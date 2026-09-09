"""分钟级（5/15/30/60 分）技术信号与日内买卖决策。

与 `signal_service`（日线，定战略位）分工：
- 日线回答「这只票现在处在什么位置、大方向如何」
- 分钟线回答「就今天这一笔，现在该不该动手」

日内核心锚点是 **VWAP（当日成交量加权均价）**——机构执行基准，
价格在其上方为多头控盘，反之为空头控盘。配合日内高低点、分钟均线、
分钟布林带与分钟量比，给出可执行到价的挂单计划。

日内决策的止损显著紧于日线（0.5%~1.5%），因为日内只赚一小段波动，
不允许用日线级别的 3% 止损扛单。
"""
from __future__ import annotations

import statistics

# 各周期参数：止损带（相对现价的上下限）与建议仓位区间。
# 止损整体压在 1.5% 以内 —— 日内只赚一小段波动，不允许用波段级别的容忍度扛单；
# 周期越短止损越紧（5m 噪点多，必须更快认错）。
_PERIOD_PROFILE = {
    "1m": {"stop_lo": 0.994, "stop_hi": 0.998, "pos_lo": 10, "pos_hi": 25},
    "5m": {"stop_lo": 0.992, "stop_hi": 0.997, "pos_lo": 10, "pos_hi": 30},
    "15m": {"stop_lo": 0.989, "stop_hi": 0.995, "pos_lo": 15, "pos_hi": 35},
    "30m": {"stop_lo": 0.987, "stop_hi": 0.993, "pos_lo": 20, "pos_hi": 40},
    "60m": {"stop_lo": 0.985, "stop_hi": 0.991, "pos_lo": 20, "pos_hi": 45},
}
_DEFAULT_PROFILE = _PERIOD_PROFILE["15m"]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def compute_intraday_signals(hist, price: float, period: str = "15m") -> dict | None:
    """基于分钟 K 线计算日内信号。

    hist 需带 OHLC（opens/highs/lows），由 `data_service.get_intraday_history` 提供。
    """
    if not hist or not hist.closes or len(hist.closes) < 30:
        return None
    highs = hist.highs or []
    lows = hist.lows or []
    opens = hist.opens or []
    volumes = hist.volumes or []
    if not (len(highs) == len(lows) == len(opens) == len(volumes) == len(hist.closes)):
        return None

    closes = hist.closes
    dates = hist.dates
    session = str(dates[-1])[:8]

    # 当日（最后一根 K 线所属交易日）的 bar 索引 —— VWAP 与日内高低都只按当日算
    day_idx = [i for i, d in enumerate(dates) if str(d)[:8] == session]
    day_open = opens[day_idx[0]] if day_idx else None
    day_high = max(highs[i] for i in day_idx) if day_idx else None
    day_low = min(lows[i] for i in day_idx) if day_idx else None

    vwap: float | None = None
    if day_idx:
        weighted = sum(
            ((highs[i] + lows[i] + closes[i]) / 3) * (volumes[i] or 0) for i in day_idx
        )
        total_vol = sum((volumes[i] or 0) for i in day_idx)
        vwap = weighted / total_vol if total_vol > 0 else None

    ma_fast = _mean(closes[-5:])
    ma_slow = _mean(closes[-20:])
    std20 = statistics.pstdev(closes[-20:]) if len(closes) >= 20 else 0.0
    bb_upper = ma_slow + 2 * std20
    bb_lower = ma_slow - 2 * std20

    volume_ratio: float | None = None
    if len(volumes) >= 21:
        base = [v for v in volumes[-21:-1] if v and v > 0]
        if base and volumes[-1]:
            volume_ratio = round(volumes[-1] / (sum(base) / len(base)), 2)

    above_vwap = vwap is not None and price > vwap
    if above_vwap and ma_fast > ma_slow:
        trend = "up"
    elif vwap is not None and price < vwap and ma_fast < ma_slow:
        trend = "down"
    else:
        trend = "flat"

    # 日内支撑：多头看 VWAP/快线，跌破则看日内低点
    support_candidates = [c for c in (vwap, ma_fast, bb_lower, day_low) if c and c <= price]
    support = max(support_candidates) if support_candidates else (day_low or price)
    # 日内压力：先看日内高点，再看布林上轨/VWAP
    resistance_candidates = [c for c in (day_high, bb_upper, vwap, ma_fast) if c and c > price]
    resistance = min(resistance_candidates) if resistance_candidates else (day_high or price)

    profile = _PERIOD_PROFILE.get(period, _DEFAULT_PROFILE)
    stop_loss = _intraday_stop(price, day_low, profile)

    strength = 5.0
    if above_vwap:
        strength += 1.5
    if ma_fast > ma_slow:
        strength += 1.5
    if price > ma_slow:
        strength += 1.0
    if volume_ratio is not None and volume_ratio >= 1.5:
        strength += 1.0
    if trend == "down":
        strength -= 2.0
    if day_low and price <= day_low * 1.002:
        strength -= 1.5
    strength = round(max(0.0, min(10.0, strength)), 1)

    return {
        "price": round(price, 2),
        "vwap": round(vwap, 2) if vwap else None,
        "day_open": round(day_open, 2) if day_open else None,
        "day_high": round(day_high, 2) if day_high else None,
        "day_low": round(day_low, 2) if day_low else None,
        "ma_fast": round(ma_fast, 2),
        "ma_slow": round(ma_slow, 2),
        "bb_upper": round(bb_upper, 2),
        "bb_lower": round(bb_lower, 2),
        "volume_ratio": volume_ratio,
        "trend": trend,
        "support": round(support, 2),
        "resistance": round(resistance, 2),
        "stop_loss": stop_loss,
        "strength": strength,
        "bars": len(closes),
        "session": session,
    }


