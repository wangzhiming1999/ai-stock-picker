"""证据台账接四问的测试。

## 这个模块在解决什么

台账是 19 条口径的总览页 —— 唯一能一眼看出「哪些口径其实站不住」的地方。
但它此前只有 `tier`（证据等级），没有「这个数字本身站不站得住」这一层。

## 两条不可违反的纪律

1. **四问与 tier 并列，互不影响。**
   tier 答「结论有效不有效」（证据链），四问答「数字站不站得住」（口径纪律）。
   混在一起会让任何一次口径调整都能悄悄改变证据分级 ——
   所以台账**不改** `tier` / `badge` / `actionable` / `counts`（有测试逐项锁死）。

2. **样本量必须显式声明，不能从文案里抽。**
   我试过正则抽取，结果是错的（详见 `_EVIDENCE_SAMPLE` 的注释）：
   `limitup_relay` 的 summary 里 n=601 是「首板→2板」子档，
   764 才是整体 —— 把子集当整体会让 n 一问答出「看起来精确、对象错误」的结论。
"""
from __future__ import annotations

import pytest

from app.services import calibers
from app.services import evidence_ledger as el


class TestExplicitSampleDeclaration:
    """样本量显式声明，且必须与 caliber key 绑定在同一条记录里。"""

    def test_every_declared_caliber_key_exists(self) -> None:
        """声明的 calibers key 必须真实存在 —— 写错会静默变成「未登记口径」。"""
        for evidence_key, (caliber_key, _n, _note) in el._EVIDENCE_SAMPLE.items():
            assert caliber_key in calibers.all_keys(), f"{evidence_key} → {caliber_key} 不存在"

    def test_declared_notes_are_present(self) -> None:
        """每条都要写清 n 是「整体」还是「子档」—— 这是声明存在的意义。"""
        for key, (_ck, n, note) in el._EVIDENCE_SAMPLE.items():
            assert n is not None and n > 0, key
            assert note and note.strip(), f"{key} 缺样本量出处说明"

    def test_relay_uses_overall_not_bucket(self) -> None:
        """回归：limitup_relay 的 n 必须是整体 764，不是子档 601。

        601 是「首板→2板」那一档 —— 用它会让 n 一问看似有答案、实则对象错误。
        """
        _ck, n, note = el._EVIDENCE_SAMPLE["limitup_relay"]

        assert n == 764
        assert "非分档小计" in note

    def test_premium_notes_the_second_caliber(self) -> None:
        """limitup_premium 有两个口径（涨停池 758 / 日 K 4953），必须说明取的是哪个。"""
        _ck, n, note = el._EVIDENCE_SAMPLE["limitup_premium"]

        assert n == 758
        assert "4953" in note

    def test_reseal_distinguishes_sampled_from_settled(self) -> None:
        """seize_reseal 取样 84、结算 81 —— 必须用结算数并说明差额。"""
        _ck, n, note = el._EVIDENCE_SAMPLE["seize_reseal"]

        assert n == 81
        assert "84" in note


