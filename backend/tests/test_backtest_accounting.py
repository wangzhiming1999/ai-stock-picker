import unittest
from unittest.mock import patch

import pandas as pd

from app.services.backtest_service import BacktestParams, _score, run_backtest


class BacktestAccountingTests(unittest.TestCase):
    def test_quality_momentum_rejects_momentum_without_trend(self) -> None:
        dates = pd.date_range("2025-01-01", periods=65, freq="B")
        falling = pd.DataFrame(
            {
                "date": dates,
                "close": list(range(100, 35, -1)),
                "amount": [1_000_000.0] * len(dates),
            }
        )

        self.assertEqual(_score(falling, "quality_momentum"), -999)

    def test_uninvested_cash_is_preserved_across_rebalances(self) -> None:
        dates = pd.date_range("2025-01-01", periods=65, freq="B")
        history = pd.DataFrame(
            {
                "date": dates,
                "close": [60.0] * len(dates),
                "amount": [1_000_000.0] * len(dates),
            }
        )
        benchmark = pd.DataFrame({"date": dates, "close": [100.0] * len(dates)})
        params = BacktestParams(
            strategy="value",
            codes=["600000"],
            start_date="2025-01-01",
            end_date="2025-04-30",
            top_n=1,
            rebalance_days=5,
            initial_capital=100.0,
        )

        with (
            patch("app.services.backtest_service._fetch_history", return_value=history),
            patch("app.services.backtest_service.akshare_guard.call", return_value=benchmark),
        ):
            result = run_backtest(params)

        self.assertEqual(result["final_value"], 100.0)
        self.assertEqual(result["total_return"], 0.0)


if __name__ == "__main__":
    unittest.main()
