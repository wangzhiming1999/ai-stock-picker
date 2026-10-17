"""证据台账：一处看清「现在有多少 n、哪些结论能动手」。

项目里 K 线形态与结构化口径的可信度由 `tactic_evidence` 统一裁决，但要知道
「到底什么能用」得跨好几个页面拼信息。这里把它们聚合成一份只读读数：

· 每条口径的**证据等级 + 样本出处**（provenance）与最后一次跑批快照
· 各等级覆盖计数 —— 其中 `verified` 是唯一允许进入买卖点位置的档
· **观察期自积累进度**（涨停池累积表已攒够几个交易日）
· 每条口径的**四问守卫**（2026-10-17）—— 数字本身站不站得住

⚠️ 这里是**只读聚合**，不产生任何新结论，数字全部来自各服务自己的登记表与跑批快照。
台账存在的意义正是杜绝「文档说 A、代码说 B」—— 本项目已出现过多次这类不一致。

## 为什么样本量是显式声明而不是从文案里抽（试过，很难）

`Evidence` 是 frozen dataclass，文案里确实写着各种实测样本量，但**句式不统一、
且子集与整体混在一起**：
  · `limitup_relay` summary 里 n=601 是「首板→2板」子档，764 才是整体（在 provenance）
  · `limitdown_repair` 写「共 133 个样本」，没有 `n=` 前缀
  · `monitor_levels` n=1790 是「回踩可买」子集，整体是 10500 个 (股票,交易日) 对

这些数字**本身都没错**，错的是「拿子集当整体」—— 而那会让四问的 n 一问
答出一个看起来精确、实际对象错误的结论（与 legacy 分母那次同类）。
所以改为在 `_EVIDENCE_SAMPLE` 里**显式声明**，不猜。
"""
from __future__ import annotations

from app.services import calibers, limitup_service, tactic_evidence, trade_calendar_service

# 展示顺序：能动手的排最前，不能动手的按「离能动手有多远」排列
_TIER_ORDER = ("verified", "preliminary", "unsupported", "unknown", "not_testable")

_TIER_MEANING = {
    "verified": "统计显著且各持有期超额为正 —— 只有这一档允许进入买卖点位置",
    "preliminary": "样本不足，或关键环节（如可成交性）只是代理口径 —— 只作线索，不进动作",
    "unsupported": "已用当前实现回测且有明确结论（含结论为负）—— 不作为策略依据",
    "unknown": "尚未用当前实现回测过",
    "not_testable": "当前数据源无法回测",
}

# 台账条目 ↔ calibers 口径 key 的对应。台账与 calibers 是两套 key（台账用技巧名、
# calibers 用口径名），这张表是唯一的翻译处 —— **不允许在渲染时按名字猜**，
# 猜错等于把 A 口径的读数挂到 B 口径上。
#
# 每条同时**显式声明样本量**与它的出处。为什么不用正则从文案里抽（试过，很难）：
#   · `limitup_relay` 的 summary 里「首板→2板 n=601、2板→3板 n=99」是**子档位**的 n，
#     抽第一个会得到 601，而整体样本数（764）写在 provenance 的另一种句式里 ——
#     把子档位的样本量当整体，会让四问的 n 一问答出错误结论。
#   · `limitdown_repair` 写的是「共 133 个样本」，句式与 n= 完全不同。
#   · `monitor_levels` 的 n=1790 是「回踩可买」档的子集。
# 这些数字**本身没错**，错的是「拿子集当整体」。所以显式声明，不猜。
#
# ⚠️ 这里的 n 是**静态快照**（各条 evidence 文案写下的那次跑批），
# 不是实时查询 —— 四问的 detail 会注明来源与这个限制。
_EVIDENCE_SAMPLE: dict[str, tuple[str, int | None, str]] = {
    # key → (calibers 口径 key, 样本量, 样本量出处说明)
    "limitup_relay": ("limitup_relay", 764, "13 个交易日对的全部晋级观察（764 个样本，非分档小计）"),
    "limitup_premium": ("limitup_premium", 758, "涨停池口径 14 个交易日跑批；该口径另有日 K 口径 n=4953"),
    "seize_reseal": ("seize_reseal", 81, "已结算样本 81（取样 84，n=84 里 3 条无法结算）"),
    "limitdown_repair": ("limitdown_repair", 133, "13 个交易日全部跌停样本"),
}

# 未登记对应 calibers 口径的条目（纯形态技巧、买卖点结构位、四维打分榜等）。
# 它们的 n 语义各不相同（评估点数 / 打分次数 / 无收益口径），**不接四问** ——
# 硬套一个就是拿别的口径的判据来评价它。
_EVIDENCE_WITHOUT_CALIBER = {
    "strategy_scores": "策略分打分不是收益口径（unsupported），无 calibers 对应口径",
    "monitor_levels": "买卖点结构位是 unsupported 的结构读数，样本单位是 (股票,交易日) 对",
    "vanguard_three_dim": "三维打分榜非收益口径，证据已声明「不具备升级条件」",
}


