import unittest

from app.models import StockHistory
from app.services.winrate_service import _next_close_after, _sample_status


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


if __name__ == "__main__":
    unittest.main()
