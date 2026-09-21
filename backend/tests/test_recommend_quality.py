import unittest

from app.services.recommend_service import (
    _build_action_plan,
    _build_watchlist_candidates,
    _merge_blockers,
    _merge_strategy_results,
    _quality_gate,
    _rr_unlock_price,
    _should_use_cached_recommendation,
    _watch_unlock,
    db_source,
)


class RecommendQualityTests(unittest.TestCase):
    def test_legacy_empty_snapshot_is_regenerated_for_watchlist_support(self) -> None:
        self.assertFalse(
            _should_use_cached_recommendation({"source": "empty", "recommendations": []})
        )
        self.assertFalse(_should_use_cached_recommendation({"schema_version": 2, "source": "empty", "recommendations": [], "watchlist": []}))
        # v3 快照存的是「盈亏比不足 + 买点关注」的矛盾文案，必须重算
        self.assertFalse(_should_use_cached_recommendation({"schema_version": 3, "source": "empty", "recommendations": [], "watchlist": []}))
        # v4 快照没有 expected_price 字段 —— 不重算就会整整一天给不出预期价格
        self.assertFalse(_should_use_cached_recommendation({"schema_version": 4, "source": "empty", "recommendations": [], "watchlist": []}))
        self.assertTrue(_should_use_cached_recommendation({"schema_version": 5, "source": "empty", "recommendations": [], "watchlist": []}))

    def test_rejects_high_chase_candidate(self) -> None:
        candidate = {"price": 20, "change_pct": 8.5, "turnover": 4, "strategy_score": 8, "signal": {"rr_ratio": 2}}
        accepted, flags = _quality_gate(candidate)
        self.assertFalse(accepted)
        self.assertIn("涨幅过高", flags)

    def test_rejects_candidate_with_poor_risk_reward(self) -> None:
        candidate = {"price": 20, "change_pct": 2, "turnover": 4, "strategy_score": 8, "signal": {"rr_ratio": 0.7}}
        accepted, flags = _quality_gate(candidate)
        self.assertFalse(accepted)
        self.assertIn("风险收益比不足", flags)

    def test_accepts_confirmed_breakout_setup_even_when_old_resistance_makes_rr_small(self) -> None:
        candidate = {
            "price": 106.97,
            "change_pct": 0.94,
            "turnover": 2.5,
            "strategy_score": 5.9,
            "tags": ["接近新高", "量能活跃", "均线多头", "MACD转强"],
            "signal": {"rr_ratio": 0.6, "strength": 8, "resistance": 108.0, "support": 101.0},
        }

        accepted, flags = _quality_gate(candidate)

        self.assertTrue(accepted)
        self.assertNotIn("风险收益比不足", flags)

    def test_breakout_action_plan_uses_resistance_as_trigger(self) -> None:
        candidate = {
            "price": 106.97,
            "change_pct": 0.94,
            "strategy_score": 5.9,
            "tags": ["接近新高", "量能活跃", "均线多头"],
            "signal": {"buy_point": 105.9, "stop_loss": 101.0, "resistance": 108.0, "rr_ratio": 0.6, "strength": 8},
        }

        plan = _build_action_plan(candidate, "2026-09-09")

        self.assertIn("放量突破 108.00", plan["trigger"])
        self.assertIn("未突破不买", plan["trigger"])
        self.assertIn("跌回 108.00", plan["invalidation"])

    def test_allows_low_turnover_for_large_cap_candidate(self) -> None:
        candidate = {
            "price": 20,
            "change_pct": 2,
            "turnover": 0.08,
            "market_cap_yi": 1000,
            "strategy_score": 8,
            "signal": {"rr_ratio": 2},
        }
        accepted, flags = _quality_gate(candidate)
        self.assertTrue(accepted)
        self.assertNotIn("流动性异常", flags)

    def test_action_plan_has_trigger_invalidation_and_target(self) -> None:
        candidate = {
            "price": 20,
            "signal": {"buy_point": 19.8, "stop_loss": 18.9, "sell_point": 22.0, "rr_ratio": 2.2},
        }
        plan = _build_action_plan(candidate, "2026-09-08")
        self.assertIn("19.80", plan["trigger"])
        self.assertIn("18.90", plan["invalidation"])
        self.assertEqual(plan["valid_until"], "2026-09-08")


