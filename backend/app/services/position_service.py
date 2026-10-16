"""仓位决策：把「今天该上几成仓」从一句自由文案变成结构化结论（A）。

## 它解决什么

此前仓位建议散在三处，且都不成决策：

1. ``market_prediction`` 让 LLM 输出 ``trading_advice`` 自由文案（「总仓位≤5成，
   跌破 X 减到 3 成」）—— 前端只能**用正则从文案里抠数字**
   （``DailyBriefing`` 的 ``position_suggestion.match(/(\\d+...)成/)``）。
   LLM 换一种说法（「半仓」「五成」「控制在 50% 以内」）前端就抠不到，
    silently 退化成展示原文。
2. ``briefing_service._direction_to_position`` 是一张确定性映射表，但只吃方向分
   一个输入，且没有触发/失效条件，也不走 ``decision.make()`` —— 它是个数字，
   不是一条决策。
3. 规则模式下 LLM 那栏是套话（「配置 LLM 后可获得更详细研判」）。

本模块把三者合成**一条结构化决策**：仓位上限（数字）+ 动作（decision 6 态）
+ 理由 + 加仓触发 + 降仓失效 + 可参与/回避板块。前端不再解析文案。

## 口径与红线

* **修正只用「降档」，不做多信号相加。** 方向分、情绪温度、板块资金三者高度相关
  （都是同一轮行情的不同切面），相加等于把同一个信号放大 N 倍 —— 这是
  ``MEMORY-FEATURES`` 第 7.5 节点名的问题。所以情绪与板块只用来**下调**上限，
  不上调：宁可比方向分暗示的更保守，也不能把保守结论叠加成激进。
* **板块清单只取名字，不取分位。** 板块四态（``sector_flow_service``）的判据是
  **当日横截面分位**，换日即换基准、不可跨日比较；但「哪些板块在加速流入」
  这个**名单**在当日内部是可用的。取名单不取分数，正是为了不把不可比的量搬过来。
* 仓位上限是**风险控制框架**，不是收益预测 —— 它不回答「上 5 成能赚多少」，
  只回答「这个环境下最多该承担多少敞口」。因此不进 ``evidence_score``、
  不参与胜率结算。
* 动作词一律走 ``decision.make()``，**不得**在调用点另写中文。
"""
from __future__ import annotations

from app.services import decision, sector_flow_service

# 方向分 → 基础仓位成数。沿用 briefing_service._direction_to_position 的既有分档，
# 不在本模块另起一套（同一件事两个口径必然打架）。
_BASE_CAP: tuple[tuple[float, int], ...] = (
    (7.0, 7),
    (6.0, 6),
    (5.5, 5),
    (5.0, 4),
    (4.0, 3),
    (3.0, 2),
)
_MIN_CAP = 1
_MAX_CAP = 7

# 情绪温度的降档阈值。炸板率是「封板有多不结实」的风险读数，不属于方向，
# 所以只用来降档、不上调。
_BREAK_RATE_WARN = 20.0     # 炸板率 ≥20%：接力分歧明显
_BREAK_RATE_SEVERE = 35.0   # ≥35%：分歧加剧
# 涨停家数极少说明没有做多温度，同样只降档
_LOW_LIMITUP = 20

# 板块四态里可以点名「可参与」/「回避」的上限数量
_SECTOR_LONG_MAX = 3
_SECTOR_AVOID_MAX = 3


def _base_cap(direction_score: float | None) -> int:
    """方向分 → 基础仓位成数。None（证据缺失）按中性 4 成起算，不按 0。"""
    if direction_score is None:
        return 4
    for threshold, cap in _BASE_CAP:
        if direction_score >= threshold:
            return cap
    return _MIN_CAP


def _sentiment_penalty(sentiment: dict | None) -> tuple[int, str | None]:
    """情绪温度 → 降档成数（非负）。

    返回 ``(降几成, 原因)``。没有可用情绪数据时降 0 成，**不猜**。
    """
    if not sentiment:
        return 0, None
    break_rate = _f(sentiment.get("break_rate"))
    limit_up = _i(sentiment.get("limit_up_count"))

    if break_rate is not None and break_rate >= _BREAK_RATE_SEVERE:
        return 2, f"炸板率 {break_rate:.0f}%（分歧加剧，接力易断）"
    if break_rate is not None and break_rate >= _BREAK_RATE_WARN:
        return 1, f"炸板率 {break_rate:.0f}%（封板质量偏弱）"
    if limit_up is not None and limit_up < _LOW_LIMITUP:
        return 1, f"涨停仅 {limit_up} 家，做多温度不足"
    return 0, None


