"""持仓决策层：每只持仓给出「持有 / 减仓 / 卖出 / 不参与」+ 结构位触发价（B）。

## 它解决什么

``portfolio_service.get_portfolio_advice`` 已经有一套持仓建议，但停留在
「提示清单」而不是「决策」：

1. **只有两个动作**（``hold`` / ``reduce``），从不输出 ``sell`` / ``skip`` ——
   于是「已跌破止损」和「结构完好」在界面上可能长成同一句话；
2. **没有 trigger / invalidation** —— 只有若干 tips 文字，用户读完还是不知道
   「到什么价该动手」「什么信号出现说明不用动了」；
3. **止盈条件是现价系数派生**（``pnl_pct > 20`` = 成本价 ×1.2）而不是结构位。
   本项目铁律：买卖点必须是结构位，禁「现价×系数」—— 系数法在 70~83% 的样本上
   退化成现价∓1%（实测，见 ``signal_service`` 模块说明）；
4. **不接板块资金** —— 持股所在板块正在被主力撤离这件事，此前完全不进决策。

本模块在既有 advice 之上加一层：把动作补全为 decision 6 态中的 4 态，
止盈/止损全部改锚**结构位**（``support`` / ``resistance`` / ``stop_loss``），
并接入板块四态（``sector_flow_service``）提高减仓优先级。

## 判据（按优先级从高到低，命中即停）

| 动作 | 触发条件 | 说明 |
|---|---|---|
| ``sell`` | 现价 ≤ ``stop_loss`` | 止损位已破，结构破坏 —— 不需要再等其它信号 |
| ``reduce`` | 现价 ≤ ``support``，或浮盈且已从 ``resistance`` 回落超 ``_PULLBACK_PCT``，或板块 ``follow_exit`` 且浮盈 > 0，或仓位占比超上限 | 四种独立原因，命中任一即降档 |
| ``hold`` | 现价 > ``stop_loss`` 且 > ``support`` | 结构完好 |
| ``skip`` | ``signal`` 为 None（K 线样本不足） | 不猜，明说不参与 |

⚠️ ``sell`` 刻意**不看浮盈**：止损是结构位判据，与成本无关。用「亏了多少」
来决定卖不卖，本质上是让沉没成本参与决策。

## 口径与红线

* 结构位一律取 ``signal_service.compute_signals`` 的输出（已按「定档用走完的那根」
  处理，见其模块说明），本模块**不重新取数** —— 直接消费
  ``portfolio_service`` 已 enrich 好的 ``signal`` / ``tactics``，避免 N+1 请求。
* 形态升级沿用既有闸门：只有 ``confidence == significant`` 的卖出形态才有资格
  把 ``hold`` 升成 ``reduce``（``pattern_service.ESCALATE_SELL_KEYS``）。
* 本模块产出的是**风险处置决策**（要不要离场/降敞口），不是收益预测，
  因此不进 ``evidence_score``、不参与胜率结算。
* 动作词一律走 ``decision.make()``，**不得**在调用点另写中文。
"""
from __future__ import annotations

from app.services import decision, pattern_service

# 浮盈后从压力位回落的幅度阈值。锚在 resistance（结构位）而不是成本价倍数：
# 「涨过压力位又跌回来多少」是可观测的结构事件，「赚了 20%」不是。
_PULLBACK_PCT = 0.05

# 板块处于撤离状态时，浮盈超过这个幅度才触发减仓（避免一天正常波动就赶人）
_EXIT_SECTOR_MIN_PNL = 5.0

# 单只持仓占总资金的上限（与 portfolio_service 的「稳健」档一致，不另起一套）
_MAX_POSITION_PCT = 20.0