class TestFourQuestionsWiring:
    def test_entries_without_caliber_get_none_and_a_reason(self) -> None:
        """未登记口径的条目：four_questions=None **且必须给出原因**。

        只给 None 不给原因，前端会把它读成「四问过了」——
        「没有四问」和「四问通过」是两件事。
        """
        absent = el._EVIDENCE_WITHOUT_CALIBER

        assert "strategy_scores" in absent
        assert "monitor_levels" in absent
        for key, reason in absent.items():
            assert reason and reason.strip(), key

    def test_ledger_four_questions_returns_none_without_caliber(self) -> None:
        assert el._ledger_four_questions(caliber_key=None, n=10, sample_note="x", tier="preliminary") is None

    def test_ledger_four_questions_rejects_unknown_caliber(self) -> None:
        """key 写错必须返回 None（而不是拿一个不存在的口径算四问）。"""
        assert el._ledger_four_questions(
            caliber_key="no_such_caliber", n=10, sample_note="x", tier="preliminary"
        ) is None

    def test_sample_source_is_marked(self) -> None:
        four = el._ledger_four_questions(
            caliber_key="limitup_premium", n=758, sample_note="14 个交易日", tier="preliminary"
        )

        assert four["sample_source"] == "evidence_declared"
        assert four["caliber_key"] == "limitup_premium"
        assert four["sample_note"] == "14 个交易日"

    def test_snapshot_caveat_is_in_the_sample_detail(self) -> None:
        """n 一问必须注明「静态快照、非实时查询」—— 否则会被当成刚跑出来的。"""
        four = el._ledger_four_questions(
            caliber_key="limitup_premium", n=758, sample_note="14 个交易日", tier="preliminary"
        )
        detail = {i["key"]: i for i in four["items"]}["sample"]["detail"]

        assert "非实时查询" in detail
        assert "最新跑批" in detail

    def test_only_n_is_answered_others_are_honestly_unanswered(self) -> None:
        """台账层只有 tier 与文字 —— 另三问必须答不上来，不去别处借数字。"""
        four = el._ledger_four_questions(
            caliber_key="limitup_premium", n=758, sample_note="x", tier="preliminary"
        )
        items = {i["key"]: i for i in four["items"]}

        assert items["sample"]["answered"] is True
        for key in ("median", "tradable", "benchmark_sign"):
            assert items[key]["answered"] is False, key
            assert items[key]["passed"] is None, key
        assert four["verdict"] == "unknown"

    def test_absent_questions_explain_where_to_look(self) -> None:
        """答不上来的问项要指路「去哪看」，而不是只说「没有」。"""
        four = el._ledger_four_questions(
            caliber_key="limitup_premium", n=758, sample_note="x", tier="preliminary"
        )
        items = {i["key"]: i for i in four["items"]}

        assert "研究页" in items["median"]["detail"] or "涨停带" in items["median"]["detail"]
        assert "tier_meaning" in items["tradable"]["detail"]
        assert "中证1000" in items["benchmark_sign"]["detail"]


class TestDoesNotAffectEvidenceTiers:
    """⚠️ 四问绝不能改变证据链的判定。"""

    @pytest.mark.asyncio
    async def test_tiers_and_actionable_are_untouched(self) -> None:
        from app.services import tactic_evidence

        report = await el.build()

        # 台账的 tier/actionable 必须与登记表逐项一致
        for item in report["items"]:
            table = tactic_evidence.EVIDENCE if item["namespace"] == "pattern" else tactic_evidence.STRATEGY_EVIDENCE
            ev = table[item["key"]]
            assert item["tier"] == ev.tier
            assert item["actionable"] == ev.actionable
            assert item["badge"] == ev.badge

    @pytest.mark.asyncio
    async def test_counts_still_derived_from_tiers_only(self) -> None:
        report = await el.build()

        total_by_tier: dict[str, int] = {}
        for item in report["items"]:
            total_by_tier[item["tier"]] = total_by_tier.get(item["tier"], 0) + 1

        assert report["counts"] == total_by_tier
        assert report["actionable_count"] == len(report["actionable_keys"])

    @pytest.mark.asyncio
    async def test_four_question_verdicts_are_counted_separately(self) -> None:
        """四问的 verdict 分布是**另一套统计**，不与 tier 的 counts 混在一起。"""
        report = await el.build()
        fq = report["four_questions"]

        assert fq["checked"] == len(el._EVIDENCE_SAMPLE)
        assert fq["verdict_counts"] == {"unknown": len(el._EVIDENCE_SAMPLE)}
        # 且与 tier 统计是并列的两份，不互相覆盖
        assert fq["checked"] <= len(report["items"])
        assert report["counts"]

    @pytest.mark.asyncio
    async def test_note_states_the_two_layers_are_independent(self) -> None:
        note = (await el.build())["four_questions"]["note"]

        assert "并列" in note
        assert "互不影响" in note


class TestNoDeadHelper:
    def test_no_unused_sample_extractor_remains(self) -> None:
        """正则抽取函数已删除 —— 留着会被人「顺手用一下」又踩子集当整体的坑。

        这是本项目的既有纪律：讨厌为规避 lint 而存在的死代码/死导出。
        """
        assert not hasattr(el, "_sample_from_text")
        assert not hasattr(el, "_CALIBER_KEY_BY_EVIDENCE_KEY")