def _sector_lists(sector_follow: dict | None) -> tuple[list[str], list[str], str | None]:
    """板块四态 → (可参与名单, 回避名单, 说明)。

    只取**名字**：四态判据是当日横截面分位，不可跨日比较；名单在当日内部可用。
    不可用时返回空名单 + 说明，前端据此显示「—」而不是编造。
    """
    if not sector_follow or not sector_follow.get("available"):
        return [], [], "板块资金流不可用，本次不给板块方向"
    sectors = sector_follow.get("sectors") or []
    long_names = [s["name"] for s in sectors if s.get("state") == "follow_accel"]
    avoid_names = [s["name"] for s in sectors if s.get("state") == "follow_exit"]
    note = None
    if not long_names:
        note = "当日无板块处于加速流入，不点名可参与方向"
    return (
        long_names[:_SECTOR_LONG_MAX],
        avoid_names[:_SECTOR_AVOID_MAX],
        note,
    )


def build_position_plan(
    direction_score: float | None,
    direction: str | None = None,
    sentiment: dict | None = None,
    sector_follow: dict | None = None,
) -> dict:
    """合成结构化仓位决策。

    返回 ``position_plan``：仓位上限（成 + 百分比）+ decision 四要素 + 板块名单
    + 判据（``basis``，供前端/排查复核这个仓位是怎么来的）。

    ⚠️ 修正只降档不上调，理由见模块说明。
    """
    base = _base_cap(direction_score)
    penalty, penalty_reason = _sentiment_penalty(sentiment)
    cap = max(_MIN_CAP, min(_MAX_CAP, base - penalty))

    long_names, avoid_names, sector_note = _sector_lists(sector_follow)

    # 动作：按上限相对「中性 4 成」的位置选，不按方向文案选 ——
    # 方向标签可能因惯性滞后，上限才是真正要执行的那个量。
    if cap >= 6:
        action = "add"
    elif cap <= 2:
        action = "reduce"
    else:
        action = "hold"

    reasons = [f"方向分 {direction_score if direction_score is not None else '—'}（{direction or '未知'}）→ 基础 {base} 成"]
    if penalty:
        reasons.append(f"情绪修正 −{penalty} 成（{penalty_reason}）")
    if long_names:
        reasons.append(f"板块资金：{'、'.join(long_names)} 处于加速流入")
    if sector_note:
        reasons.append(sector_note)

    # 加仓触发：必须落到可观测条件，不能是「感觉强了就加」。
    # 已在最高档时不再说「加至 N 成」（那会变成自指），改成维持条件。
    next_cap = min(cap + 1, _MAX_CAP)
    if cap >= _MAX_CAP:
        trigger = f"维持 {cap} 成上限：方向分跌回 6.0 以下即降到 {max(_MIN_CAP, cap - 1)} 成"
    elif long_names:
        trigger = f"放量站上压力位且 {'、'.join(long_names)} 仍为加速流入，可加至 {next_cap} 成"
    else:
        trigger = f"方向分回到 6.0 以上且炸板率降到 {_BREAK_RATE_WARN:.0f}% 以下，可加至 {next_cap} 成"

    # 降仓失效：这是本条决策的止损线，缺了它就只是「一句建议」。
    # 已经在最低档时不能再降 —— 此时改说「跌破支撑即清仓离场」，
    # 否则会出现「降到 1 成」而当前就是 1 成的自相矛盾。
    floor_cap = max(_MIN_CAP, cap - 2)
    if cap <= _MIN_CAP:
        invalidation = "已在最低仓位档，跌破主支撑即清仓离场，不再有中间档可降"
    else:
        invalidation = f"跌破主支撑或炸板率升到 {_BREAK_RATE_SEVERE:.0f}% 以上，降到 {floor_cap} 成"

    plan = decision.make(
        action,
        reason="；".join(reasons),
        trigger=trigger,
        invalidation=invalidation,
    )
    plan.update(
        {
            "position_cap": cap,
            "position_cap_pct": cap * 10,
            "position_cap_label": f"总仓位最多 {cap} 成（{cap * 10}%）",
            "sectors_long": long_names,
            "sectors_avoid": avoid_names,
            "basis": {
                "direction_score": direction_score,
                "direction": direction,
                "base_cap": base,
                "sentiment_penalty": penalty,
                "sentiment_reason": penalty_reason,
                "sector_note": sector_note,
                "sector_source": sector_flow_service.CAVEATS[0] if sector_follow else None,
            },
            # 免责句不属于模棱两可，按 decision.py 纪律保留
            "disclaimer": "仓位上限是风险控制框架，不是收益预测；未定义收益口径，不构成买卖指令。",
        }
    )
    return plan


def _f(value) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _i(value) -> int | None:
    if value in (None, "", "-"):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