def _decide_one(
    item: dict,
    sector_state: str | None = None,
) -> dict:
    """单只持仓 → 结构化决策。

    ``item`` 是 ``portfolio_service.get_portfolio_advice`` 的 ``holdings_advice``
    元素（已含 signal / tactics / pnl_pct / position_pct）。
    ``sector_state`` 是该股所属板块的四态（``follow_*``），未知时传 None。
    """
    price = item.get("price")
    signal = item.get("signal") or {}
    support = signal.get("support")
    resistance = signal.get("resistance")
    stop_loss = signal.get("stop_loss")
    pnl_pct = item.get("pnl_pct")
    pos_pct = item.get("position_pct") or 0.0
    tactics = item.get("tactics") or []

    # ① 样本不足：明说不参与，不用「持有不动」冒充
    if not signal or price is None:
        return decision.make(
            "skip",
            reason="K 线样本不足或行情缺失，算不出结构位，本次不对这只持仓下结论。",
            trigger=f"补齐 {item.get('code')} 的日线数据后再看。",
            invalidation=None,
        )

    reasons: list[str] = []
    reduce_causes: list[str] = []

    # ② 跌破止损位 = 结构破坏 → 直接卖出（不看浮盈，见模块说明）
    if stop_loss is not None and price <= stop_loss:
        return decision.make(
            "sell",
            reason=f"现价 {price:.2f} 已跌破止损位 {stop_loss:.2f}，结构破坏。",
            trigger=f"现价 ≤ {stop_loss:.2f}（已触发）",
            invalidation=f"重新站回止损位 {stop_loss:.2f} 之上并企稳，本条作废。",
        )

    # ③ 跌破主支撑
    if support is not None and price <= support:
        reduce_causes.append(f"现价 {price:.2f} 已跌破主支撑 {support:.2f}")
    elif support is not None:
        gap = (price - support) / price * 100 if price else None
        if gap is not None and gap < 5:
            reasons.append(f"距主支撑 {support:.2f} 仅 {gap:.1f}%，是下一个观察点")

    # ④ 浮盈后从压力位回落（结构位锚定，不是成本价倍数）
    if (
        resistance is not None
        and pnl_pct is not None
        and pnl_pct > 0
        and price < resistance * (1 - _PULLBACK_PCT)
    ):
        reduce_causes.append(
            f"有浮盈 {pnl_pct:.1f}% 但已从压力位 {resistance:.2f} 回落超 {_PULLBACK_PCT * 100:.0f}%，上方承压"
        )

    # ⑤ 板块资金撤离 + 有浮盈 → 提高减仓优先级
    if sector_state == "follow_exit" and pnl_pct is not None and pnl_pct >= _EXIT_SECTOR_MIN_PNL:
        reduce_causes.append(
            f"所属板块资金处于撤离状态且浮盈 {pnl_pct:.1f}%，主力退潮时优先落袋"
        )

    # ⑥ 单只仓位超上限（组合层铁律）
    if pos_pct > _MAX_POSITION_PCT:
        reduce_causes.append(
            f"单只占总资金 {pos_pct:.1f}% 超过上限 {_MAX_POSITION_PCT:.0f}%，减到限额内"
        )

    # ⑦ 显著级卖出形态（沿用既有闸门，未验证形态不驱动仓位动作）
    escalated = False
    for t in tactics:
        if t.get("direction") != "sell":
            continue
        if t.get("key") in pattern_service.ESCALATE_SELL_KEYS:
            escalated = True
            reduce_causes.append(f"显著级卖出形态：{t.get('name')} —— {t.get('action')}")
        else:
            reasons.append(f"形态风险（未达升级门槛，只提示）：{t.get('name')}")

    if reduce_causes:
        # 降档目标用结构位：回到主支撑附近或止损位上方，不是「现价×0.9」。
        # trigger 要反映**真正的触发条件**（是哪一条命中的），
        # 不能所有原因都写成「现价 ≤ 支撑」—— 那会让用户按错的价挂单。
        anchor = support if support is not None else stop_loss
        trigger = "；".join(
            f"{c}（已触发，按结构位减仓）" if not c.startswith("现价") else f"{c}，按结构位减仓"
            for c in reduce_causes
        )
        if anchor is not None:
            trigger += f"；减仓锚点 {anchor:.2f}"
        return decision.make(
            "reduce",
            reason="；".join(reduce_causes),
            trigger=trigger,
            invalidation=(
                f"重新站回主支撑 {support:.2f} 之上且板块资金不再撤离，本条作废。"
                if support is not None
                else "结构重新走好后本条作废。"
            ),
        )

    # ⑧ 结构完好 → 持有
    all_reasons = reasons or ["结构完好：现价在止损位与主支撑之上，无显著卖出信号。"]
    hold_trigger = f"现价 ≤ {support:.2f} 或 ≤ {stop_loss:.2f} 时转为减仓/卖出" if (support is not None and stop_loss is not None) else None
    hold_invalidation = None
    if resistance is not None:
        hold_invalidation = f"放量突破压力位 {resistance:.2f} 可考虑加仓，本条让位给加仓判断。"

    return decision.make(
        "hold",
        reason="；".join(all_reasons),
        trigger=hold_trigger,
        invalidation=hold_invalidation,
        # 供前端展开显示：这条结论用到的结构位
    )


