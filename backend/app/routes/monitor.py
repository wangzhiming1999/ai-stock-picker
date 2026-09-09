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
from app.services import data_service, intraday_service, signal_service

router = APIRouter(prefix="/api/market", tags=["monitor"])

_KLINE_TTL = 30 * 60  # 30 分钟
_CN_TZ = dt.timezone(dt.timedelta(hours=8))
_kline_cache: dict[str, tuple[float, StockHistory | None]] = {}
_KLINE_CACHE_MAX = 200


class MonitorRequest(BaseModel):
    codes: list[str] = Field(..., min_length=1, max_length=20, description="股票代码列表（6位纯数字）")
    force: bool = Field(False, description="强制刷新：忽略 K 线内存缓存，重新拉取")
    costs: dict[str, float] = Field(default_factory=dict, description="持仓成本价 {code: cost}，传入后指令带盈亏视角")
    interval: str = Field("1d", description="决策周期：1d 日线（战略）/ 5m / 15m / 30m / 60m 分钟线（日内战术）")


_VALID_INTERVALS = {"1d", "1m", "5m", "15m", "30m", "60m"}


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


def _position_pct(sig: dict) -> int:
    """建议仓位（%）：信号强度 + 风报比 + 盘中量能，仅买入情形有意义。"""
    pct = 20
    strength = sig.get("strength") or 5
    if strength >= 8:
        pct += 20
    elif strength >= 6.5:
        pct += 10
    if (sig.get("rr_ratio") or 0) >= 2:
        pct += 10
    vr = sig.get("volume_ratio")
    if vr is not None and vr >= 1.5:
        pct += 10
    return int(max(10, min(60, pct)))


def _build_plan(price: float, sig: dict, action: str) -> dict:
    """把技术信号翻译成可直接下单的一组价位。"""
    support = sig["support"]
    resistance = sig["resistance"]
    stop = sig["stop_loss"]
    buy = sig.get("buy_point") or max(price * 0.99, support)
    sell = sig.get("sell_point") or min(price * 1.01, resistance)
    if price > resistance:
        # 已突破压力：压力位转为回踩确认位，跌回去就该走
        sell = round(resistance, 2)
    urgency = "low"
    if action in ("stop", "sell"):
        urgency = "high"
    elif action == "buy":
        urgency = "high" if support > 0 and (price - support) / price <= 0.003 else "mid"
    return {
        "buy": round(buy, 2),
        "sell": round(sell, 2),
        "stop": round(stop, 2),
        "target": round(resistance, 2),
        "position_pct": _position_pct(sig) if action == "buy" else 0,
        "urgency": urgency,
    }


def _do_text(action: str, plan: dict) -> str:
    """一句话指令：打开就知道干什么。"""
    if action == "stop":
        return f"现价止损，跌破 {plan['stop']:.2f} 走"
    if action == "buy":
        return f"挂 {plan['buy']:.2f} 买入 · {plan['position_pct']}% 仓"
    if action == "sell":
        return f"挂 {plan['sell']:.2f} 减仓/止盈"
    return f"观望 · {plan['buy']:.2f} 低吸 / {plan['sell']:.2f} 减仓 / {plan['stop']:.2f} 止损"


def _with_cost(advice: dict, price: float, cost: float, sig: dict) -> dict:
    """叠加持仓成本视角：盈亏感知的买卖指令。"""
    if not cost or cost <= 0:
        return advice
    pnl = (price - cost) / cost * 100
    advice = dict(advice)
    plan = dict(advice.get("plan") or {})
    # 硬止损：最多亏 7%，与技术止损取更紧的一个
    plan["stop"] = round(min(plan.get("stop") or sig["stop_loss"], cost * 0.93), 2)
    advice["pnl_pct"] = round(pnl, 2)

    if advice["action"] == "stop":
        advice["hint"] = f"现价 {price:.2f} 已跌破止损位 {plan['stop']:.2f}（成本 {cost:.2f}，浮亏 {pnl:.1f}%），风控优先，建议离场"
    elif advice["action"] == "hold":
        if pnl >= 12:
            plan["sell"] = round(max(price * 0.99, cost * 1.05), 2)
            advice.update(
                action="sell",
                label="盈利止盈",
                tone="warn",
                hint=f"浮盈 {pnl:.1f}%（成本 {cost:.2f}），可分批兑现；跌破 {plan['sell']:.2f} 先减半",
            )
        elif pnl <= -7:
            advice.update(
                action="sell",
                label="逼近止损",
                tone="danger",
                hint=f"浮亏 {pnl:.1f}%（成本 {cost:.2f}），距硬止损 {plan['stop']:.2f} 很近，反抽无力先减仓",
            )
    elif advice["action"] == "buy" and pnl > 0:
        advice["hint"] = f"{advice['hint']}；已有浮盈 {pnl:.1f}%，加仓控制在半仓内"
    advice["plan"] = plan
    advice["do"] = _do_text(advice["action"], plan)
    return advice


