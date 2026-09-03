"""市场筛选接口：行业板块、板块成分股、全市场扫描、策略选股、明日推衍。"""
import asyncio
import time

import akshare as ak
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import data_service, market_prediction, opportunity_service, recommend_service, winrate_service

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


class StrategyScanRequest(BaseModel):
    """策略选股请求"""
    strategy: str = Field("momentum", description="策略: momentum/trend/value/volume")
    limit: int = Field(20, ge=5, le=50, description="返回数量")
    min_amount_yi: float = Field(3, ge=0, description="最低成交额（亿元），过滤冷门股")


def _is_tradable(row: dict) -> bool:
    """过滤 ST、退市、停牌、次新股等不可交易标的（仅匹配前缀，避免误杀 TCL 等含字母名称）。"""
    name = (row.get("name") or "").strip().upper()
    price = row.get("price", 0)
    if name.startswith(("ST", "*ST", "N", "C")) or "退" in name:
        return False
    if price <= 1 or price > 500:
        return False
    return True


def _compute_indicators(closes: list[float]) -> dict | None:
    """基于收盘价计算技术指标（MA5/MA20/MA60/MACD/RSI）。"""
    if len(closes) < 61:
        return None
    price = closes[-1]
    ma5 = sum(closes[-5:]) / 5
    ma20 = sum(closes[-20:]) / 20
    ma60 = sum(closes[-60:]) / 60

    # MACD (12, 26, 9)
    ema12, ema26 = closes[0], closes[0]
    difs = []
    for c in closes:
        ema12 = ema12 + (c - ema12) * 2 / 13
        ema26 = ema26 + (c - ema26) * 2 / 27
        difs.append(ema12 - ema26)
    dea = sum(difs[-9:]) / 9
    macd = (difs[-1] - dea) * 2

    # RSI(14)
    gains, losses = [], []
    for i in range(1, 15):
        diff = closes[-14 + i] - closes[-15 + i]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains) / 14
    avg_loss = sum(losses) / 14
    rsi = 100 - 100 / (1 + avg_gain / avg_loss) if avg_loss > 0 else 100

    return {
        "price": price,
        "ma5": ma5,
        "ma20": ma20,
        "ma60": ma60,
        "macd": macd,
        "dif": difs[-1],
        "dea": dea,
        "rsi": rsi,
        "pct_from_high": (price / max(closes) - 1) * 100,
    }


