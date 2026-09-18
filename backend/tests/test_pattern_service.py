"""实战形态规则引擎测试：每条技巧的命中/不命中/数据不足三种路径。"""
import datetime as dt
import unittest

from app.models import StockHistory
from app.routes.analysis import _tail_history
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


def _v_shape(n: int, up: int = 3) -> list[float]:
    """浅跌 + 最后 3 根急拉的 V 形：MACD 金叉落在最后 3 根内，且价格全程为正。

    跌速取得很缓（0.05/根）是为了长序列也不会跌到 0 以下 ——
    负价格会让回测的前向收益直接判为无效样本。
    """
    vals = [100.0]
    for _ in range(n - up - 1):
        vals.append(vals[-1] - 0.05)
    for _ in range(up):
        vals.append(vals[-1] + 3.0)
    return vals


class CycleResonanceTests(unittest.TestCase):
    def test_requires_long_history(self) -> None:
        result = ps.detect_cycle_resonance({"daily": _hist([10.0] * 100)})

        self.assertEqual(result["status"], "insufficient_data")
        self.assertFalse(result["matched"])

    def test_marks_higher_timeframe_unavailable_when_short(self) -> None:
        # 只给日线：月线只能靠重采样，300 根日线重采样出的月线必然 < 35 根
        result = ps.detect_cycle_resonance({"daily": _hist([10.0] * 300)})

        self.assertEqual(result["total"], 3)
        self.assertFalse(result["matched"])
        monthly = result["conditions"][2]
        self.assertFalse(monthly["available"])

    def test_matches_when_all_three_periods_golden_cross(self) -> None:
        """三周期各自金叉 → 命中。这是改造前**不可能**出现的分支。

        改造前周线/月线由日线重采样得到，月线最多 ~33 根 < MACD 所需的 35 根，
        该技巧在任何股票上都只能返回 insufficient_data。
        """
        ctx = {
            "daily": _hist(_v_shape(120)),
            "week": _hist(_v_shape(60)),
            "month": _hist(_v_shape(40)),
        }

        result = ps.detect_cycle_resonance(ctx)

        self.assertTrue(result["matched"])
        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["passed"], 3)
        self.assertEqual(result["metrics"]["month_bars"], 40)
        # 三个周期都用了真实 K 线，没有一根是「重采样凑出来的」
        self.assertEqual([c["available"] for c in result["conditions"]], [True, True, True])

    def test_real_month_series_takes_precedence_over_resample(self) -> None:
        # 只有日线时月线不可用；补上真实月线后同一只票就能判定
        daily = _hist(_v_shape(120))
        without = ps.detect_cycle_resonance({"daily": daily, "week": _hist(_v_shape(60))})

        with_month = ps.detect_cycle_resonance(
            {"daily": daily, "week": _hist(_v_shape(60)), "month": _hist(_v_shape(40))}
        )

        self.assertFalse(without["conditions"][2]["available"])
        self.assertIn("重采样", without["conditions"][2]["detail"])
        self.assertTrue(with_month["conditions"][2]["available"])

    def test_short_real_month_series_reports_insufficient(self) -> None:
        ctx = {"daily": _hist(_v_shape(120)), "week": _hist(_v_shape(60)), "month": _hist(_v_shape(20))}

        result = ps.detect_cycle_resonance(ctx)

        self.assertFalse(result["matched"])
        monthly = result["conditions"][2]
        self.assertFalse(monthly["available"])
        self.assertIn("不足 35 根", monthly["detail"])