class ExpectedPriceTests(unittest.TestCase):
    """预期价格：给「不知道怎么操作」补上执行价位。

    核心不变量：**预期价格必须与同一行的触发文案是同一个数** ——
    文案说回踩 19.80、价格却给 20.10，用户会不知道挂哪个。
    """

    def test_pullback_plan_anchors_on_buy_point(self) -> None:
        candidate = {
            "price": 20,
            "signal": {"buy_point": 19.8, "stop_loss": 18.9, "sell_point": 22.0, "rr_ratio": 2.2},
        }
        plan = _build_action_plan(candidate, "2026-09-08")
        self.assertEqual(plan["expected_price"], 19.8)
        self.assertEqual(plan["expected_price_setup"], "pullback")
        # 触发文案里的数与预期价格必须是同一个
        self.assertIn(f"{plan['expected_price']:.2f}", plan["trigger"])
        # 现价 20 > 锚点 19.8 → 偏离为负（要等它跌回来）
        self.assertEqual(plan["expected_price_gap_pct"], -1.0)
        self.assertIn("回踩位", plan["expected_price_note"])

    def test_breakout_plan_anchors_on_resistance(self) -> None:
        candidate = {
            "price": 106.97,
            "change_pct": 0.94,
            "strategy_score": 5.9,
            "tags": ["接近新高", "量能活跃", "均线多头"],
            "signal": {"buy_point": 105.9, "stop_loss": 101.0, "resistance": 108.0, "rr_ratio": 0.6, "strength": 8},
        }
        plan = _build_action_plan(candidate, "2026-09-09")
        self.assertEqual(plan["expected_price_setup"], "breakout")
        self.assertEqual(plan["expected_price"], 108.0)
        self.assertIn("108.00", plan["trigger"])
        self.assertIn("突破位", plan["expected_price_note"])
        # 现价低于锚点 → 偏离为正（要等它涨上去突破）
        self.assertGreater(plan["expected_price_gap_pct"], 0)

    def test_missing_levels_yield_none_not_zero(self) -> None:
        """结构位拿不到时必须是 None —— 折算成 0 或现价会造出一个假锚点。"""
        plan = _build_action_plan({"price": 20, "signal": None}, "2026-09-08")
        self.assertIsNone(plan["expected_price"])
        self.assertIsNone(plan["expected_price_gap_pct"])
        self.assertIn("不可给", plan["expected_price_note"])

    def test_gap_is_none_when_price_unknown(self) -> None:
        """锚点有、现价没有：价格照给，偏离量置 None（不除以 0）。"""
        plan = _build_action_plan(
            {"price": 0, "signal": {"buy_point": 19.8, "stop_loss": 18.9, "resistance": 22.0}},
            "2026-09-08",
        )
        self.assertEqual(plan["expected_price"], 19.8)
        self.assertIsNone(plan["expected_price_gap_pct"])

    def test_expected_price_never_used_as_entry_for_settlement(self) -> None:
        """口径隔离：预期价格只是执行锚点，结算用的仍是 recommend_price（现价）。"""
        candidate = {
            "price": 20,
            "signal": {"buy_point": 19.8, "stop_loss": 18.9, "sell_point": 22.0, "rr_ratio": 2.2},
        }
        plan = _build_action_plan(candidate, "2026-09-08")
        self.assertNotIn("recommend_price", plan)
        # 计划里不出现任何以预期价格为准的收益字段
        self.assertNotIn("expected_return", plan)
        self.assertNotIn("target_from_expected", plan)

    def test_strategy_merge_requires_momentum_and_trend_confirmation(self) -> None:
        results = [
            ("momentum", [{"code": "600000", "strategy_score": 7, "tags": ["动量"], "indicators": {"rsi": 60}}]),
            ("trend", [{"code": "600000", "strategy_score": 4.5, "tags": ["趋势"], "indicators": {"ma20": 10}}]),
            ("value", [{"code": "000001", "strategy_score": 6, "tags": ["低估"], "indicators": {}}]),
        ]

        merged = _merge_strategy_results(results)

        self.assertEqual([item["code"] for item in merged], ["600000"])
        self.assertEqual(merged[0]["strategy_votes"], ["momentum", "trend"])
        self.assertLessEqual(merged[0]["strategy_score"], 10)

    def test_watchlist_keeps_near_miss_without_promoting_value_only_stock(self) -> None:
        results = [
            ("momentum", [{"code": "600000", "name": "浦发银行", "price": 10, "strategy_score": 5, "tags": ["动量"], "indicators": {}}]),
            ("trend", [{"code": "600000", "name": "浦发银行", "price": 10, "strategy_score": 3, "tags": ["趋势待确认"], "indicators": {}}]),
            ("value", [{"code": "000001", "name": "平安银行", "price": 11, "strategy_score": 7, "tags": ["低估"], "indicators": {}}]),
        ]

        watchlist = _build_watchlist_candidates(results, excluded_codes=set())

        self.assertEqual([item["code"] for item in watchlist], ["600000"])
        self.assertEqual(watchlist[0]["status"], "等待趋势确认")

    def test_watchlist_excludes_high_chase_candidate(self) -> None:
        results = [
            ("momentum", [{"code": "300001", "name": "高涨幅", "price": 20, "change_pct": 12, "strategy_score": 8, "tags": [], "indicators": {}}]),
            ("trend", [{"code": "300001", "name": "高涨幅", "price": 20, "change_pct": 12, "strategy_score": 5, "tags": [], "indicators": {}}]),
        ]

        self.assertEqual(_build_watchlist_candidates(results, excluded_codes=set()), [])

    def test_watchlist_exposes_merge_stage_blockers(self) -> None:
        """观察层必须交代「策略势头」这一层为什么没达标，不能只透出风控文案。"""
        results = [
            ("momentum", [{"code": "600000", "name": "浦发银行", "price": 10, "strategy_score": 3.5, "tags": [], "indicators": {}}]),
            ("trend", [{"code": "600000", "name": "浦发银行", "price": 10, "strategy_score": 3, "tags": [], "indicators": {}}]),
        ]

        watchlist = _build_watchlist_candidates(results, excluded_codes=set())

        self.assertEqual(watchlist[0]["blockers"], ["动量不足", "趋势未确认"])

    def test_merge_blockers_prefers_hard_gate_and_drops_redundant_momentum(self) -> None:
        merged = _merge_blockers(["动量不足", "趋势未确认"], ["策略强度不足", "风险收益比不足"])

        self.assertEqual(merged, ["策略强度不足", "风险收益比不足", "趋势未确认"])

    def test_rr_unlock_price_restores_the_gate_threshold(self) -> None:
        signal = {"resistance": 110.0, "stop_loss": 95.0}
        unlock = _rr_unlock_price(signal)

        self.assertIsNotNone(unlock)
        rr_at_unlock = (110.0 - unlock) / (unlock - 95.0)
        self.assertAlmostEqual(rr_at_unlock, 1.2, delta=0.01)
        self.assertEqual(_rr_unlock_price({}), None)

    def test_watch_unlock_never_tells_a_rejected_stock_to_buy(self) -> None:
        """核心回归：被风控拦下的票不能再拿到「回踩买点企稳再关注」这种买入指令。"""
        candidate = {
            "price": 108.0,
            "strategy_score": 6.3,
            "signal": {"resistance": 110.0, "stop_loss": 95.0, "buy_point": 106.9, "rr_ratio": 0.15},
        }

        text = _watch_unlock(candidate, ["风险收益比不足"])

        self.assertIn("101.82", text)  # 真正修复盈亏比的价格
        self.assertIn("110.00", text)  # 或者放量突破打开上行空间
        self.assertNotIn("106.90", text)  # 旧买点高于解锁价，盈亏比依旧不达标
        self.assertNotIn("企稳", text)
        self.assertNotIn("再关注", text)

    def test_watch_unlock_falls_back_without_signal(self) -> None:
        self.assertEqual(_watch_unlock({"signal": None}, []), "等待技术信号进一步确认后再评估")


