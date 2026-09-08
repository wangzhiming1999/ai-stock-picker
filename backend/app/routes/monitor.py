"""盯盘监控路由：给定一批股票，实时行情 + 技术信号 → 分档操作指令。

供前端每 5 分钟轮询一次。K 线按 30 分钟内存缓存（日 K 盘中不变，避免反复拉取）。
"""
from __future__ import annotations

import asyncio
import datetime as dt
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.models import StockHistory
from app.services import data_service, signal_service

router = APIRouter(prefix="/api/market", tags=["monitor"])

_KLINE_TTL = 30 * 60  # 30 分钟
_CN_TZ = dt.timezone(dt.timedelta(hours=8))
_kline_cache: dict[str, tuple[float, StockHistory | None]] = {}
_KLINE_CACHE_MAX = 200


class MonitorRequest(BaseModel):
    codes: list[str] = Field(..., min_length=1, max_length=20, description="股票代码列表（6位纯数字）")
    force: bool = Field(False, description="强制刷新：忽略 K 线内存缓存，重新拉取")


def _get_history_cached(code: str, days: int = 120, force: bool = False) -> StockHistory | None:
    """取日 K（默认带内存缓存；force=True 时强制重新拉取）。"""
    now = time.monotonic()
    if not force:
        hit = _kline_cache.get(code)
        if hit and now - hit[0] < _KLINE_TTL:
            return hit[1]
    try:
        hist = data_service.get_history(code, days)
        history = hist if hist and hist.closes else None
    except Exception:
        history = None
    if len(_kline_cache) >= _KLINE_CACHE_MAX:
        oldest = sorted(_kline_cache, key=lambda item: _kline_cache[item][0])[: max(1, _KLINE_CACHE_MAX // 4)]
        for old_code in oldest:
            _kline_cache.pop(old_code, None)
    _kline_cache[code] = (now, history)
    return history


def _projected_volume_ratio(live_volume: float | None, historical_volumes: list[float] | None, quote_time: str | None) -> float | None:
    """Compare projected full-day volume with the recent five-day average."""
    if not live_volume or live_volume <= 0 or not historical_volumes or not quote_time:
        return None
    samples = [float(v) for v in historical_volumes[-5:] if v and float(v) > 0]
    if not samples:
        return None
    try:
        raw_time = quote_time.strip()
        if "T" in raw_time or (len(raw_time) >= 10 and raw_time[4] == "-"):
            clock = dt.datetime.fromisoformat(raw_time.replace("Z", "+00:00")).timetz()
        else:
            clock = dt.time.fromisoformat(raw_time.split()[-1][:8])
    except ValueError:
        return None
    minute = clock.hour * 60 + clock.minute + clock.second / 60
    if minute < 570:
        return None
    if minute <= 690:
        elapsed = minute - 570
    elif minute < 780:
        elapsed = 120
    else:
        elapsed = 120 + min(120, minute - 780)
    if elapsed < 15:
        return None
    progress = min(1.0, max(elapsed / 240, 1 / 240))
    average = sum(samples) / len(samples)
    return round(live_volume / (average * progress), 2) if average > 0 else None


def _advice(price: float, sig: dict) -> dict:
    """基于绝对支撑/压力/止损分档给出操作指令。"""
    support = sig["support"]
    resistance = sig["resistance"]
    stop = sig["stop_loss"]
    to_stop = (price - stop) / price * 100
    to_support = (price - support) / price * 100
    to_resist = (resistance - price) / price * 100

    if price <= stop:
        return {
            "action": "stop",
            "label": "止损离场",
            "tone": "danger",
            "hint": f"现价 {price:.2f} 已跌破止损位 {stop:.2f}，风控优先，建议离场",
            "dist": {"to_stop": round(to_stop, 2), "to_support": round(to_support, 2), "to_resistance": round(to_resist, 2)},
        }
    if price < support:
        return {
            "action": "sell",
            "label": "跌破支撑",
            "tone": "warn",
            "hint": f"现价 {price:.2f} 已跌破支撑位 {support:.2f}，暂不低吸；若不能快速收回，优先减仓，止损 {stop:.2f}",
            "dist": {"to_stop": round(to_stop, 2), "to_support": round(to_support, 2), "to_resistance": round(to_resist, 2)},
        }
    if price > resistance:
        breakout_pct = (price - resistance) / resistance * 100 if resistance > 0 else 0
        volume_ratio = sig.get("volume_ratio")
        if breakout_pct > 3:
            label = "突破过远"
            hint = f"现价 {price:.2f} 已高出压力位 {resistance:.2f} 达 {breakout_pct:.1f}%，即使放量也不追高，等待回踩确认"
        elif volume_ratio is not None and volume_ratio >= 1.5 and breakout_pct >= 0.3:
            return {
                "action": "buy",
                "label": "放量突破",
                "tone": "good",
                "hint": f"现价 {price:.2f} 突破压力位 {resistance:.2f}，盘中量比 {volume_ratio:.2f}x；可等回踩不破后分批关注",
                "dist": {"to_stop": round(to_stop, 2), "to_support": round(to_support, 2), "to_resistance": round(to_resist, 2)},
            }
        elif volume_ratio is not None and volume_ratio < 1.0:
            label = "缩量突破"
            hint = f"现价 {price:.2f} 突破压力位 {resistance:.2f}，但盘中量比仅 {volume_ratio:.2f}x，暂按假突破风险观察"
        else:
            label = "突破待确认"
            volume_text = f"，盘中量比 {volume_ratio:.2f}x" if volume_ratio is not None else "，量能数据不足"
            hint = f"现价 {price:.2f} 突破压力位 {resistance:.2f}{volume_text}；等待站稳或回踩确认"
        return {
            "action": "hold",
            "label": label,
            "tone": "neutral",
            "hint": hint,
            "dist": {"to_stop": round(to_stop, 2), "to_support": round(to_support, 2), "to_resistance": round(to_resist, 2)},
        }
    if 0 <= to_resist <= 0.5:
        return {
            "action": "sell",
            "label": "压力减仓",
            "tone": "warn",
            "hint": f"现价 {price:.2f} 逼近压力位 {resistance:.2f}，可分批止盈/减仓",
            "dist": {"to_stop": round(to_stop, 2), "to_support": round(to_support, 2), "to_resistance": round(to_resist, 2)},
        }
    if 0 <= to_support <= 1.0 and price > stop:
        return {
            "action": "buy",
            "label": "回踩可买",
            "tone": "good",
            "hint": f"现价 {price:.2f} 回踩支撑位 {support:.2f}，若企稳可分批低吸，止损 {stop:.2f}",
            "dist": {"to_stop": round(to_stop, 2), "to_support": round(to_support, 2), "to_resistance": round(to_resist, 2)},
        }
    return {
        "action": "hold",
        "label": "持有观察",
        "tone": "neutral",
        "hint": f"区间震荡中：距压力位 {to_resist:.1f}%，距支撑位 {to_support:.1f}%，距止损 {to_stop:.1f}%",
        "dist": {"to_stop": round(to_stop, 2), "to_support": round(to_support, 2), "to_resistance": round(to_resist, 2)},
    }


@router.post("/monitor")
async def monitor(req: MonitorRequest):
    """批量监控：实时行情 + 日 K 信号 → 每只给操作指令。

    force=true 时忽略 30 分钟 K 线内存缓存，重新拉取（供「立即刷新」使用）。
    """
    seen: list[str] = []
    for c in req.codes:
        c = (c or "").strip().replace("sh", "").replace("sz", "").replace("bj", "").replace(".", "")
        if c and c.isdigit() and c not in seen:
            seen.append(c)
    if not seen:
        raise HTTPException(status_code=400, detail="代码格式不正确")

    try:
        quotes = await asyncio.to_thread(data_service.get_spot_quote, seen)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"获取实时行情失败: {e}")

    quote_map = {q.code: q for q in quotes}
    sem = asyncio.Semaphore(12)

    async def _k(code: str):
        async with sem:
            return await asyncio.to_thread(_get_history_cached, code, 120, req.force)

    histories = await asyncio.gather(*(_k(c) for c in seen))
    history_map = dict(zip(seen, histories))

    items = []
    for code in seen:
        q = quote_map.get(code)
        history = history_map.get(code)
        if not q or not history or not history.closes:
            continue
        historical_volumes = list(history.volumes or [])
        if history.dates and q.quote_time and history.dates[-1] == q.quote_time[:10]:
            historical_volumes = historical_volumes[:-1]
        volume_ratio = _projected_volume_ratio(q.volume, historical_volumes, q.quote_time)
        sig = signal_service.compute_signals(history.closes, q.price)
        if not sig:
            continue
        sig["volume_ratio"] = volume_ratio
        sig_out = {
            "support": sig["support"],
            "resistance": sig["resistance"],
            "buy_point": sig["buy_point"],
            "sell_point": sig["sell_point"],
            "stop_loss": sig["stop_loss"],
            "rr_ratio": sig["rr_ratio"],
            "strength": sig["strength"],
            "ma20": sig["ma20"],
            "ma60": sig["ma60"],
            "high60": sig["high60"],
            "low60": sig["low60"],
            "volume_ratio": volume_ratio,
        }
        items.append(
            {
                "code": code,
                "name": q.name,
                "price": round(q.price, 2),
                "change_pct": round(q.change_pct or 0, 2),
                "turnover": round(q.turnover, 2) if q.turnover is not None else None,
                "quote_at": q.quote_time,
                "signal": sig_out,
                "advice": _advice(q.price, sig),
            }
        )

    completed = {item["code"] for item in items}
    missed = [c for c in seen if c not in completed]
    now = dt.datetime.now(dt.timezone.utc).astimezone(_CN_TZ)
    quote_times = []
    for q in quotes:
        if not q.quote_time:
            continue
        try:
            parsed = dt.datetime.fromisoformat(q.quote_time)
            quote_times.append(parsed if parsed.tzinfo else parsed.replace(tzinfo=_CN_TZ))
        except ValueError:
            continue
    latest_quote_at = max(quote_times) if quote_times else None
    freshness_seconds = max(0, int((now - latest_quote_at).total_seconds())) if latest_quote_at else None
    local_time = now.time()
    market_open = now.weekday() < 5 and (
        dt.time(9, 15) <= local_time <= dt.time(11, 30)
        or dt.time(13, 0) <= local_time <= dt.time(15, 0)
    )
    return {
        "updated_at": now.isoformat(timespec="seconds"),
        "quote_at": latest_quote_at.isoformat(timespec="seconds") if latest_quote_at else None,
        "freshness_seconds": freshness_seconds,
        "freshness": (
            "unknown"
            if freshness_seconds is None
            else "closed"
            if not market_open
            else "stale"
            if freshness_seconds > 90
            else "live"
        ),
        "market_open": market_open,
        "poll_interval_seconds": 20 if market_open else 300,
        "count": len(items),
        "missed": missed,
        "items": items,
    }