class PeriodDeclarationsTests(unittest.TestCase):
    def test_only_cycle_resonance_needs_extra_periods(self) -> None:
        self.assertEqual(ps.needed_periods(["cycle_resonance"]), ("week", "month"))
        self.assertEqual(ps.needed_periods(["guillotine", "wash_scrub"]), ())
        self.assertEqual(ps.needed_periods(["guillotine", "cycle_resonance"]), ("week", "month"))

    def test_default_keys_cover_every_declared_period(self) -> None:
        declared = {p for t in ps.TACTICS for p in t.get("extra_periods", ())}

        self.assertEqual(set(ps.needed_periods(None)), declared)

    def test_list_tactics_exposes_extra_periods(self) -> None:
        meta = {t["key"]: t for t in ps.list_tactics()}

        self.assertEqual(meta["cycle_resonance"]["extra_periods"], ["week", "month"])
        self.assertEqual(meta["guillotine"]["extra_periods"], [])

    def test_cycle_resonance_daily_warmup_matches_daily_requirement(self) -> None:
        """预热根数必须与判定口径一致，否则回测会静默跳过该技巧。"""
        tactic = ps.TACTIC_MAP["cycle_resonance"]

        self.assertEqual(tactic["warmup"], 60)
        self.assertLessEqual(tactic["warmup"], tactic["history_days"])
        self.assertTrue(ps.macd_series([10.0] * tactic["warmup"]) is not None)


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
        # 文案已从「至少减半仓」降级为风险提示口径（回测未显示显著超额）
        self.assertIn("分批减仓", result["action"])

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


class MacdZoneCrossTests(unittest.TestCase):
    def test_insufficient_history(self) -> None:
        result = ps.detect_macd_zone_cross({"daily": _hist([10.0] * 40)})

        self.assertEqual(result["status"], "insufficient_data")

    def test_flat_market_has_no_cross(self) -> None:
        result = ps.detect_macd_zone_cross({"daily": _hist([10.0] * 80)})

        self.assertFalse(result["matched"])
        self.assertFalse(result["conditions"][0]["passed"])

    def test_above_zero_cross_matches(self) -> None:
        # 单边上行时 DIF 必然在零轴上方；金叉用打桩控制，专注验证分区分支
        closes = [10.0 + i * 0.5 for i in range(80)]
        orig = ps._cross_recently
        ps._cross_recently = lambda dif, dea, lookback=3: True  # noqa: E731
        try:
            result = ps.detect_macd_zone_cross({"daily": _hist(closes), "price": closes[-1]})
        finally:
            ps._cross_recently = orig

        self.assertTrue(result["matched"])
        self.assertEqual(result["metrics"]["zone"], "above")

    def test_below_zero_cross_requires_volume(self) -> None:
        # 单边下行时 DIF < 0；零轴下方金叉必须放量（原文物 30%）才成立
        closes = [30.0 - i * 0.2 for i in range(80)]
        orig = ps._cross_recently
        ps._cross_recently = lambda dif, dea, lookback=3: True  # noqa: E731
        try:
            no_vol = ps.detect_macd_zone_cross(
                {"daily": _hist(closes, volumes=[1000.0] * 80), "price": closes[-1]}
            )
            spike = [1000.0] * 80
            spike[-1] = 2000.0
            with_vol = ps.detect_macd_zone_cross(
                {"daily": _hist(closes, volumes=spike), "price": closes[-1]}
            )
        finally:
            ps._cross_recently = orig

        self.assertFalse(no_vol["matched"])
        self.assertTrue(with_vol["matched"])
        self.assertEqual(with_vol["metrics"]["zone"], "below")


class Ma10BreakTests(unittest.TestCase):
    def test_detects_three_days_below_ma10(self) -> None:
        closes = [10.0] * 26 + [9.5, 9.0, 8.5]

        result = ps.detect_ma10_break({"daily": _hist(closes), "price": closes[-1]})

        self.assertTrue(result["matched"])
        self.assertIn("趋势走弱", result["action"])

    def test_two_days_below_is_not_enough(self) -> None:
        closes = [10.0] * 27 + [9.5, 9.0]

        result = ps.detect_ma10_break({"daily": _hist(closes), "price": closes[-1]})

        self.assertFalse(result["matched"])

    def test_already_below_is_not_a_break(self) -> None:
        # 一直贴在 MA10 下方，不属于「跌破后失守」
        closes = [10.0] * 20 + [9.0] * 9 + [8.5, 8.0, 7.5]

        result = ps.detect_ma10_break({"daily": _hist(closes), "price": closes[-1]})

        self.assertFalse(result["matched"])


