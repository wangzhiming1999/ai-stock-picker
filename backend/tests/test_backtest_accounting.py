import unittest
from datetime import date
from unittest.mock import patch

import pandas as pd

from app.services import backtest_service
from app.services.backtest_service import (
    BacktestParams,
    _close_on_or_before,
    _score,
    _value_positions,
    run_backtest,
)


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


class FetchFailureCacheTests(unittest.TestCase):
    """取数失败不能被当成「这段区间没有数据」锁进长 TTL。

    2026-10-05 实测缺陷：两者共用 30 分钟 TTL，一次瞬时 SSLError 会让该票在半小时内
    恒为空且不报错 —— 回测池子从 18 只悄悄变 16/15，同一参数复跑结果都不一样。
    """

    KEY = ("600519", "2025-01-01", "2025-06-30")

    def setUp(self) -> None:
        backtest_service._history_cache.clear()

    def _cached(self):
        return backtest_service._history_cache[self.KEY]

    def test_transient_fetch_error_uses_short_negative_ttl(self) -> None:
        failed: list[str] = []
        with patch.object(backtest_service.akshare_guard, "call", side_effect=RuntimeError("SSLError")):
            df = backtest_service._fetch_history(*self.KEY, failed=failed)

        self.assertTrue(df.empty)
        self.assertEqual(failed, ["600519"])
        _, cached_df, ttl, is_failure = self._cached()
        self.assertTrue(cached_df.empty)
        self.assertTrue(is_failure, "取数失败必须被标记，否则无法与「真的没有数据」区分")
        self.assertEqual(ttl, backtest_service._HIST_TTL_FAIL)
        self.assertLess(backtest_service._HIST_TTL_FAIL, backtest_service._HIST_TTL)

    def test_cached_failure_is_still_reported(self) -> None:
        with patch.object(backtest_service.akshare_guard, "call", side_effect=RuntimeError("SSLError")):
            backtest_service._fetch_history(*self.KEY)

        failed: list[str] = []
        df = backtest_service._fetch_history(*self.KEY, failed=failed)

        self.assertTrue(df.empty)
        self.assertEqual(failed, ["600519"], "命中负缓存时也要登记，不能因为「命中了」就静默")

    def test_genuine_empty_is_not_a_fetch_failure(self) -> None:
        failed: list[str] = []
        with patch.object(backtest_service.akshare_guard, "call", return_value=pd.DataFrame()):
            df = backtest_service._fetch_history(*self.KEY, failed=failed)

        self.assertTrue(df.empty)
        self.assertEqual(failed, [], "真的没有数据不等于取数失败")
        _, _, ttl, is_failure = self._cached()
        self.assertFalse(is_failure)
        self.assertEqual(ttl, backtest_service._HIST_TTL)

    def test_transient_error_is_retried_once_before_giving_up(self) -> None:
        """单只偶发失败必须重试：18 只池少 2 只足以让总收益从 +28% 掉到 +14%。"""
        calls = {"n": 0}
        frame = pd.DataFrame({"date": pd.to_datetime(["2025-01-02"]), "close": [10.0]})

        def flaky(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("SSLError")
            return frame

        failed: list[str] = []
        with (
            patch.object(backtest_service.akshare_guard, "call", side_effect=flaky),
            patch.object(backtest_service.time, "sleep", lambda *_: None),
        ):
            df = backtest_service._fetch_history(*self.KEY, failed=failed)

        self.assertEqual(calls["n"], 2, "第一次失败后应重试一次")
        self.assertEqual(len(df), 1)
        self.assertEqual(failed, [], "重试成功后不该再登记为取数失败")
        _, _, ttl, is_failure = self._cached()
        self.assertEqual(ttl, backtest_service._HIST_TTL)
        self.assertFalse(is_failure)

    def test_run_backtest_surfaces_failed_codes(self) -> None:
        dates = pd.date_range("2025-01-01", periods=65, freq="B")
        history = pd.DataFrame(
            {"date": dates, "close": [10.0] * len(dates), "amount": [1_000_000.0] * len(dates)}
        )
        benchmark = pd.DataFrame({"date": dates, "close": [100.0] * len(dates)})

        def fake_fetch(code, start, end, *, failed=None):
            if code == "600000":
                if failed is not None:
                    failed.append(code)
                return pd.DataFrame()
            return history

        params = BacktestParams(
            strategy="momentum",
            codes=["600000", "000001"],
            start_date="2025-01-01",
            end_date="2025-04-30",
            top_n=1,
            rebalance_days=5,
            initial_capital=100000.0,
        )
        with (
            patch("app.services.backtest_service._fetch_history", side_effect=fake_fetch),
            patch("app.services.backtest_service.akshare_guard.call", return_value=benchmark),
        ):
            result = run_backtest(params)

        self.assertEqual(result["fetch_failed"], ["600000"])
        self.assertEqual(result["pool_size"], 1)
        self.assertIn("取数失败", result["data_note"])
        self.assertIn("600000", result["data_note"])

    def test_single_code_exception_is_isolated_and_recorded(self) -> None:
        """单只抛异常不该拖垮整轮，但也不能静默少一只。"""
        dates = pd.date_range("2025-01-01", periods=65, freq="B")
        history = pd.DataFrame(
            {"date": dates, "close": [10.0] * len(dates), "amount": [1_000_000.0] * len(dates)}
        )
        benchmark = pd.DataFrame({"date": dates, "close": [100.0] * len(dates)})

        def fake_fetch(code, start, end, *, failed=None):
            if code == "600000":
                raise KeyError("date")
            return history

        params = BacktestParams(
            strategy="momentum",
            codes=["600000", "000001"],
            start_date="2025-01-01",
            end_date="2025-04-30",
            top_n=1,
            rebalance_days=5,
            initial_capital=100000.0,
        )
        with (
            patch("app.services.backtest_service._fetch_history", side_effect=fake_fetch),
            patch("app.services.backtest_service.akshare_guard.call", return_value=benchmark),
        ):
            result = run_backtest(params)

        self.assertEqual(result["fetch_failed"], ["600000"])
        self.assertEqual(result["pool_size"], 1)


class PositionValuationTests(unittest.TestCase):
    """持仓取不到当日价时按最近一次已知价估值，不能跳过/清零。

    2026-10-05 实测缺陷：`period_value += shares * 0  # 停牌按原值` ——
    注释写「按原值」，实现却是把该持仓从组合市值里抹掉。
    """

    def test_close_on_or_before_picks_last_row_at_or_before_date(self) -> None:
        df = pd.DataFrame(
            {
                "date": pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"]),
                "close": [1.0, 2.0, 3.0],
            }
        )

        self.assertEqual(_close_on_or_before(df, date(2025, 1, 4)), 2.0)
        self.assertEqual(_close_on_or_before(df, date(2025, 1, 6)), 3.0)
        self.assertIsNone(_close_on_or_before(df, date(2025, 1, 1)))
        self.assertIsNone(_close_on_or_before(None, date(2025, 1, 4)))
        self.assertIsNone(_close_on_or_before(pd.DataFrame(), date(2025, 1, 4)))

    def test_missing_price_falls_back_to_last_known_instead_of_zeroing(self) -> None:
        last_price = {"600000": 10.0}
        portfolio = [("600000", 100.0)]

        # 该票已不在 histories 里（数据缺口）→ 按最近已知价 10 元计 1000，而不是 0
        value = _value_positions(portfolio, {}, date(2025, 3, 3), last_price)

        self.assertEqual(value, 1000.0)

    def test_available_price_is_used_and_recorded_as_last_known(self) -> None:
        df = pd.DataFrame({"date": pd.to_datetime(["2025-03-01"]), "close": [12.5]})
        last_price: dict[str, float] = {}

        value = _value_positions([("600000", 100.0)], {"600000": df}, date(2025, 3, 3), last_price)

        self.assertEqual(value, 1250.0)
        self.assertEqual(last_price, {"600000": 12.5})


if __name__ == "__main__":
    unittest.main()