def _advice(price: float, sig: dict) -> dict:
    """基于绝对支撑/压力/止损分档给出操作指令（含可执行价位）。"""
    support = sig["support"]
    resistance = sig["resistance"]
    stop = sig["stop_loss"]
    to_stop = (price - stop) / price * 100
    to_support = (price - support) / price * 100
    to_resist = (resistance - price) / price * 100
    dist = {"to_stop": round(to_stop, 2), "to_support": round(to_support, 2), "to_resistance": round(to_resist, 2)}

    def _pack(action: str, label: str, tone: str, hint: str) -> dict:
        plan = _build_plan(price, sig, action)
        return {
            "action": action,
            "label": label,
            "tone": tone,
            "hint": hint,
            "plan": plan,
            "do": _do_text(action, plan),
            "dist": dist,
        }

    if price <= stop:
        return _pack("stop", "止损离场", "danger", f"现价 {price:.2f} 已跌破止损位 {stop:.2f}，风控优先，建议离场")
    if price < support:
        return _pack("sell", "跌破支撑", "warn", f"现价 {price:.2f} 已跌破支撑位 {support:.2f}，暂不低吸；若不能快速收回，优先减仓，止损 {stop:.2f}")
    if price > resistance:
        breakout_pct = (price - resistance) / resistance * 100 if resistance > 0 else 0
        volume_ratio = sig.get("volume_ratio")
        if breakout_pct > 3:
            label = "突破过远"
            hint = f"现价 {price:.2f} 已高出压力位 {resistance:.2f} 达 {breakout_pct:.1f}%，即使放量也不追高，等待回踩 {resistance:.2f} 确认"
        elif volume_ratio is not None and volume_ratio >= 1.5 and breakout_pct >= 0.3:
            return _pack("buy", "放量突破", "good", f"现价 {price:.2f} 突破压力位 {resistance:.2f}，盘中量比 {volume_ratio:.2f}x；可等回踩不破后分批关注")
        elif volume_ratio is not None and volume_ratio < 1.0:
            label = "缩量突破"
            hint = f"现价 {price:.2f} 突破压力位 {resistance:.2f}，但盘中量比仅 {volume_ratio:.2f}x，暂按假突破风险观察"
        else:
            label = "突破待确认"
            volume_text = f"，盘中量比 {volume_ratio:.2f}x" if volume_ratio is not None else "，量能数据不足"
            hint = f"现价 {price:.2f} 突破压力位 {resistance:.2f}{volume_text}；等待站稳或回踩确认"
        return _pack("hold", label, "neutral", hint)
    if 0 <= to_resist <= 0.5:
        return _pack("sell", "压力减仓", "warn", f"现价 {price:.2f} 逼近压力位 {resistance:.2f}，可分批止盈/减仓")
    if 0 <= to_support <= 1.0 and price > stop:
        return _pack("buy", "回踩可买", "good", f"现价 {price:.2f} 回踩支撑位 {support:.2f}，若企稳可分批低吸，止损 {stop:.2f}")
    return _pack("hold", "持有观察", "neutral", f"区间震荡中：距压力位 {to_resist:.1f}%，距支撑位 {to_support:.1f}%，距止损 {to_stop:.1f}%")


