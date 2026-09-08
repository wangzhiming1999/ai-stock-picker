import unittest

from app.services.recommend_service import (
    _build_action_plan,
    _build_watchlist_candidates,
    _merge_strategy_results,
    _quality_gate,
    _should_use_cached_recommendation,
)


class RecommendQualityTests(unittest.TestCase):
    def test_legacy_empty_snapshot_is_regenerated_for_watchlist_support(self) -> None:
        self.assertFalse(
            _should_use_cached_recommendation({"source": "empty", "recommendations": []})
        )
        self.assertTrue(
            _should_use_cached_recommendation({"source": "empty", "recommendations": [], "watchlist": []})
        )

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


if __name__ == "__main__":
    unittest.main()