async def _apply_strategy(codes: list[str], strategy: str) -> list[dict]:
    """对候选代码应用策略过滤与评分。codes 已按成交额预排序。"""
    # 1. 批量补充腾讯行情（PE/PB/换手率/市值）
    quotes = await asyncio.to_thread(data_service.get_spot_quote, codes)
    quote_map = {q.code: q for q in quotes}

    # 2. 拉历史K线（并发，仅策略需要时）
    if strategy in ("trend", "momentum", "volume"):
        histories = await asyncio.gather(
            *(asyncio.to_thread(data_service.get_history, c, 100) for c in codes[:30])
        )
        hist_map = {c: h for c, h in zip(codes[:30], histories)}
    else:
        hist_map = {}

    results = []
    for code in codes[:30]:
        q = quote_map.get(code)
        if not q:
            continue
        hist = hist_map.get(code)
        closes = hist.closes if hist and hist.closes else None
        ind = _compute_indicators(closes) if closes else None
        turnover = q.turnover or 0

        # 通用过滤：排除停牌（成交量过低）
        if q.volume and q.volume < 1000:
            continue

        score = 0.0
        tags: list[str] = []
        detail: dict = {}

        if strategy == "momentum":
            # 动量：站上 MA5，MACD 上方，RSI 健康(50-75)，接近阶段新高
            if ind:
                if ind["price"] > ind["ma5"]:
                    score += 2
                    tags.append("站上MA5")
                if ind["macd"] > 0:
                    score += 2
                    tags.append("MACD多头")
                if 50 <= ind["rsi"] <= 75:
                    score += 2
                    tags.append("RSI健康")
                if ind["pct_from_high"] > -10:
                    score += 2
                    tags.append("接近新高")
                score += max(0, q.change_pct) * 0.3
                detail = {k: round(v, 2) for k, v in ind.items() if k in ("ma5", "ma20", "rsi", "macd", "pct_from_high")}

        elif strategy == "trend":
            # 趋势多头：MA5>MA20>MA60 完美多头排列
            if ind and ind["ma5"] > ind["ma20"] > ind["ma60"] and ind["price"] > ind["ma5"]:
                score += 5
                tags.append("均线多头")
                score += min(3, ind["pct_from_high"] * 0.15)
                tags.append("趋势上行")
            detail = {k: round(v, 2) for k, v in ind.items() if k in ("ma5", "ma20", "ma60", "pct_from_high")} if ind else {}

        elif strategy == "value":
            # 低估值：PE/PB 合理 + 有换手
            if q.pe and 0 < q.pe <= 30:
                score += 3
                tags.append(f"PE{q.pe:.1f}")
            if q.pb and 0 < q.pb <= 3:
                score += 2
                tags.append(f"PB{q.pb:.1f}")
            if 0.5 <= turnover <= 5:
                score += 1
                tags.append("交投健康")
            detail = {"pe": q.pe, "pb": q.pb, "turnover": round(turnover, 2)}

        elif strategy == "volume":
            # 放量活跃：换手率适中、涨幅健康、MACD 转强
            if 2 <= turnover <= 12:
                score += 3
                tags.append("量能活跃")
            if 0 < q.change_pct <= 8:
                score += 2
                tags.append("温和上涨")
            if ind and ind["macd"] > 0:
                score += 2
                tags.append("MACD转强")
            detail = {"turnover": round(turnover, 2), "change_pct": q.change_pct}

        if score > 0:
            results.append(
                {
                    "code": q.code,
                    "name": q.name,
                    "price": q.price,
                    "change_pct": q.change_pct,
                    "pe": q.pe,
                    "pb": q.pb,
                    "turnover": round(turnover, 2),
                    "market_cap_yi": round(q.market_cap / 1e8, 1) if q.market_cap else None,
                    "strategy_score": round(score, 2),
                    "tags": tags,
                    "indicators": detail,
                }
            )

    results.sort(key=lambda x: x["strategy_score"], reverse=True)
    return results


@router.post("/strategy-scan")
async def strategy_scan(req: StrategyScanRequest):
    """策略选股：动量/趋势/低估值/放量。

    流程：全市场快照预筛 → 按成交额取候选 → 补充行情与K线 → 策略评分排序。
    """
    strategies = {"momentum", "trend", "value", "volume"}
    if req.strategy not in strategies:
        raise HTTPException(status_code=400, detail=f"未知策略 {req.strategy}，可选: {strategies}")

    try:
        spot = await _get_spot()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"获取全市场行情失败: {e}")

    # 预筛：可交易 + 成交额达标，按成交额降序取前 40
    candidates = []
    for row in spot:
        if not _is_tradable(row):
            continue
        if row["amount"] / 1e8 < req.min_amount_yi:
            continue
        code = row["code"].replace("sh", "").replace("sz", "").replace("bj", "")
        candidates.append({"code": code, "name": row["name"], "price": row["price"], "change": row["change"], "amount": row["amount"]})

    candidates.sort(key=lambda x: x["amount"], reverse=True)
    codes = [c["code"] for c in candidates[:40]]

    results = await _apply_strategy(codes, req.strategy)
    return results[: req.limit]