_ACTION_ORDER = {"stop": 0, "sell": 1, "buy": 2, "hold": 3}


def _sort_key(item: dict) -> tuple:
    """需要立刻操作的排最前：止损 > 卖出 > 买入 > 观望。"""
    advice = item.get("advice") or {}
    plan = advice.get("plan") or {}
    return (
        _ACTION_ORDER.get(advice.get("action"), 9),
        0 if plan.get("urgency") == "high" else 1,
        item.get("code", ""),
    )


def _summary(items: list[dict]) -> dict:
    """顶层决策摘要：一眼知道现在有几只要操作、分别干什么。"""
    def _count(action: str) -> int:
        return sum(1 for i in items if (i.get("advice") or {}).get("action") == action)

    acting = sorted(
        (i for i in items if (i.get("advice") or {}).get("action") != "hold"),
        key=_sort_key,
    )
    return {
        "total": len(items),
        "act_now": len(acting),
        "stop": _count("stop"),
        "sell": _count("sell"),
        "buy": _count("buy"),
        "hold": _count("hold"),
        "top": [
            {
                "code": i["code"],
                "name": i.get("name") or i["code"],
                "price": i.get("price"),
                "action": i["advice"]["action"],
                "label": i["advice"]["label"],
                "tone": i["advice"]["tone"],
                "do": i["advice"].get("do") or "",
            }
            for i in acting[:8]
        ],
    }


@router.post("/monitor")
async def monitor(req: MonitorRequest):
    """批量监控：实时行情 + K 线信号 → 每只给操作指令。

    force=true 时忽略 30 分钟 K 线内存缓存，重新拉取（供「立即刷新」使用）。
    interval 选分钟周期时按日内逻辑决策，同时始终返回日线战略位（daily）。
    """
    interval = req.interval if req.interval in _VALID_INTERVALS else "1d"
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

    # 分钟线只在需要时拉取（盘中 60s 缓存由 data_service 维护）
    intraday_map: dict[str, object] = {}
    if interval != "1d":
        sem_m = asyncio.Semaphore(8)

        async def _m(code: str):
            async with sem_m:
                return await asyncio.to_thread(data_service.get_intraday_history, code, interval)

        intraday_map = dict(zip(seen, await asyncio.gather(*(_m(c) for c in seen))))

    items = []
    degraded = False
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
        # 日线锚点：无论用哪个周期决策，都给出战略位，避免日内被日线大方向反着做
        daily_out = {
            "support": sig["support"],
            "resistance": sig["resistance"],
            "buy_point": sig["buy_point"],
            "sell_point": sig["sell_point"],
            "stop_loss": sig["stop_loss"],
            "strength": sig["strength"],
            "ma20": sig["ma20"],
            "ma60": sig["ma60"],
        }

        # 主决策：分钟周期优先，拿不到分钟数据时降级回日线
        intraday_sig = None
        if interval != "1d":
            ih = intraday_map.get(code)
            if ih:
                intraday_sig = intraday_service.compute_intraday_signals(ih, q.price, interval)
            if intraday_sig is None:
                degraded = True

        if intraday_sig is not None:
            sig_out = dict(intraday_sig)
            sig_out["volume_ratio"] = intraday_sig.get("volume_ratio")
            advice = intraday_service.intraday_advice(q.price, intraday_sig, interval)
        else:
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
            advice = _advice(q.price, sig)

        cost = req.costs.get(code)
        if cost:
            advice = _with_cost(advice, q.price, float(cost), sig)
        items.append(
            {
                "code": code,
                "name": q.name,
                "price": round(q.price, 2),
                "change_pct": round(q.change_pct or 0, 2),
                "turnover": round(q.turnover, 2) if q.turnover is not None else None,
                "quote_at": q.quote_time,
                "signal": sig_out,
                "advice": advice,
                "daily": daily_out,
            }
        )

    items.sort(key=_sort_key)
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
        "interval": interval,
        # 分钟数据不可用时自动降级为日线决策，前端据此提示用户
        "degraded": degraded and interval != "1d",
        "summary": _summary(items),
        "items": items,
    }
