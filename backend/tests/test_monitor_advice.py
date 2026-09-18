import unittest

from app.routes.monitor import _advice, _projected_volume_ratio, _summary, _with_cost
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

    def test_advice_carries_an_executable_plan(self) -> None:
        result = _advice(100.5, self.signal)

        plan = result["plan"]
        self.assertEqual(plan["stop"], 95.0)
        self.assertEqual(plan["target"], 110.0)
        # 回踩买点落在现价下方且不高于支撑之上太远
        self.assertLessEqual(plan["buy"], 100.5)
        self.assertGreater(plan["position_pct"], 0)
        self.assertIn("买入", result["do"])

    def test_breakout_sets_sell_at_the_former_resistance(self) -> None:
        result = _advice(112.0, self.signal)

        self.assertEqual(result["plan"]["sell"], 110.0)


class MonitorCostTests(unittest.TestCase):
    def setUp(self) -> None:
        self.signal = {
            "support": 100.0,
            "resistance": 110.0,
            "stop_loss": 95.0,
            "buy_point": 99.5,
            "sell_point": 101.5,
            "strength": 7.0,
        }

    def test_big_profit_turns_hold_into_take_profit(self) -> None:
        advice = _advice(105.0, self.signal)  # 区间震荡 → hold
        self.assertEqual(advice["action"], "hold")

        with_cost = _with_cost(advice, 105.0, 90.0, self.signal)  # 浮盈 16.7%
        self.assertEqual(with_cost["action"], "sell")
        self.assertEqual(with_cost["label"], "盈利止盈")
        self.assertAlmostEqual(with_cost["pnl_pct"], 16.67, places=1)

    def test_hard_stop_is_tighter_than_technical_stop(self) -> None:
        advice = _advice(105.0, self.signal)
        with_cost = _with_cost(advice, 105.0, 100.0, self.signal)

        # 成本 100 → 硬止损 93；技术止损 95 → 取更紧的 93
        self.assertAlmostEqual(with_cost["plan"]["stop"], 93.0, places=2)

    def test_deep_loss_flags_stop_risk(self) -> None:
        advice = _advice(105.0, self.signal)
        with_cost = _with_cost(advice, 105.0, 118.0, self.signal)  # 浮亏 11%

        self.assertEqual(with_cost["action"], "sell")
        self.assertEqual(with_cost["label"], "逼近止损")


class MonitorSummaryTests(unittest.TestCase):
    def test_summary_counts_and_orders_actions(self) -> None:
        items = [
            {"code": "600519", "name": "A", "price": 1.0, "advice": {"action": "hold", "label": "观望", "tone": "neutral", "do": ""}},
            {"code": "000858", "name": "B", "price": 2.0, "advice": {"action": "buy", "label": "回踩可买", "tone": "good", "do": "挂 2.00 买入"}},
            {"code": "601318", "name": "C", "price": 3.0, "advice": {"action": "stop", "label": "止损离场", "tone": "danger", "do": "现价止损"}},
        ]
        result = _summary(items)

        self.assertEqual(result["act_now"], 2)
        self.assertEqual(result["buy"], 1)
        self.assertEqual(result["stop"], 1)
        self.assertEqual(result["total"], 3)
        self.assertEqual([t["code"] for t in result["top"]], ["601318", "000858"])


class SignalLevelTests(unittest.TestCase):
    """结构位必须来自「已走完的那根」。

    盘中日 K 最后一根的收盘价就是现价（实测差异 0.000%）。若定档参考价含这一根，
    则 support 恒 ≤ 现价、resistance 恒 ≥ 现价、stop_loss 恒 < 现价，
    「跌破支撑 / 突破压力 / 止损离场」三档在定义上永远不可能成立
    （实测 10500 个样本触发 0 次）。下面几条断言把这个可达性钉住。
    """

    def test_in_progress_bar_does_not_participate_in_level_selection(self) -> None:
        sig = compute_signals([50.0] * 79 + [60.0], 60.0)

        self.assertLess(sig["high60"], 60.0)

    def test_crash_day_reads_as_support_break_not_a_buy(self) -> None:
        # 前 79 根横在 50，最后一根（当日）跌到 49 —— 旧实现会给出「回踩可买」
        closes = [50.0] * 79 + [49.0]
        result = _advice(49.0, compute_signals(closes, 49.0))

        self.assertEqual(result["action"], "sell")
        self.assertEqual(result["label"], "跌破支撑")

    def test_drop_through_stop_is_reachable(self) -> None:
        closes = [50.0] * 79 + [47.0]  # 支撑 50 → 止损 48.5
        result = _advice(47.0, compute_signals(closes, 47.0))

        self.assertEqual(result["action"], "stop")
        self.assertEqual(result["label"], "止损离场")

    def test_gap_up_can_reach_the_resistance_branch(self) -> None:
        closes = [50.0] * 79 + [51.0]
        result = _advice(51.0, compute_signals(closes, 51.0))

        self.assertEqual(result["action"], "hold")
        self.assertEqual(result["label"], "突破待确认")

    def test_buy_and_sell_points_are_structural_and_do_not_drift(self) -> None:
        closes = [50.0] * 40 + [48.0] * 39 + [49.0]
        a = compute_signals(closes, 49.0)
        b = compute_signals(closes, 49.6)

        # 买卖点等于结构位，且不随现价移动
        self.assertEqual(a["buy_point"], a["support"])
        self.assertEqual(a["sell_point"], a["resistance"])
        self.assertEqual(a["buy_point"], b["buy_point"])
        self.assertEqual(a["sell_point"], b["sell_point"])


if __name__ == "__main__":
    unittest.main()
