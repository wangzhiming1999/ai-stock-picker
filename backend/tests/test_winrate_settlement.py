import unittest

from app.models import StockHistory
from app.services.winrate_service import (
    _index_window_return,
    _next_close_after,
    _reco_outcome,
    _sample_status,
)


class RecommendationSettlementTests(unittest.TestCase):
    def test_uses_first_trading_close_after_recommendation_date(self) -> None:
        history = StockHistory(
            dates=["2026-09-04", "2026-09-07", "2026-09-08"],
            closes=[10.0, 10.5, 11.0],
        )
        self.assertEqual(_next_close_after(history, "2026-09-04"), ("2026-09-07", 10.5))

    def test_does_not_settle_before_next_close_exists(self) -> None:
        history = StockHistory(dates=["2026-09-04"], closes=[10.0])
        self.assertIsNone(_next_close_after(history, "2026-09-04"))

    def test_small_samples_are_explicitly_marked_insufficient(self) -> None:
        self.assertEqual(_sample_status(29), "insufficient")
        self.assertEqual(_sample_status(30), "developing")


class RecoExcessCaliberTests(unittest.TestCase):
    """结算超额口径的核心换算：扣费 + 对比基准，超额为正才算赢。"""

    def test_index_window_return_aligned_to_holding_period(self) -> None:
        bench = StockHistory(
            dates=["2026-09-04", "2026-09-07", "2026-09-08"],
            closes=[4000.0, 4040.0, 4080.0],
        )
        # rec_date 收盘买入、next_date 收盘卖出：4040/4000 - 1 = 1.0%
        self.assertAlmostEqual(_index_window_return(bench, "2026-09-04", "2026-09-07"), 1.0, places=4)

    def test_index_window_return_none_when_benchmark_missing(self) -> None:
        self.assertIsNone(_index_window_return(None, "2026-09-04", "2026-09-07"))
        bench = StockHistory(dates=["2026-09-07", "2026-09-08"], closes=[4040.0, 4080.0])
        # rec_date 当天无基准收盘 → 无法对齐持有期 → 回退
        self.assertIsNone(_index_window_return(bench, "2026-09-04", "2026-09-07"))

    def test_reco_outcome_beats_index(self) -> None:
        net, excess, hit = _reco_outcome(2.0, 1.0, 0.15)
        self.assertAlmostEqual(net, 1.85)
        self.assertAlmostEqual(excess, 0.85)
        self.assertTrue(hit)

    def test_reco_outcome_loses_to_index(self) -> None:
        net, excess, hit = _reco_outcome(2.0, 3.0, 0.15)
        self.assertAlmostEqual(net, 1.85)
        self.assertAlmostEqual(excess, -1.15)
        self.assertFalse(hit)

    def test_reco_outcome_falls_back_when_benchmark_unavailable(self) -> None:
        # 基准缺失时降级为旧口径：看 next_return 是否 > 0，excess 置空。
        net, excess, hit = _reco_outcome(2.0, None, 0.15)
        self.assertAlmostEqual(net, 1.85)
        self.assertIsNone(excess)
        self.assertTrue(hit)
        net2, excess2, hit2 = _reco_outcome(-1.0, None, 0.15)
        self.assertAlmostEqual(net2, -1.15)
        self.assertIsNone(excess2)
        self.assertFalse(hit2)


if __name__ == "__main__":
    unittest.main()