@router.get("/search")
async def search_stocks(q: str = "", limit: int = 10):
    """按名称或代码模糊搜索股票（基于全市场快照缓存）。"""
    q = q.strip().upper().replace(" ", "")
    if not q:
        return []
    try:
        spot = await _get_spot()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"搜索失败: {e}")
    results = []
    for row in spot:
        name = row.get("name", "").replace(" ", "")
        code = row["code"].replace("sh", "").replace("sz", "").replace("bj", "")
        if q in name.upper() or q in code:
            results.append(
                {
                    "code": code,
                    "name": row.get("name", "").strip(),
                    "price": row["price"],
                    "change_pct": row["change"],
                }
            )
            if len(results) >= limit:
                break
    return results


@router.get("/winrate")
async def winrate_endpoint():
    """胜率看板：预测命中率 + 推荐胜率统计。"""
    return await winrate_service.get_winrate_stats()


@router.get("/daily-recommend")
async def daily_recommend_endpoint(refresh: bool = False):
    """每日收盘推荐：策略扫描候选 + LLM 精选 10 只并给出推荐理由。

    refresh=true 时强制重跑（绕过当日缓存）。
    """
    try:
        return await recommend_service.generate_daily_recommendations(force_refresh=refresh)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"每日推荐失败: {e}")


@router.get("/prediction")
async def market_prediction_endpoint(refresh: bool = False):
    """明日大盘推衍：基于上证指数技术信号 + LLM 预测次日走势。

    refresh=true 时强制重跑（绕过当日缓存）。
    """
    try:
        return await market_prediction.predict_tomorrow(force_refresh=refresh)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"大盘推衍失败: {e}")


@router.get("/prediction/index-history")
async def index_history_endpoint(days: int = 120):
    """上证指数历史 K 线（供大盘走势图使用，只读行情、不跑 LLM，速度快）。"""
    days = max(20, min(days, 500))
    try:
        hist = await market_prediction.asyncio_hist()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"获取指数K线失败: {e}")
    hist = hist[-days:]
    if not hist:
        raise HTTPException(status_code=502, detail="未获取到指数K线数据")
    closes = [h["close"] for h in hist]
    return {
        "index": market_prediction.MARKET_NAME,
        "dates": [h["date"] for h in hist],
        "opens": [h["open"] for h in hist],
        "highs": [h["high"] for h in hist],
        "lows": [h["low"] for h in hist],
        "closes": closes,
        "volumes": [h["volume"] for h in hist],
        "latest": closes[-1] if closes else None,
        "change_pct": round((closes[-1] / closes[-2] - 1) * 100, 2) if len(closes) >= 2 else None,
        "days": len(hist),
    }


@router.post("/prediction/settle")
async def settle_prediction_endpoint():
    """结算预测：对比最近一个交易日的实际走势，标记命中/未命中。"""
    try:
        n = await market_prediction.settle_predictions()
        return {"settled": n}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"结算失败: {e}")


@router.get("/prediction/stats")
async def prediction_stats_endpoint():
    """预测准确率统计。"""
    try:
        return await market_prediction.get_prediction_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"stats 计算失败: {type(e).__name__}: {e}")


@router.get("/prediction/history")
async def prediction_history_endpoint(limit: int = 30):
    """历史预测记录（含结算结果）。"""
    return await market_prediction.get_prediction_history(limit)


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


@router.get("/opportunity/auction")
async def auction_opportunity_endpoint(limit: int = 15, force: bool = False):
    """早盘竞价机会（9:15-9:30），博当日大涨。

    优先返回 DB 当日缓存（自动 cron / 用户手动写入）。
    force=true 时绕过缓存，立即扫描并写回缓存。
    """
    try:
        return await opportunity_service.get_auction_opportunity_detail(limit, force=force)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"早盘竞价扫描失败: {e}")


@router.get("/opportunity/closing")
async def closing_opportunity_endpoint(limit: int = 15, force: bool = False):
    """尾盘机会（14:45-15:00），博次日高开/继续上涨。

    优先返回 DB 当日缓存（自动 cron / 用户手动写入）。
    force=true 时绕过缓存，立即扫描并写回缓存。
    """
    try:
        return await opportunity_service.get_closing_opportunity_detail(limit, force=force)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"尾盘扫描失败: {e}")
