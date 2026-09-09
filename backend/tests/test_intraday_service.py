import unittest

from app.models import StockHistory
from app.services.intraday_service import compute_intraday_signals, intraday_advice


def _make_hist(closes, spread=1.0, volumes=None, session="20260909"):
    """构造带 OHLC 的分钟 K 线；最后 8 根属于同一个交易日。"""
    n = len(closes)
    dates = [f"20260908{i:04d}" for i in range(n - 8)] + [f"{session}{1000 + i * 5:04d}" for i in range(8)]
    opens = [c - spread * 0.2 for c in closes]
    highs = [c + spread * 0.5 for c in closes]
    lows = [c - spread * 0.5 for c in closes]
    return StockHistory(
        dates=dates,
        closes=closes,
        volumes=volumes if volumes is not None else [100.0] * n,
        opens=opens,
        highs=highs,
        lows=lows,
    )


class IntradaySignalTests(unittest.TestCase):
    def test_too_few_bars_returns_none(self) -> None:
        self.assertIsNone(compute_intraday_signals(_make_hist([10.0] * 10), 10.0, "15m"))

    def test_vwap_and_day_range_cover_only_current_session(self) -> None:
        # 前段为上一交易日的高价区，不应污染当日的 VWAP / 日内高低
        closes = [50.0] * 40 + [10.0] * 8
        hist = _make_hist(closes)
        sig = compute_intraday_signals(hist, 10.0, "15m")

        self.assertIsNotNone(sig)
        self.assertEqual(sig["session"], "20260909")
        # 当日全部 10 元附近，VWAP 不应被昨日的 50 元拉高
        self.assertAlmostEqual(sig["vwap"], 10.0, places=1)
        self.assertLess(sig["day_high"], 11.0)
        self.assertGreater(sig["day_low"], 9.0)

    def test_uptrend_detected_above_vwap(self) -> None:
        closes = [10.0] * 30 + [10.2, 10.4, 10.6, 10.8, 11.0, 11.2, 11.4, 11.6]
        sig = compute_intraday_signals(_make_hist(closes), 11.6, "15m")

        self.assertEqual(sig["trend"], "up")
        self.assertLess(sig["vwap"], 11.6)

    def test_downtrend_detected_below_vwap(self) -> None:
        closes = [12.0] * 30 + [11.8, 11.6, 11.4, 11.2, 11.0, 10.8, 10.6, 10.4]
        sig = compute_intraday_signals(_make_hist(closes), 10.4, "15m")

        self.assertEqual(sig["trend"], "down")
        self.assertGreater(sig["vwap"], 10.4)


class IntradayAdviceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sig = {
            "price": 10.0,
            "vwap": 10.0,
            "day_open": 9.9,
            "day_high": 10.3,
            "day_low": 9.7,
            "ma_fast": 10.05,
            "ma_slow": 9.95,
            "bb_upper": 10.4,
            "bb_lower": 9.6,
            "volume_ratio": 1.0,
            "trend": "flat",
            "support": 9.9,
            "resistance": 10.3,
            "stop_loss": 9.9,
            "strength": 5.0,
        }

    def test_breaking_day_low_is_a_sell(self) -> None:
        result = intraday_advice(9.65, self.sig, "15m")

        self.assertEqual(result["action"], "sell")
        self.assertEqual(result["label"], "破日内低")
        self.assertEqual(result["scope"], "intraday")

    def test_price_near_but_above_day_low_is_not_a_break(self) -> None:
        """现价在日内低点上方哪怕很近，也不能判成跌破（高价股 0.1% 就是好几块）。"""
        result = intraday_advice(9.71, {**self.sig, "trend": "up"}, "15m")

        self.assertNotEqual(result["label"], "破日内低")

    def test_volume_breakout_of_day_high_is_a_buy(self) -> None:
        sig = {**self.sig, "volume_ratio": 2.0}
        result = intraday_advice(10.35, sig, "15m")

        self.assertEqual(result["action"], "buy")
        self.assertEqual(result["label"], "放量破日内高")
        self.assertGreater(result["plan"]["position_pct"], 0)

    def test_breakout_without_volume_waits(self) -> None:
        sig = {**self.sig, "volume_ratio": 0.8}
        result = intraday_advice(10.35, sig, "15m")

        self.assertEqual(result["action"], "hold")
        self.assertEqual(result["label"], "破日内高待确认")

    def test_pullback_to_fast_ma_in_uptrend_is_a_buy(self) -> None:
        sig = {**self.sig, "trend": "up"}
        result = intraday_advice(10.06, sig, "15m")

        self.assertEqual(result["action"], "buy")
        self.assertEqual(result["label"], "回踩分钟均线")

    def test_intraday_stop_is_much_tighter_than_daily(self) -> None:
        """日内止损应控制在 1.5% 以内，远紧于日线的 3%。

        走完整链路（compute_intraday_signals → intraday_advice），
        因为止损带由周期 profile 决定，硬编码 sig 会绕过这段逻辑。
        """
        closes = [10.0] * 40 + [10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8]
        for period in ("5m", "15m", "30m", "60m"):
            sig = compute_intraday_signals(_make_hist(closes), 10.8, period)
            result = intraday_advice(10.8, sig, period)
            loss_pct = result["dist"]["to_stop"]  # 距止损的跌幅（正数）
            self.assertGreater(loss_pct, 0)
            self.assertLessEqual(loss_pct, 1.5)

    def test_shorter_period_has_tighter_stop(self) -> None:
        closes = [10.0] * 40 + [10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8]

        def _stop(period: str) -> float:
            sig = compute_intraday_signals(_make_hist(closes), 10.8, period)
            return intraday_advice(10.8, sig, period)["plan"]["stop"]

        self.assertGreater(_stop("5m"), _stop("15m"))
        self.assertGreater(_stop("15m"), _stop("60m"))

    def test_stop_clamps_when_day_low_is_far_below(self) -> None:
        """日内低点远低于现价时，止损不能被拉到日线级别的宽度。"""
        # 当日低点 9.5，现价 10.8 —— 直接用 9.5 就是 -12%，必须被 clamp
        closes = [10.0] * 40 + [10.8] * 7 + [10.8]
        hist = _make_hist(closes)
        hist.lows[-8] = 9.5
        sig = compute_intraday_signals(hist, 10.8, "15m")
        result = intraday_advice(10.8, sig, "15m")

        self.assertLessEqual(result["dist"]["to_stop"], 1.5)

    def test_advice_carries_intraday_metadata(self) -> None:
        result = intraday_advice(10.35, {**self.sig, "volume_ratio": 2.0}, "5m")

        self.assertEqual(result["scope"], "intraday")
        self.assertEqual(result["period"], "5m")
        self.assertIn("当日有效", result["session_note"])


if __name__ == "__main__":
    unittest.main()