class ConfidenceSourceTests(unittest.TestCase):
    """confidence 双语义拆分（2026-09-20 技术债）。

    `daily_recommendations.confidence` 是「按同行 source 解释的分数槽」：
    同为 0-10，却分别是 LLM 自评把握、规则加权策略分、quad 四维综合分。
    此前 source 靠「reason 里有没有『策略分』三个字」反推 —— 猜文案，不是判事实。
    """

    def test_llm_reason_mentioning_strategy_score_is_not_mislabelled(self) -> None:
        # 回归用例：LLM 在理由里写了「策略分」，旧逻辑会把整行错标成 rule，
        # 污染 winrate 的 by_source 分档（llm / rule / watch / quad 不可相加）。
        rec = {
            "confidence": 7,
            "confidence_source": "llm_self_report",
            "reason": "量价配合良好，策略分位置不高，趋势确认后仍有空间",
        }
        self.assertEqual(db_source(rec), "llm")

    def test_rule_recommendation_maps_to_rule(self) -> None:
        self.assertEqual(db_source({"confidence": 8.2, "confidence_source": "rule_score"}), "rule")

    def test_missing_source_no_longer_guesses_from_reason_text(self) -> None:
        # 老快照没有该字段。此时两个 reason 完全不同的推荐必须落同一边 ——
        # 只要结果还随 reason 变化，就说明文本推断没被真正移除。
        with_wording = {"confidence": 4, "reason": "策略分 6，依据：放量"}
        without_wording = {"confidence": 4, "reason": "四维共振，量能温和放大"}
        self.assertEqual(db_source(with_wording), db_source(without_wording))

    def test_unknown_source_value_degrades_instead_of_raising(self) -> None:
        # 未知取值不能抛异常（结算链路写入不能被一条脏数据打断），
        # 落到与缺字段一致的兜底值。
        self.assertEqual(db_source({"confidence_source": "watch"}), db_source({}))

    def test_every_declared_source_is_registered(self) -> None:
        # 新增 confidence_source 取值时必须同步登记映射，否则会静默落到兜底档
        from app.services.recommend_service import _CONFIDENCE_SOURCE_TO_DB

        self.assertEqual(set(_CONFIDENCE_SOURCE_TO_DB), {"llm_self_report", "rule_score"})
        self.assertEqual(set(_CONFIDENCE_SOURCE_TO_DB.values()), {"llm", "rule"})


if __name__ == "__main__":
    unittest.main()