def _intraday_stop(price: float, day_low: float | None, profile: dict) -> float:
    """日内止损：破日内低点就走，但最多容忍 profile 定义的一小段回撤。"""
    raw = day_low if (day_low and day_low < price) else price * profile["stop_hi"]
    stop = min(max(raw, price * profile["stop_lo"]), price * profile["stop_hi"])
    return round(stop, 2)


def _position_pct(sig: dict, profile: dict) -> int:
    """日内仓位：短线波动快，仓位远小于日线级别。"""
    lo, hi = profile["pos_lo"], profile["pos_hi"]
    pct = lo + (hi - lo) * ((sig.get("strength") or 5) / 10)
    vr = sig.get("volume_ratio")
    if vr is not None and vr >= 1.5:
        pct += 5
    return int(max(lo, min(hi, pct)))


def intraday_advice(price: float, sig: dict, period: str = "15m") -> dict:
    """分钟级买卖指令：与日线 `_advice` 结构一致，额外标注 scope=intraday。"""
    profile = _PERIOD_PROFILE.get(period, _DEFAULT_PROFILE)
    vwap = sig.get("vwap")
    day_high = sig.get("day_high")
    day_low = sig.get("day_low")
    ma_fast = sig["ma_fast"]
    ma_slow = sig["ma_slow"]
    bb_upper = sig["bb_upper"]
    volume_ratio = sig.get("volume_ratio")
    trend = sig.get("trend", "flat")
    support = sig["support"]
    resistance = sig["resistance"]
    stop = sig["stop_loss"]

    to_vwap = ((price - vwap) / vwap * 100) if vwap else None
    to_high = ((day_high - price) / price * 100) if day_high else None
    dist = {
        "to_stop": round((price - stop) / price * 100, 2),
        "to_support": round((price - support) / price * 100, 2),
        "to_resistance": round((resistance - price) / price * 100, 2),
        "to_vwap": round(to_vwap, 2) if to_vwap is not None else None,
    }

    def _pack(action: str, label: str, tone: str, hint: str) -> dict:
        buy = round(max(support, price * 0.995), 2)
        plan = {
            "buy": buy,
            "sell": round(resistance, 2),
            "stop": round(stop, 2),
            "target": round(resistance, 2),
            "position_pct": _position_pct(sig, profile) if action == "buy" else 0,
            "urgency": "high" if action in ("stop", "sell") else ("mid" if action == "buy" else "low"),
        }
        do = {
            "stop": f"现价止损，跌破 {plan['stop']:.2f} 走",
            "buy": f"挂 {plan['buy']:.2f} 买入 · {plan['position_pct']}% 仓",
            "sell": f"挂 {plan['sell']:.2f} 减仓/止盈",
        }.get(action, f"观望 · {plan['buy']:.2f} 低吸 / {plan['sell']:.2f} 减仓 / {plan['stop']:.2f} 止损")
        return {
            "action": action,
            "label": label,
            "tone": tone,
            "hint": hint,
            "do": do,
            "plan": plan,
            "dist": dist,
            "scope": "intraday",
            "period": period,
            "session_note": "日内决策仅当日有效，收盘前需了结或改按日线持有",
        }

    vr_text = f"量比 {volume_ratio:.2f}x" if volume_ratio is not None else "量能数据不足"

    # 1) 跌破日内低点：日内多头逻辑已被破坏（严格判断，不用百分比容差——
    #    高价股 0.1% 就是好几块钱，会把「逼近」误判成「跌破」）
    if day_low and price <= day_low:
        hint = f"现价 {price:.2f} 跌破日内低点 {day_low:.2f}（{vr_text}），日内转弱，反抽 {vwap:.2f} 无力先离场" if vwap else f"现价 {price:.2f} 跌破日内低点 {day_low:.2f}（{vr_text}）"
        return _pack("sell", "破日内低", "danger", hint)

    # 2) 放量突破日内高点
    if day_high and price >= day_high:
        if volume_ratio is not None and volume_ratio >= 1.5:
            return _pack("buy", "放量破日内高", "good", f"现价 {price:.2f} 放量突破日内高点 {day_high:.2f}（{vr_text}），可顺势跟进，跌回 {day_high:.2f} 下方即离场")
        return _pack("hold", "破日内高待确认", "neutral", f"现价 {price:.2f} 触及日内高点 {day_high:.2f} 但 {vr_text}，等站稳或放量再跟")

    # 3) 多头结构：站上 VWAP 且分钟均线多头
    if trend == "up":
        if price <= ma_fast * 1.003:
            return _pack("buy", "回踩分钟均线", "good", f"现价 {price:.2f} 回踩 {period} 快线 {ma_fast:.2f} 且守住 VWAP {vwap:.2f}，日内多头结构完好，可低吸，止损 {stop:.2f}")
        if price >= bb_upper:
            return _pack("sell", "冲高上轨减仓", "warn", f"现价 {price:.2f} 触及 {period} 布林上轨 {bb_upper:.2f}，短线超买，可分批止盈")
        return _pack("hold", "日内多头持有", "neutral", f"现价 {price:.2f} 站稳 VWAP {vwap:.2f} 上方 {to_vwap:.2f}%，分钟均线多头，回踩 {ma_fast:.2f} 不破继续持有" if to_vwap is not None else f"现价 {price:.2f} 分钟均线多头，持有观察")

    # 4) 空头结构：跌破 VWAP 且分钟均线空头
    if trend == "down":
        if vwap and price >= vwap * 0.997:
            return _pack("sell", "反抽 VWAP 走", "warn", f"现价 {price:.2f} 反抽 VWAP {vwap:.2f} 未站上，日内空头压制，有仓借反抽减，无仓别接")
        return _pack("sell", "日内空头压制", "danger", f"现价 {price:.2f} 位于 VWAP {vwap:.2f} 下方且分钟均线空头，日内不参与，有仓反抽减")

    # 5) 多空胶着
    gap = f"距日内高点 {to_high:.2f}%" if to_high is not None else ""
    return _pack("hold", "日内胶着观望", "neutral", f"现价 {price:.2f} 与 VWAP {vwap:.2f} 缠绕、分钟均线走平{gap}，等方向明确再动手")