class Ma20SlopeTests(unittest.TestCase):
    def test_golden_slope_matches(self) -> None:
        closes = [round(10.0 + i * 0.05, 4) for i in range(60)]

        result = ps.detect_ma20_slope({"daily": _hist(closes), "price": closes[-1]})

        self.assertTrue(result["matched"])
        self.assertGreaterEqual(result["metrics"]["slope"], 5.0)
        self.assertLessEqual(result["metrics"]["slope"], 20.0)

    def test_too_steep_is_fish_tail(self) -> None:
        closes = [round(10.0 + i * 0.3, 4) for i in range(60)]

        result = ps.detect_ma20_slope({"daily": _hist(closes), "price": closes[-1]})

        self.assertFalse(result["matched"])
        self.assertIn("鱼尾", result["action"])

    def test_flat_slope_does_not_match(self) -> None:
        result = ps.detect_ma20_slope({"daily": _hist([10.0] * 60)})

        self.assertFalse(result["matched"])
        self.assertIn("不在黄金区间", result["action"])


class RegistryTests(unittest.TestCase):
    def test_all_tactics_have_detector(self) -> None:
        """在册技巧必须有 detector；下线技巧的 detector 保留（回测可复用），反向不成立。"""
        keys = {t["key"] for t in ps.TACTICS}
        self.assertEqual(keys, set(ps.DETECTORS) - set(ps.RETIRED_TACTICS))

    def test_retired_tactics_are_out_of_registry_but_keep_detector(self) -> None:
        """下线技巧不进 TACTIC_MAP（扫描/面板不再出现），detect 函数保留供回测复用。"""
        self.assertEqual(set(ps.RETIRED_TACTICS) & set(ps.TACTIC_MAP), set())
        for key in ps.RETIRED_TACTICS:
            self.assertIn(key, ps.DETECTORS)

    def test_check_one_isolates_detector_failure(self) -> None:
        # daily=None 时每个 detector 都应走 insufficient，而不是抛异常
        results = ps.check_one({"daily": None, "intraday": None, "price": None})

        self.assertEqual(len(results), len(ps.TACTICS))
        self.assertTrue(all(r["matched"] is False for r in results))

    def test_list_tactics_shape(self) -> None:
        items = ps.list_tactics()

        # ma20_slope 已下线（2026-09-17）：9 → 8 条
        self.assertEqual(len(items), 8)
        self.assertEqual({i["direction"] for i in items}, {"buy", "sell"})
        self.assertTrue(all({"key", "name", "category", "desc"} <= set(i) for i in items))

    def test_matched_tactics_returns_only_hits(self) -> None:
        closes = [10.0] * 21 + [9.4]
        opens = [10.0] * 21 + [10.0]
        highs = [10.0] * 21 + [10.05]
        lows = [10.0] * 21 + [9.3]
        ctx = {"daily": _hist(closes, opens, highs, lows), "price": 9.4, "turnover": None}

        hits = ps.matched_tactics(ctx)

        self.assertTrue(hits)
        self.assertTrue(all(h["matched"] for h in hits))
        self.assertIn("guillotine", {h["key"] for h in hits})

    def test_matched_tactics_empty_when_nothing_hits(self) -> None:
        self.assertEqual(ps.matched_tactics({"daily": None, "price": None, "turnover": None}), [])


class AnalysisTailHistoryTests(unittest.TestCase):
    """深度分析卡用 900 根日线跑形态，但下游只允许拿到 260 根切片。"""

    def test_trims_all_series_together(self) -> None:
        hist = _hist(list(range(1, 101)))

        trimmed = _tail_history(hist, 10)

        self.assertEqual(len(trimmed.closes), 10)
        self.assertEqual(trimmed.closes[-1], 100)
        for series in (trimmed.dates, trimmed.opens, trimmed.highs, trimmed.lows, trimmed.volumes):
            self.assertEqual(len(series), 10)

    def test_short_series_returned_as_is(self) -> None:
        hist = _hist([10.0] * 5)

        self.assertIs(_tail_history(hist, 260), hist)

    def test_empty_history_returns_none(self) -> None:
        self.assertIsNone(_tail_history(None, 260))
        self.assertIsNone(_tail_history(StockHistory(dates=[], closes=[], volumes=None), 260))


if __name__ == "__main__":
    unittest.main()
