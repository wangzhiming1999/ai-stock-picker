"""形态回测与简报形态块的测试。

回测部分用合成 K 线（可精确控制形态是否出现），验证 walk-forward 的统计口径：
方向化胜率、基准对比、命中去重、不可回测项要明说。
"""
import datetime as dt
import unittest

from app.models import StockHistory
from app.services import tactic_backtest_service as bt
from app.services.briefing_service import _build_tactics_block


def _dates(n: int, start: dt.date = dt.date(2024, 1, 1)) -> list[str]:
    return [(start + dt.timedelta(days=i)).isoformat() for i in range(n)]


def _hist(closes, volumes=None) -> StockHistory:
    n = len(closes)
    return StockHistory(
        dates=_dates(n),
        closes=list(closes),
        volumes=list(volumes) if volumes is not None else [1000.0] * n,
        opens=list(closes),
        highs=list(closes),
        lows=list(closes),
    )


def _guillotine_history(blocks: int = 12) -> StockHistory:
    """每块 = 21 根均线粘合横盘 + 1 根 -6% 大阴线 + 6 根继续走弱。

    大阴线当日一定满足「均线粘合 + 跌破三线 + 跌幅 >5%」，用于验证回测统计。
    """
    closes, opens, highs, lows, volumes = [], [], [], [], []
    base = 20.0
    for _ in range(blocks):
        for _ in range(21):
            closes.append(base); opens.append(base); highs.append(base); lows.append(base)
            volumes.append(1000.0)
        drop = round(base * 0.94, 2)
        closes.append(drop); opens.append(base); highs.append(base); lows.append(drop)
        volumes.append(1500.0)
        for j in range(1, 7):
            px = round(base * (0.94 - 0.0133 * j), 2)
            closes.append(px); opens.append(px); highs.append(px); lows.append(px)
            volumes.append(800.0)
        base = round(base * 0.90, 2)
    return StockHistory(
        dates=_dates(len(closes)),
        closes=closes,
        volumes=volumes,
        opens=opens,
        highs=highs,
        lows=lows,
    )


class ForwardReturnTests(unittest.TestCase):
    def test_forward_return_and_path(self) -> None:
        closes = [10.0, 11.0, 12.0]

        ret, max_gain, max_dd = bt._forward(closes, 0, 2)

        # (持有收益, 期间最大浮盈, 期间最大浮亏)，均相对入场价
        self.assertAlmostEqual(ret, 20.0)
        self.assertAlmostEqual(max_gain, 20.0)
        self.assertAlmostEqual(max_dd, 10.0)

    def test_forward_returns_none_when_window_incomplete(self) -> None:
        self.assertIsNone(bt._forward([10.0, 11.0], 0, 5))


class PrefixTests(unittest.TestCase):
    def test_prefix_trims_every_series(self) -> None:
        hist = _hist(list(range(1, 31)))

        trimmed = bt._prefix(hist, 10)

        self.assertEqual(len(trimmed.closes), 10)
        self.assertEqual(trimmed.closes[-1], 10)
        self.assertEqual(len(trimmed.dates), 10)
        self.assertEqual(len(trimmed.opens), 10)
        self.assertEqual(len(trimmed.highs), 10)
        self.assertEqual(len(trimmed.lows), 10)
        self.assertEqual(len(trimmed.volumes), 10)


class EvaluateSyncTests(unittest.TestCase):
    def test_intraday_divergence_is_marked_not_backtestable(self) -> None:
        items = bt._evaluate_sync({}, ["intraday_divergence"], 10, 100)

        self.assertEqual(items[0]["status"], "not_backtestable")
        self.assertIn("分钟级", items[0]["note"])
        self.assertIsNone(items[0]["win_rate"])

    def test_guillotine_backtest_counts_signals_and_baseline(self) -> None:
        hist_map = {"600519": _guillotine_history()}

        items = bt._evaluate_sync(hist_map, ["guillotine"], 10, 400)
        item = items[0]

        # 12 块 → 12 次大阴线，落在评估区间内应 >= 8 次
        self.assertGreaterEqual(item["signals"], 8)
        self.assertEqual(item["status"], "ok")
        self.assertGreater(item["eval_points"], item["signals"])
        self.assertIsNotNone(item["baseline_win_rate"])
        self.assertIsNotNone(item["edge_win_rate"])
        self.assertTrue(item["by_stock"])

    def test_sell_tactic_win_definition_is_direction_aware(self) -> None:
        hist_map = {"600519": _guillotine_history()}

        item = bt._evaluate_sync(hist_map, ["guillotine"], 10, 400)[0]

        # 合成序列在大阴线后继续走弱 → 「下跌为胜」口径下胜率应偏高
        self.assertIn("下跌", item["win_definition"])
        self.assertGreater(item["win_rate"], 50)

    def test_flat_market_yields_insufficient_sample(self) -> None:
        flat = StockHistory(
            dates=_dates(300),
            closes=[10.0] * 300,
            volumes=[1000.0] * 300,
            opens=[10.0] * 300,
            highs=[10.0] * 300,
            lows=[10.0] * 300,
        )

        item = bt._evaluate_sync({"600519": flat}, ["wash_scrub"], 10, 250)[0]

        self.assertEqual(item["status"], "insufficient_data")
        self.assertEqual(item["signals"], 0)
        self.assertIsNone(item["win_rate"])

    def test_declining_only_marks_stocks_with_usable_history(self) -> None:
        hist_map = {"600519": _guillotine_history(), "000858": _hist([10.0] * 20)}

        item = bt._evaluate_sync(hist_map, ["guillotine"], 10, 250)[0]

        # 只有 20 根的第二只票不足 horizon + warmup，不应计入评估
        self.assertEqual(item["stocks_evaluated"], 1)


class BriefingTacticsBlockTests(unittest.TestCase):
    def test_no_hits_yields_empty_block(self) -> None:
        block = _build_tactics_block([{"code": "600519", "name": "贵州茅台", "tactics": []}], [])

        self.assertEqual(block["morning"], [])
        self.assertEqual(block["holdings"], [])
        self.assertIsNone(block["summary"])

    def test_collects_hits_with_summary(self) -> None:
        morning = [{"code": "600519", "name": "贵州茅台", "tactics": [{"key": "wash_scrub"}]}]
        holdings = [{"code": "000858", "name": "五粮液", "tactics": [{"key": "volume_peak"}]}]

        block = _build_tactics_block(morning, holdings)

        self.assertEqual(len(block["morning"]), 1)
        self.assertEqual(len(block["holdings"]), 1)
        self.assertIn("五粮液", block["summary"])
        self.assertIn("关注池 1 只", block["summary"])


if __name__ == "__main__":
    unittest.main()
