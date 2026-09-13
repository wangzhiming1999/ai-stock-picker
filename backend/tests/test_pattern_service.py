"""实战形态规则引擎测试：每条技巧的命中/不命中/数据不足三种路径。"""
import datetime as dt
import unittest

from app.models import StockHistory
from app.services import pattern_service as ps


def _dates(n: int, start: dt.date = dt.date(2024, 1, 1)) -> list[str]:
    return [(start + dt.timedelta(days=i)).isoformat() for i in range(n)]


def _hist(closes, opens=None, highs=None, lows=None, volumes=None) -> StockHistory:
    n = len(closes)
    return StockHistory(
        dates=_dates(n),
        closes=list(closes),
        volumes=list(volumes) if volumes is not None else [1000.0] * n,
        opens=list(opens) if opens is not None else list(closes),
        highs=list(highs) if highs is not None else list(closes),
        lows=list(lows) if lows is not None else list(closes),
    )


class IndicatorHelperTests(unittest.TestCase):
    def test_macd_series_needs_enough_bars(self) -> None:
        self.assertIsNone(ps.macd_series([10.0] * 30))
        self.assertIsNotNone(ps.macd_series([10.0 + i * 0.1 for i in range(60)]))

    def test_cross_recently_detects_golden_cross(self) -> None:
        dif = [0.0, -0.2, -0.1, 0.1, 0.3]
        dea = [0.0, -0.1, -0.05, 0.0, 0.1]
        self.assertTrue(ps._cross_recently(dif, dea, 3))

    def test_cross_recently_ignores_stale_cross(self) -> None:
        dif = [0.0, -0.1, 0.2, 0.3, 0.4]
        dea = [0.0, 0.0, 0.1, 0.2, 0.3]
        self.assertFalse(ps._cross_recently(dif, dea, 2))

    def test_resample_monthly_takes_last_close(self) -> None:
        dates = ["2026-01-05", "2026-01-20", "2026-02-03", "2026-02-27", "2026-03-02"]
        closes = [1.0, 2.0, 3.0, 4.0, 5.0]
        self.assertEqual(ps._resample_closes(dates, closes, "M"), [2.0, 4.0, 5.0])

    def test_resample_weekly_groups_by_iso_week(self) -> None:
        dates = ["2026-01-05", "2026-01-09", "2026-01-12"]
        closes = [1.0, 2.0, 3.0]
        self.assertEqual(ps._resample_closes(dates, closes, "W"), [2.0, 3.0])


class CycleResonanceTests(unittest.TestCase):
    def test_requires_long_history(self) -> None:
        result = ps.detect_cycle_resonance({"daily": _hist([10.0] * 100)})

        self.assertEqual(result["status"], "insufficient_data")
        self.assertFalse(result["matched"])

    def test_marks_higher_timeframe_unavailable_when_short(self) -> None:
        # 250~700 根：日线/周线可算，月线不足 35 根
        result = ps.detect_cycle_resonance({"daily": _hist([10.0] * 300)})

        self.assertEqual(result["total"], 3)
        self.assertFalse(result["matched"])
        monthly = result["conditions"][2]
        self.assertFalse(monthly["available"])


class GuillotineTests(unittest.TestCase):
    def test_detects_ma_convergence_breakdown(self) -> None:
        closes = [10.0] * 21 + [9.4]
        opens = [10.0] * 21 + [10.0]
        highs = [10.0] * 21 + [10.05]
        lows = [10.0] * 21 + [9.3]
        result = ps.detect_guillotine({"daily": _hist(closes, opens, highs, lows), "price": 9.4})

        self.assertTrue(result["matched"])
        self.assertEqual(result["status"], "matched")
        self.assertIn("减仓", result["action"])

    def test_small_drop_does_not_match(self) -> None:
        closes = [10.0] * 21 + [9.8]
        result = ps.detect_guillotine({"daily": _hist(closes), "price": 9.8})

        self.assertFalse(result["matched"])
        self.assertFalse(result["conditions"][2]["passed"])

    def test_insufficient_history(self) -> None:
        result = ps.detect_guillotine({"daily": _hist([10.0] * 10)})

        self.assertEqual(result["status"], "insufficient_data")


class WashScrubTests(unittest.TestCase):
    def _build(self):
        closes = [round(9.0 + i * 0.1, 2) for i in range(25)]
        opens, highs, lows = list(closes), list(closes), list(closes)
        # 第 1 根：长上影冲高回落
        closes.append(11.1); opens.append(11.0); highs.append(12.0); lows.append(10.9)
        # 第 2 根：长下影探底回升，实体与第 1 根接近
        closes.append(10.9); opens.append(11.0); highs.append(11.2); lows.append(10.0)
        # 突破上影高点
        closes.append(12.4); opens.append(11.0); highs.append(12.5); lows.append(10.95)
        return _hist(closes, opens, highs, lows), closes[-1]

    def test_detects_scrub_line_with_breakout(self) -> None:
        daily, price = self._build()

        result = ps.detect_wash_scrub({"daily": daily, "price": price})

        self.assertTrue(result["matched"])
        self.assertEqual(result["total"], 5)
        self.assertTrue(all(c["passed"] for c in result["conditions"]))

    def test_scrub_without_breakout_is_watch(self) -> None:
        closes = [round(9.0 + i * 0.1, 2) for i in range(25)]
        opens, highs, lows = list(closes), list(closes), list(closes)
        closes.append(11.1); opens.append(11.0); highs.append(12.0); lows.append(10.9)
        closes.append(10.9); opens.append(11.0); highs.append(11.2); lows.append(10.0)

        result = ps.detect_wash_scrub({"daily": _hist(closes, opens, highs, lows), "price": closes[-1]})

        self.assertFalse(result["matched"])
        self.assertEqual(result["status"], "watch")
        self.assertIn("加仓点", result["action"])

    def test_missing_ohlc_is_insufficient(self) -> None:
        near = StockHistory(dates=_dates(30), closes=[10.0] * 30, volumes=[100.0] * 30)

        result = ps.detect_wash_scrub({"daily": near, "price": 10.0})

        self.assertEqual(result["status"], "insufficient_data")


