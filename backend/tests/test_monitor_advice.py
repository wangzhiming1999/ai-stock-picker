import unittest

from app.routes.monitor import _advice, _projected_volume_ratio
from app.services.signal_service import compute_signals


class MonitorAdviceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.signal = {
            "support": 100.0,
            "resistance": 110.0,
            "stop_loss": 95.0,
            "strength": 7.0,
        }

    def test_price_below_support_is_not_reported_as_buy(self) -> None:
        result = _advice(98.0, self.signal)

        self.assertEqual(result["action"], "sell")
        self.assertEqual(result["label"], "跌破支撑")

    def test_price_above_resistance_is_not_reported_as_near_resistance_sell(self) -> None:
        result = _advice(112.0, self.signal)

        self.assertEqual(result["action"], "hold")
        self.assertEqual(result["label"], "突破待确认")

    def test_price_just_above_support_is_a_buy_watch(self) -> None:
        result = _advice(100.5, self.signal)

        self.assertEqual(result["action"], "buy")

    def test_falling_below_a_buy_support_does_not_become_hold(self) -> None:
        closes = [30.0, 50.0] + [35.0] * 38 + [39.8] * 20
        advice_at_40 = _advice(40.0, compute_signals(closes, 40.0))
        advice_at_39 = _advice(39.0, compute_signals(closes, 39.0))

        self.assertEqual(advice_at_40["action"], "buy")
        self.assertEqual(advice_at_39["action"], "sell")
        self.assertEqual(advice_at_39["label"], "跌破支撑")

    def test_volume_breakout_is_actionable(self) -> None:
        signal = {**self.signal, "volume_ratio": 1.8}
        result = _advice(111.0, signal)

        self.assertEqual(result["action"], "buy")
        self.assertEqual(result["label"], "放量突破")

    def test_weak_volume_breakout_waits_for_confirmation(self) -> None:
        signal = {**self.signal, "volume_ratio": 0.8}
        result = _advice(111.0, signal)

        self.assertEqual(result["action"], "hold")
        self.assertEqual(result["label"], "缩量突破")

    def test_extended_breakout_is_not_chased(self) -> None:
        signal = {**self.signal, "volume_ratio": 2.0}
        result = _advice(114.0, signal)

        self.assertEqual(result["action"], "hold")
        self.assertEqual(result["label"], "突破过远")

    def test_volume_ratio_adjusts_for_elapsed_trading_time(self) -> None:
        ratio = _projected_volume_ratio(
            live_volume=30.0,
            historical_volumes=[100.0] * 5,
            quote_time="2026-09-08T10:30:00+08:00",
        )

        self.assertAlmostEqual(ratio, 1.2)

    def test_opening_minutes_do_not_emit_noisy_volume_ratio(self) -> None:
        ratio = _projected_volume_ratio(
            live_volume=10.0,
            historical_volumes=[100.0] * 5,
            quote_time="2026-09-08T09:35:00+08:00",
        )

        self.assertIsNone(ratio)


if __name__ == "__main__":
    unittest.main()
