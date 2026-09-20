"""证据台账：一处看清「现在有多少 n、哪些结论能动手」。

项目里 K 线形态与结构化口径的可信度由 `tactic_evidence` 统一裁决，但要知道
「到底什么能用」得跨好几个页面拼信息。这里把它们聚合成一份只读读数：

· 每条口径的**证据等级 + 样本出处**（provenance）与最后一次跑批快照
· 各等级覆盖计数 —— 其中 `verified` 是唯一允许进入买卖点位置的档
· **观察期自积累进度**（涨停池累积表已攒够几个交易日）

⚠️ 这里是**只读聚合**，不产生任何新结论，数字全部来自各服务自己的登记表与跑批快照。
台账存在的意义正是杜绝「文档说 A、代码说 B」—— 本项目已出现过多次这类不一致。
"""
from __future__ import annotations

from app.services import limitup_service, tactic_evidence, trade_calendar_service

# 展示顺序：能动手的排最前，不能动手的按「离能动手有多远」排列
_TIER_ORDER = ("verified", "preliminary", "unsupported", "unknown", "not_testable")

_TIER_MEANING = {
    "verified": "统计显著且各持有期超额为正 —— 只有这一档允许进入买卖点位置",
    "preliminary": "样本不足，或关键环节（如可成交性）只是代理口径 —— 只作线索，不进动作",
    "unsupported": "已用当前实现回测且有明确结论（含结论为负）—— 不作为策略依据",
    "unknown": "尚未用当前实现回测过",
    "not_testable": "当前数据源无法回测",
}


async def build() -> dict:
    """组装台账。全部数据来自内存登记表 + 一次轻量累积表计数，无回测、无行情请求。"""
    pattern = tactic_evidence.survey()
    strategy = tactic_evidence.strategy_survey()
    accumulated = await limitup_service.accumulated_stats()

    items: list[dict] = []
    for namespace, table in (("pattern", tactic_evidence.EVIDENCE), ("strategy", tactic_evidence.STRATEGY_EVIDENCE)):
        for key, ev in table.items():
            items.append(
                {
                    "key": key,
                    "namespace": namespace,
                    "tier": ev.tier,
                    "label": ev.label,
                    "badge": ev.badge,
                    "actionable": ev.actionable,
                    "summary": ev.summary,
                    "provenance": ev.provenance,
                }
            )
    items.sort(key=lambda i: (_TIER_ORDER.index(i["tier"]) if i["tier"] in _TIER_ORDER else 9, i["key"]))

    counts: dict[str, int] = {}
    for item in items:
        counts[item["tier"]] = counts.get(item["tier"], 0) + 1
    actionable = [i["key"] for i in items if i["actionable"]]

    return {
        "generated_at": trade_calendar_service.now_cn().isoformat(timespec="seconds"),
        "counts": counts,
        "tier_meaning": _TIER_MEANING,
        "tier_order": list(_TIER_ORDER),
        "actionable_keys": actionable,
        "actionable_count": len(actionable),
        "items": items,
        "pattern_survey": pattern,
        "strategy_survey": strategy,
        "observation": {
            "limitup_accumulated": accumulated,
            "note": (
                "涨停池接口只回溯约 15 个交易日，样本窗口不会随时间自然变长；"
                "每日落库（v10）用于把窗口自积累。accumulated_days 长期为 0 是预期行为 —— "
                "它只补「接口返回空池」的日期，首次真正生效约在最早落库日滑出 15 天窗口之后。"
                "Agent 决策计划的观察样本见「持仓 → 模拟盘 → Agent 决策记录」。"
            ),
        },
        "headline": (
            f"当前 {len(items)} 条口径中，{len(actionable)} 条达到可执行档（verified）。"
            + (
                "其余全部只作观察/风险提示 —— 任何「已验证有效」的说法在本项目内都不成立。"
                if not actionable
                else ""
            )
        ),
    }
