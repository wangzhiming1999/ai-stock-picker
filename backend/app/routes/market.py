"""市场筛选接口：行业板块、板块成分股、全市场扫描。"""
import asyncio
import time

import akshare as ak
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/market", tags=["market"])

# 全市场快照缓存：key -> (timestamp, data)，缓存 5 分钟
_spot_cache: tuple[float, list] | None = None
_SPOT_TTL = 300  # 5 分钟


async def _get_spot() -> list:
    """获取全市场快照，带 5 分钟缓存。"""
    global _spot_cache
    now = time.monotonic()
    if _spot_cache and now - _spot_cache[0] < _SPOT_TTL:
        return _spot_cache[1]
    df = await asyncio.to_thread(ak.stock_zh_a_spot)
    rows = []
    for _, row in df.iterrows():
        try:
            rows.append(
                {
                    "code": str(row["代码"]),
                    "name": str(row["名称"]).strip(),
                    "price": float(row["最新价"]),
                    "change": float(row["涨跌幅"]),
                    "amount": float(row["成交额"]),
                }
            )
        except (ValueError, TypeError):
            continue
    _spot_cache = (now, rows)
    return rows


class ScanRequest(BaseModel):
    """全市场扫描条件"""
    min_price: float = Field(0, ge=0, description="最低股价")
    max_price: float = Field(10000, gt=0, description="最高股价")
    min_change: float = Field(-100, description="最低涨幅 %")
    max_change: float = Field(100, description="最高涨幅 %")
    min_amount_yi: float = Field(0, ge=0, description="最低成交额（亿元）")
    max_pe: float = Field(1000, gt=0, description="最高市盈率（0表示不限）")
    limit: int = Field(50, ge=1, le=200, description="返回数量上限")


@router.get("/industries")
async def get_industries():
    """A 股行业板块列表（新浪行业）。"""
    try:
        df = await asyncio.to_thread(ak.stock_sector_spot, "新浪行业")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"获取行业板块失败: {e}")
    items = []
    for _, row in df.iterrows():
        items.append(
            {
                "label": str(row["label"]),
                "name": str(row["板块"]),
                "company_count": int(row["公司家数"]),
                "change_pct": float(row["涨跌幅"]),
                "avg_price": float(row["平均价格"]),
            }
        )
    items.sort(key=lambda x: x["change_pct"], reverse=True)
    return items


@router.get("/industries/{label}/stocks")
async def get_industry_stocks(label: str):
    """某行业板块的成分股及实时行情。"""
    try:
        df = await asyncio.to_thread(ak.stock_sector_detail, label)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"获取板块成分失败: {e}")
    stocks = []
    for _, row in df.iterrows():
        try:
            stocks.append(
                {
                    "code": str(row["code"]),
                    "name": str(row["name"]),
                    "price": float(row["trade"]),
                    "change_pct": float(row["changepercent"]),
                    "volume": float(row["volume"]),
                    "amount": float(row["amount"]),
                    "pe": float(row["per"]),
                    "pb": float(row["pb"]),
                    "market_cap": float(row["mktcap"]) * 1e4,  # 万元 -> 元
                    "turnover": float(row["turnoverratio"]),
                }
            )
        except (ValueError, TypeError):
            continue
    stocks.sort(key=lambda x: x["change_pct"], reverse=True)
    return stocks


@router.post("/scan")
async def scan_market(req: ScanRequest):
    """全市场扫描选股：基于实时快照按条件过滤。

    返回符合条件且成交额靠前的股票列表，可直接作为分析候选。
    """
    try:
        spot = await _get_spot()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"获取全市场行情失败: {e}")

    results = []
    for row in spot:
        price = row["price"]
        change = row["change"]
        amount_yi = row["amount"] / 1e8
        if not (req.min_price <= price <= req.max_price):
            continue
        if not (req.min_change <= change <= req.max_change):
            continue
        if amount_yi < req.min_amount_yi:
            continue
        results.append(
            {
                "code": row["code"].replace("sh", "").replace("sz", "").replace("bj", ""),
                "symbol": row["code"],
                "name": row["name"],
                "price": price,
                "change_pct": change,
                "amount_yi": round(amount_yi, 2),
            }
        )

    results.sort(key=lambda x: x["amount_yi"], reverse=True)
    return results[: req.limit]
