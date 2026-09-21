"""技术信号服务：基于历史K线计算压力位/支撑位/买卖点/止损位/风险收益比。

采用确定性算法（可复现、可验证），供前端展示与 LLM 研判使用。
"""
from __future__ import annotations

import statistics


def compute_signals(
    closes: list[float],
    price: float,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
) -> dict | None:
    """计算技术信号。

    参数:
      closes: 收盘价序列（最后一根若是当日进行中的 K 线，其值等于现价）
      price: 现价（观测值，只参与判断，不参与定档）
      highs / lows: 可选的真实最高/最低价序列，与 closes 等长。日线接口若只有收盘价，
        退化为用收盘价近似 —— 这会把 60 日区间算窄，压力位系统性偏低（实测中位偏低 6.4%）。

    返回:
      support: 主支撑位
      resistance: 主压力位
      buy_point: 建议买入区（= 主支撑位，结构位，不随现价漂移）
      sell_point: 建议卖出区（= 主压力位，结构位，不随现价漂移）
      stop_loss: 止损位
      rr_ratio: 风险收益比（(resistance-price)/(price-stop_loss)）
      strength: 信号强度 0-10

    ⚠️ 定档必须用「已经走完的那根」，不能含当日。盘中日 K 最后一根的收盘价**就是现价**
    （实测差异 0.000%），拿它当参考会让 support 恒 ≤ 现价、resistance 恒 ≥ 现价、
    stop_loss 恒 < 现价 —— 于是「跌破支撑 / 突破压力 / 止损离场」三档在定义上
    永远不可能成立（实测 10500 个样本触发 0 次）。
    """
    if not closes or len(closes) < 60:
        return None

    # 定档基准：去掉最后一根（进行中的那根），让现价能落在支撑/压力之外。
    if len(closes) >= 61:
        basis = closes[:-1]
        basis_highs = highs[:-1] if highs and len(highs) == len(closes) else highs
        basis_lows = lows[:-1] if lows and len(lows) == len(closes) else lows
    else:
        basis = closes
        basis_highs, basis_lows = highs, lows

    highs_window = basis_highs[-60:] if basis_highs else basis[-60:]
    lows_window = basis_lows[-60:] if basis_lows else basis[-60:]
    low = min(lows_window)
    high = max(highs_window)
    current = price

    # 布林带（20日）：中轨 MA20，上下轨 ±2σ
    ma20 = sum(basis[-20:]) / 20
    std20 = statistics.pstdev(basis[-20:]) if len(basis) >= 20 else 0
    bb_upper = ma20 + 2 * std20
    bb_lower = ma20 - 2 * std20

    # 斐波那契回撤（基于60日高低点）
    fib_range = high - low
    fib_382 = high - fib_range * 0.382
    fib_618 = high - fib_range * 0.618

    # 均线支撑
    ma5 = sum(basis[-5:]) / 5 if len(basis) >= 5 else ma20
    ma60 = sum(basis[-60:]) / 60

    # 参考价 = 最后一根已完成 K 线的收盘。定档只认它，现价不参与，
    # 否则现价一抖，支撑/压力候选就被换掉，建议会往回跳。
    reference = basis[-1]

    # 主支撑：取最近的支撑候选（低于现价且尽可能接近）
    supports = [fib_618, bb_lower, ma20, ma60]
    valid_supports = [s for s in supports if s <= reference]
    support = max(valid_supports) if valid_supports else low

    # 主压力：取最近的压力候选（高于现价且尽可能接近）
    resistances = [fib_382, bb_upper, high]
    valid_resistances = [r for r in resistances if r > reference]
    resistance = min(valid_resistances) if valid_resistances else high

    # 止损位：主支撑下方约 3%（或斐波那契 61.8% 下方）
    stop_loss = round(support * 0.97, 2)

    # 买入区 = 主支撑位，卖出区 = 主压力位：直接锚定结构位，不随现价漂移。
    # 旧实现是「现价 ∓1%」（max(现价×0.99, 支撑) / min(现价×1.01, 压力)），
    # 实测 70.1% 的样本 buy_point 就等于 round(现价×0.99)、82.7% 等于 round(现价×1.01)，
    # 挂单价每天跟着现价平移（相邻交易日位移中位 0.94%）。既没有结构含义，
    # 也是用户反馈「买卖点老是变化」的直接来源。
    buy_point = round(support, 2)
    sell_point = round(resistance, 2)

    # 风险收益比按主压力位计算；sell_point 只是 1% 的分批观察价，不能作为完整收益空间，
    # 否则绝大多数正常形态都会被错误判为低风险收益比。
    upside = resistance - current
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