def build_holding_decisions(
    advice_items: list[dict],
    sector_follow: dict | None = None,
) -> list[dict]:
    """批量持仓 → 结构化决策列表（顺序与入参一致）。

    ``sector_follow`` 用于把板块四态接进决策；不可用时全部按 None 处理
    （即板块这一维不参与，其余判据照常工作）。
    """
    # 板块名 → 四态。只用当日名单，不取分位（分位换日换基准，不可跨日比较）。
    state_by_sector: dict[str, str] = {}
    if sector_follow and sector_follow.get("available"):
        for s in sector_follow.get("sectors") or []:
            state_by_sector[str(s.get("name") or "")] = s.get("state")

    out: list[dict] = []
    for item in advice_items:
        sector_name = item.get("sector") or item.get("industry")
        sector_state = state_by_sector.get(str(sector_name)) if sector_name else None
        d = _decide_one(item, sector_state)
        out.append(
            {
                "code": item.get("code"),
                "name": item.get("name"),
                "price": item.get("price"),
                "pnl_pct": item.get("pnl_pct"),
                "position_pct": item.get("position_pct"),
                # 结构位原值：决策的锚点，前端展开时要能看到是哪个数
                "support": (item.get("signal") or {}).get("support"),
                "resistance": (item.get("signal") or {}).get("resistance"),
                "stop_loss": (item.get("signal") or {}).get("stop_loss"),
                "sector": sector_name,
                "sector_state": sector_state,
                "decision": d,
            }
        )
    # 排序：风险处置先于开仓（decision.DECISION_ORDER），让「该先动谁」有答案
    out.sort(key=lambda r: decision.DECISION_ORDER.get(r["decision"]["action"], 99))
    return out


def summarize(decisions: list[dict]) -> dict:
    """组合层汇总：几只要卖 / 几只要减 / 几只持有 / 几只看不准。

    刻意**不做加权打分**：各票的结构位、浮盈、板块状态不可比，
    相加会得到一个没有意义的「组合健康分」（见 MEMORY-FEATURES 第 7.5 节）。
    """
    counts: dict[str, int] = {}
    for d in decisions:
        key = d["decision"]["action"]
        counts[key] = counts.get(key, 0) + 1
    parts = []
    for action in ("sell", "reduce", "hold", "skip"):
        n = counts.get(action, 0)
        if n:
            parts.append(f"{decision.DECISION_LABEL[action]} {n} 只")
    return {
        "counts": counts,
        "summary": "；".join(parts) if parts else "暂无持仓",
        # 免责句保留（decision.py 纪律：不属于模棱两可）
        "disclaimer": "持仓决策是风险处置框架，锚定结构位；不是收益预测，不构成买卖指令。",
    }