async def build() -> dict:
    """组装台账。全部数据来自内存登记表 + 一次轻量累积表计数，无回测、无行情请求。"""
    pattern = tactic_evidence.survey()
    strategy = tactic_evidence.strategy_survey()
    accumulated = await limitup_service.accumulated_stats()

    items: list[dict] = []
    for namespace, table in (("pattern", tactic_evidence.EVIDENCE), ("strategy", tactic_evidence.STRATEGY_EVIDENCE)):
        for key, ev in table.items():
            caliber_key, sample_n, sample_note = _EVIDENCE_SAMPLE.get(key, (None, None, None))
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
                    "plan_horizon": ev.plan_horizon,
                    "win_rate": ev.win_rate,
                    "caliber_key": caliber_key,
                    # 四问：证据等级答「结论有效不有效」，四问答「数字站不站得住」。
                    # **并列展示、互不影响** —— 台账不改 tier、不改 actionable。
                    "four_questions": _ledger_four_questions(
                        caliber_key=caliber_key,
                        n=sample_n,
                        sample_note=sample_note,
                        tier=ev.tier,
                    ),
                    # 未接四问的原因也要下发 —— 否则「没有四问」会读成「四问过了」
                    "four_questions_absent_reason": (
                        None
                        if caliber_key
                        else _EVIDENCE_WITHOUT_CALIBER.get(key, "未登记对应 calibers 口径")
                    ),
                }
            )
    items.sort(key=lambda i: (_TIER_ORDER.index(i["tier"]) if i["tier"] in _TIER_ORDER else 9, i["key"]))

    counts: dict[str, int] = {}
    for item in items:
        counts[item["tier"]] = counts.get(item["tier"], 0) + 1
    actionable = [i["key"] for i in items if i["actionable"]]

    # 数字可信度分布：只统计能接上四问的条目（其余口径未登记，见上）
    verdict_counts: dict[str, int] = {}
    four_checked = 0
    for item in items:
        four = item["four_questions"]
        if not four or four.get("sample_source") != "evidence_declared":
            continue
        four_checked += 1
        verdict_counts[four["verdict"]] = verdict_counts.get(four["verdict"], 0) + 1

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
        "four_questions": {
            "checked": four_checked,
            "verdict_counts": verdict_counts,
            "note": (
                "四问与证据等级**并列、互不影响**：等级答「结论有效不有效」，"
                "四问答「这个数字本身站不站得住」。前者是证据链，后者是口径纪律，"
                "混在一起会让任何一次口径调整都能悄悄改变证据分级。"
                "台账的四问样本量取自各条证据文案里的实测 n（静态快照，"
                "非实时查询），因此 detail 里标注了来源与快照时间。"
                "未登记对应 calibers 口径的条目（如纯形态技巧）不接四问，如实标注。"
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


def _ledger_four_questions(
    *, caliber_key: str | None, n: int | None, sample_note: str | None, tier: str
) -> dict | None:
    """台账条目的四问 —— 无对应口径时返回 None（前端显示原因）。

    ## 四处与运行时四问不同，都是台账特有的约束

    1. **n 是显式声明的静态快照**（`_EVIDENCE_SAMPLE`），不是实时测量。
       n 一问要额外说明来源与「需以最新跑批为准」。
    2. **分布与可成交答不上来**：台账只有 tier 与文字描述，
       没有收益分布、也没有逐笔成交数据。**不去别处借** ——
       借来的数字挂在这个 key 上就是在造假。
    3. **第四问答不上来**：台账层没做基准对照。
       `limitup_premium` 之类口径本身自带双基准对照（在它自己的回测里），
       但台账这层不重复计算、也不假装算得出。
    4. **tier 不参与判定**：`unsupported` 的条目照样出四问 ——
       它的结论已经是「否」，四问答的是「这个数字本身站不站得住」，
       两件事并行。
    """
    if caliber_key is None or caliber_key not in calibers.all_keys():
        return None

    four = calibers.four_questions_with_notes(
        {
            "sample": (
                f"样本量 n={n}（{sample_note}）取自本条证据快照，"
                "**非实时查询**，需以最新跑批为准"
                if n is not None
                else "本条未登记样本量 —— 可能尚未回测（tier=" + tier + "）"
            ),
            "median": "台账层只有 tier 与文字描述，没有收益分布可算中位数"
            "（分布读数见该口径自己的面板，如涨停带 / 研究页回测）",
            "tradable": "台账层无逐笔成交数据；可成交性是该口径证据等级的判定依据之一"
            "（见 tier_meaning），具体比例见各口径自己的回测面板",
            "benchmark_sign": "台账层未做基准对照 —— 该对照由各口径自己的回测负责"
            "（如 limitup_premium 用沪深300 + 中证1000 双基准）",
        },
        n=n if n is not None else 0,
        median=None,
        mean=None,
        tradable_ratio=None,
        benchmark_sign_flips=None,
    )
    # 标记来源与样本出处，前端据此区分「有实测 n」与「未登记 n」
    four["sample_source"] = "evidence_declared" if n is not None else "not_declared"
    four["sample_note"] = sample_note
    four["caliber_key"] = caliber_key
    return four