# ---------- 预期价格（执行锚点） ----------
#
# 用户反馈：「决策类文案太少了，我都不知道怎么操作」「选股的时候记得带一个预期价格」。
# 预期价格回答的只有一件事：**这笔动作打算在什么价位成交**。
#
# 取值来源是**已经存在的结构位**（主支撑 / 主压力），不是预测价、不是目标价：
#   breakout → 取主压力位。放量突破该价才成立，所以预期成交价就是突破位（挂低了不成交）；
#   pullback → 取主支撑位。回到该价附近才成立，所以预期成交价就是回踩位（挂高了就贵了）；
#   auto     → 由**现价与主压力的距离**自动二选一（见 `_SETUP_NEAR_RESISTANCE`）。
#              「选股榜」这类没有现成形态判定的地方用它，规则仍然是确定的、可复算的。
#
# ⚠️ 三条不能破的约束：
#   1. **不参与任何收益率结算**。预期价格只是执行锚点，胜率 / 溢价 / agent 计划口径
#      一律不用它 —— 否则会凭空造出一个没人回测过的收益口径。
#   2. 结构位本身的证据档是 unsupported（见 `tactic_evidence.monitor_levels`：买入侧
#      实测超额为负）。这里只是把同一个价位搬到「执行锚点」的位置展示，
#      **不得**因此把 buy_point 说成买点。
#   3. 拿不到结构位就返回 None，由前端显示「—」。**永不折算成 0 或现价** ——
#      折算出来的假价格会被当成真锚点用。

# `auto` 的判定边界：现价 ≥ 主压力 ×0.98 视为「贴着压力」，锚点取突破位；否则取回踩位。
# 取 0.98 而不是 1.00：结构位与现价之间常常差几分钱，用 1.00 会让同一只票在两次取数间
# 在「回踩」和「突破」之间跳档，挂单价跟着跳 —— 档位必须稳定、可复现。
_SETUP_NEAR_RESISTANCE = 0.98


def expected_price_from_levels(
    price: float | None,
    levels: dict | None,
    setup: str = "pullback",
) -> dict | None:
    """结构位 → 预期价格。取不到返回 None（调用方显示「—」，不要兜底成 0）。

    返回的 ``gap_pct`` = 预期价格相对**现价**的偏离：正数表示现价还低于锚点（要等它涨上来），
    负数表示现价已高于锚点（要等它跌回来）。它只是「离锚点多远」的读数，不是预期收益。
    """
    if not levels:
        return None
    try:
        price = float(price or 0)
    except (TypeError, ValueError):
        price = 0.0

    auto = setup == "auto"
    if auto:
        try:
            resistance = float(levels.get("resistance") or 0)
        except (TypeError, ValueError):
            resistance = 0.0
        setup = "breakout" if (price > 0 and resistance > 0 and price >= resistance * _SETUP_NEAR_RESISTANCE) else "pullback"

    key = "resistance" if setup == "breakout" else "buy_point"
    try:
        anchor = float(levels.get(key) or 0)
    except (TypeError, ValueError):
        anchor = 0.0
    if anchor <= 0:
        return None

    if setup == "breakout":
        note = f"放量突破 {anchor:.2f} 后才成立，预期成交价取突破位（挂低了不会成交）"
        basis = "structure_breakout"
    else:
        note = f"回到 {anchor:.2f} 附近才成立，预期成交价取回踩位（挂高了就买贵了）"
        basis = "structure_pullback"
    if auto:
        # 自动选档时必须把「凭什么选了这一档」写出来，否则用户看到的是个黑箱结论。
        note += "；现价已贴近主压力，按突破位给价" if setup == "breakout" else "；现价离主压力尚远，按回踩位给价"

    return {
        "price": round(anchor, 2),
        "setup": setup,
        "basis": basis,
        "gap_pct": round((anchor - price) / price * 100, 2) if price > 0 else None,
        "note": note,
    }
