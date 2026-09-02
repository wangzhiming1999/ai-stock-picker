"""早盘竞价 / 尾盘机会选股。

- 早盘竞价（9:15-9:30）：开盘强势、博当日大涨
- 尾盘机会（14:45-15:00）：尾盘异动、博次日高开

数据源：akshare 全市场实时快照（东财），短缓存 60s。
"""
from __future__ import annotations

import asyncio
import re
import time

import akshare as ak

_SHORT_CACHE: dict[str, tuple[float, list[dict]]] = {}
_TTL = 60


async def _get_rich_spot() -> list[dict]:
    """全市场实时快照（含量比/换手/委比/5分钟涨跌）。短缓存 60s。

    优先东财（em）含丰富字段；若网络/超时失败则 fallback 腾讯（基础字段）。
    """
    key = "rich_spot"
    now = time.monotonic()
    if key in _SHORT_CACHE and now - _SHORT_CACHE[key][0] < _TTL:
        return _SHORT_CACHE[key][1]

    rows: list[dict] = []
    # 优先东财接口（含 量比/换手/5分钟涨跌）
    try:
        df = await asyncio.to_thread(ak.stock_zh_a_spot_em)
        for _, row in df.iterrows():
            try:
                amount = float(row.get("成交额", 0))
                rows.append(
                    {
                        "code": str(row.get("代码", "")).replace("sh", "").replace("sz", "").replace("bj", ""),
                        "name": str(row.get("名称", "")).strip(),
                        "price": float(row.get("最新价", 0)),
                        "change_pct": float(row.get("涨跌幅", 0)),
                        "amount_yi": amount / 1e8,
                        "volume_ratio": float(row.get("量比", 0) or 0),
                        "turnover": float(row.get("换手率", 0) or 0),
                        "pe": float(row.get("市盈率(动)", 0) or 0),
                        "amplitude": float(row.get("振幅", 0) or 0),
                        "change_5min": float(row.get("5分钟涨跌", 0) or 0),
                    }
                )
            except (ValueError, TypeError):
                continue
    except Exception as e:
        # Fallback：腾讯基础接口（基础字段，量比/换手/5分钟涨跌不可用）
        try:
            df = await asyncio.to_thread(ak.stock_zh_a_spot)
            for _, row in df.iterrows():
                try:
                    amount = float(row.get("成交额", 0))
                    rows.append(
                        {
                            "code": str(row.get("代码", "")).replace("sh", "").replace("sz", "").replace("bj", ""),
                            "name": str(row.get("名称", "")).strip(),
                            "price": float(row.get("最新价", 0)),
                            "change_pct": float(row.get("涨跌幅", 0)),
                            "amount_yi": amount / 1e8,
                            "volume_ratio": 0,
                            "turnover": 0,
                            "pe": 0,
                            "amplitude": float(row.get("振幅", 0) or 0),
                            "change_5min": 0,
                        }
                    )
                except (ValueError, TypeError):
                    continue
        except Exception as e2:
            raise RuntimeError(f"获取全市场快照失败: {e2}")

    _SHORT_CACHE[key] = (now, rows)
    return rows


_ST_NAME = re.compile("ST|\*ST")


def _is_valid_name(name: str) -> bool:
    return bool(name) and not _ST_NAME.search(name)


async def get_auction_opportunity(limit: int = 15) -> list[dict]:
    """早盘竞价机会（9:15-9:30），目标：当日大涨。

    选股条件（同时满足）：
    - 涨幅 >= 1.5%（开盘强势）
    - 量比 >= 1.5（成交活跃）
    - 成交额 >= 5000万
    - 排除 ST / *ST
    - 排除涨停（>=9.8% 创业板>=19.8%）
    - 价格 2-200 元（避免过冷/过高）

    评分 = 涨幅 * 0.6 + 量比 * 0.4（取top）
    """
    try:
        rows = await _get_rich_spot()
    except Exception as e:
        raise RuntimeError(f"获取全市场快照失败: {e}")

    candidates: list[dict] = []
    for r in rows:
        try:
            if not _is_valid_name(r["name"]):
                continue
            price = r["price"]
            change = r["change_pct"]
            amount_yi = r["amount_yi"]
            vol_ratio = r["volume_ratio"]
            if not (2 <= price <= 200):
                continue
            if abs(change) < 1.5 or abs(change) >= 9.5:
                continue
            # 量比：fallback 数据缺失（=0）时跳过该过滤
            if vol_ratio and vol_ratio < 1.5:
                continue
            if amount_yi < 0.5:
                continue
            # 评分（量比缺失时仅按涨幅）
            if vol_ratio > 0:
                score = change * 0.6 + vol_ratio * 0.4
            else:
                score = change
            candidates.append({**r, "score": round(score, 2), "stage": "auction"})
        except (KeyError, TypeError):
            continue
    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:limit]


async def get_closing_opportunity(limit: int = 15) -> list[dict]:
    """尾盘机会（14:45-15:00），目标：次日高开/继续上涨。

    选股条件（同时满足）：
    - 涨幅 0.2% ~ 6%（尾盘强势但非涨停）
    - 量比 >= 1.5
    - 换手率 >= 1.5%（流通活跃）
    - 5分钟涨跌 >= 0.3%（尾盘翘尾）
    - 成交额 >= 1亿
    - 排除 ST / *ST

    评分 = 涨幅*0.5 + 5分钟涨跌*0.3 + 量比*0.2
    """
    try:
        rows = await _get_rich_spot()
    except Exception as e:
        raise RuntimeError(f"获取全市场快照失败: {e}")

    candidates: list[dict] = []
    for r in rows:
        try:
            if not _is_valid_name(r["name"]):
                continue
            price = r["price"]
            change = r["change_pct"]
            amount_yi = r["amount_yi"]
            vol_ratio = r["volume_ratio"]
            turnover = r["turnover"]
            change_5min = r["change_5min"]
            if not (2 <= price <= 300):
                continue
            if not (0.2 <= change <= 6):
                continue
            # fallback 时字段=0，跳过相应过滤
            if vol_ratio and vol_ratio < 1.5:
                continue
            if turnover and turnover < 1.5:
                continue
            if change_5min and change_5min < 0.3:
                continue
            if amount_yi < 1:
                continue
            # 评分（缺失字段按 0 计入）
            score = (
                change * 0.5
                + (change_5min if change_5min > 0 else 0) * 0.3
                + (vol_ratio if vol_ratio > 0 else 0) * 0.2
            )
            candidates.append({**r, "score": round(score, 2), "stage": "closing"})
        except (KeyError, TypeError):
            continue
    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:limit]