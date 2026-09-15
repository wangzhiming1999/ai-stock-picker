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
)


class RecommendQualityTests(unittest.TestCase):
    def test_legacy_empty_snapshot_is_regenerated_for_watchlist_support(self) -> None:
        self.assertFalse(
            _should_use_cached_recommendation({"source": "empty", "recommendations": []})
        )
        self.assertFalse(_should_use_cached_recommendation({"schema_version": 2, "source": "empty", "recommendations": [], "watchlist": []}))
        # v3 快照存的是「盈亏比不足 + 买点关注」的矛盾文案，必须重算
        self.assertFalse(_should_use_cached_recommendation({"schema_version": 3, "source": "empty", "recommendations": [], "watchlist": []}))
        self.assertTrue(_should_use_cached_recommendation({"schema_version": 4, "source": "empty", "recommendations": [], "watchlist": []}))

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


if __name__ == "__main__":
    unittest.main()
