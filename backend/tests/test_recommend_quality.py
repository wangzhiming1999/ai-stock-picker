import unittest

from app.services.recommend_service import _build_action_plan, _quality_gate


class RecommendQualityTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
