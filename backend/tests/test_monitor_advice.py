import unittest

from app.routes.monitor import _advice


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
        self.assertEqual(result["label"], "突破观察")

    def test_price_just_above_support_is_a_buy_watch(self) -> None:
        result = _advice(100.5, self.signal)

        self.assertEqual(result["action"], "buy")


if __name__ == "__main__":
    unittest.main()
