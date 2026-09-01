"""技术信号服务：基于历史K线计算压力位/支撑位/买卖点/止损位/风险收益比。

采用确定性算法（可复现、可验证），供前端展示与 LLM 研判使用。
"""
from __future__ import annotations

import statistics


def compute_signals(closes: list[float], price: float) -> dict | None:
    """计算技术信号。

    返回:
      support: 主支撑位
      resistance: 主压力位
      buy_point: 建议买入区
      sell_point: 建议卖出区
      stop_loss: 止损位
      rr_ratio: 风险收益比（(sell-point)/ (price-stop)）
      strength: 信号强度 0-10
    """
    if not closes or len(closes) < 60:
        return None

    highs_window = closes[-60:]
    low = min(highs_window)
    high = max(highs_window)
    current = price

    # 布林带（20日）：中轨 MA20，上下轨 ±2σ
    ma20 = sum(closes[-20:]) / 20
    if len(closes) >= 20:
        std20 = statistics.pstdev(closes[-20:])
    else:
        std20 = 0
    bb_upper = ma20 + 2 * std20
    bb_lower = ma20 - 2 * std20

    # 斐波那契回撤（基于60日高低点）
    fib_range = high - low
    fib_382 = high - fib_range * 0.382
    fib_618 = high - fib_range * 0.618

    # 均线支撑
    ma5 = sum(closes[-5:]) / 5 if len(closes) >= 5 else ma20
    ma60 = sum(closes[-60:]) / 60

    # 主支撑：取最近的支撑候选（低于现价且尽可能接近）
    supports = [fib_618, bb_lower, ma20, ma60]
    valid_supports = [s for s in supports if s < current]
    support = max(valid_supports) if valid_supports else low

    # 主压力：取最近的压力候选（高于现价且尽可能接近）
    resistances = [fib_382, bb_upper, high]
    valid_resistances = [r for r in resistances if r > current]
    resistance = min(valid_resistances) if valid_resistances else high

    # 止损位：主支撑下方约 3%（或斐波那契 61.8% 下方）
    stop_loss = round(support * 0.97, 2)

    # 买入区：现价下方 1%（回踩买点），但不低于支撑位
    buy_point = round(max(current * 0.99, support), 2)

    # 卖出区：现价上方 1%（冲高卖点），但不高于压力位
    sell_point = round(min(current * 1.01, resistance), 2)

    # 风险收益比
    upside = sell_point - current
    downside = current - stop_loss
    rr_ratio = round(upside / downside, 2) if downside > 0 else 0.0

    # 信号强度：趋势 + 位置 + 距离
    strength = 5.0
    if current > ma20:
        strength += 1.5
    if ma5 > ma20:
        strength += 1.0
    if current > ma60:
        strength += 1.0
    if current > bb_lower:
        strength += 0.5
    # 接近支撑或压力时机会更好
    if support > 0 and 0 < (current - support) / current < 0.03:
        strength += 1.0
    if rr_ratio >= 2:
        strength += 1.0
    elif rr_ratio < 1:
        strength -= 1.0
    strength = round(max(0, min(10, strength)), 1)

    return {
        "price": round(current, 2),
        "support": round(support, 2),
        "resistance": round(resistance, 2),
        "buy_point": buy_point,
        "sell_point": sell_point,
        "stop_loss": stop_loss,
        "rr_ratio": rr_ratio,
        "strength": strength,
        "bb_upper": round(bb_upper, 2),
        "bb_lower": round(bb_lower, 2),
        "ma5": round(ma5, 2),
        "ma20": round(ma20, 2),
        "ma60": round(ma60, 2),
        "low60": round(low, 2),
        "high60": round(high, 2),
    }