class VolumeFloorTests(unittest.TestCase):
    def test_detects_capitulation_then_volume_confirmation(self) -> None:
        n = 70
        closes = [round(20.0 - i * 0.1, 2) for i in range(62)]
        closes += [13.85, 13.9, 13.95, 14.0, 14.05, 14.1, 14.15, 14.2]
        volumes = [1000.0] * n
        volumes[62] = 150.0     # 地量（前期均量 15%）
        volumes[63] = 400.0     # 3 日内放量 2 倍以上
        result = ps.detect_volume_floor({"daily": _hist(closes, volumes=volumes)})

        self.assertTrue(result["matched"])
        self.assertIn("买点", result["action"])

    def test_floor_without_confirmation_is_watch(self) -> None:
        n = 70
        closes = [round(20.0 - i * 0.1, 2) for i in range(62)]
        closes += [13.85, 13.8, 13.75, 13.7, 13.65, 13.6, 13.55, 13.5]
        volumes = [1000.0] * n
        volumes[62] = 150.0
        result = ps.detect_volume_floor({"daily": _hist(closes, volumes=volumes)})

        self.assertFalse(result["matched"])
        self.assertEqual(result["status"], "watch")

    def test_flat_market_is_not_a_floor(self) -> None:
        result = ps.detect_volume_floor({"daily": _hist([10.0] * 80)})

        self.assertFalse(result["matched"])
        self.assertFalse(result["conditions"][0]["passed"])


class VolumePeakTests(unittest.TestCase):
    def test_detects_blowoff_top(self) -> None:
        n = 70
        closes = [10.0] * 40 + [round(10.0 + (i - 39) * 0.22, 2) for i in range(40, n)]
        volumes = [1000.0] * n
        volumes[-1] = 5000.0
        result = ps.detect_volume_peak({"daily": _hist(closes, volumes=volumes), "turnover": 35.0})

        self.assertTrue(result["matched"])
        self.assertIn("减半仓", result["action"])

    def test_no_surge_no_signal(self) -> None:
        n = 70
        closes = [10.0] * 69 + [10.5]
        volumes = [1000.0] * 69 + [5000.0]
        result = ps.detect_volume_peak({"daily": _hist(closes, volumes=volumes), "turnover": 35.0})

        self.assertFalse(result["matched"])
        self.assertFalse(result["conditions"][0]["passed"])

    def test_missing_turnover_does_not_block(self) -> None:
        n = 70
        closes = [10.0] * 40 + [round(10.0 + (i - 39) * 0.22, 2) for i in range(40, n)]
        volumes = [1000.0] * n
        volumes[-1] = 5000.0
        result = ps.detect_volume_peak({"daily": _hist(closes, volumes=volumes), "turnover": None})

        self.assertTrue(result["matched"])
        self.assertFalse(result["conditions"][2]["available"])


class IntradayDivergenceTests(unittest.TestCase):
    def test_detects_top_divergence(self) -> None:
        prev = [10.0] * 30
        today = [10.0, 10.25, 10.5, 10.75, 11.0] + [10.6] * 20 + [10.6, 10.7, 10.85, 10.95, 11.05]
        closes = prev + today
        dates = [f"20260908{930 + i:04d}" for i in range(30)] + [
            f"20260909{930 + i:04d}" for i in range(len(today))
        ]
        hist = StockHistory(dates=dates, closes=closes, volumes=[100.0] * len(closes))

        result = ps.detect_intraday_divergence({"intraday": hist, "price": closes[-1]})

        self.assertTrue(result["matched"])
        self.assertEqual(result["conditions"][1]["name"], "MACD 未同步创新高（顶背离）")
        self.assertIn("止盈", result["action"])

    def test_insufficient_intraday_bars(self) -> None:
        hist = StockHistory(dates=_dates(20), closes=[10.0] * 20, volumes=[100.0] * 20)

        result = ps.detect_intraday_divergence({"intraday": hist, "price": 10.0})

        self.assertEqual(result["status"], "insufficient_data")


class RegistryTests(unittest.TestCase):
    def test_all_tactics_have_detector(self) -> None:
        keys = {t["key"] for t in ps.TACTICS}
        self.assertEqual(keys, set(ps.DETECTORS))

    def test_check_one_isolates_detector_failure(self) -> None:
        # daily=None 时每个 detector 都应走 insufficient，而不是抛异常
        results = ps.check_one({"daily": None, "intraday": None, "price": None})

        self.assertEqual(len(results), len(ps.TACTICS))
        self.assertTrue(all(r["matched"] is False for r in results))

    def test_list_tactics_shape(self) -> None:
        items = ps.list_tactics()

        self.assertEqual(len(items), 6)
        self.assertEqual({i["direction"] for i in items}, {"buy", "sell"})
        self.assertTrue(all({"key", "name", "category", "desc"} <= set(i) for i in items))


if __name__ == "__main__":
    unittest.main()
