"""市场状态识别与方向分合成的回归测试。

重点覆盖「方向为什么变稳」这件事本身：
- 状态分是连续量、始终在 0-10
- 方向标签由分数决定（中间带就是震荡），不再由关键词猜
- LLM 分的影响力被硬性限制在 ±0.5
- 惯性平滑禁止单日方向翻转
"""
import math
import random
import unittest

from app.services import regime_service as rs


def _series(start: float, daily_pct: float, days: int, seed: int = 7, noise: float = 0.004) -> list[float]:
    """带噪声的趋势序列。噪声是必要的 —— 完全无噪声的等比序列会让所有特征变成常数，
    HMM 无法区分状态；同时用固定 seed 保证可复现。"""
    rng = random.Random(seed)
    out: list[float] = []
    price = start
    for _ in range(days):
        out.append(round(price, 2))
        price *= 1 + daily_pct + rng.uniform(-noise, noise)
    return out


class ScoreToDirectionTests(unittest.TestCase):
    def test_thresholds_are_inclusive_on_both_sides(self) -> None:
        self.assertEqual(rs.score_to_direction(8.0), "上涨")
        self.assertEqual(rs.score_to_direction(rs.SCORE_UP), "上涨")
        self.assertEqual(rs.score_to_direction(5.0), "震荡")
        self.assertEqual(rs.score_to_direction(rs.SCORE_DOWN), "下跌")
        self.assertEqual(rs.score_to_direction(1.0), "下跌")

    def test_missing_score_falls_back_to_neutral(self) -> None:
        self.assertEqual(rs.score_to_direction(None), "震荡")

    def test_state_vocabulary_tracks_direction_vocabulary(self) -> None:
        """市场状态词表（上行/下行）与方向词表（上涨/下跌）必须同源同阈值。"""
        pairs = {
            "上涨": "上行",
            "震荡": "震荡",
            "下跌": "下行",
        }
        for score in [x / 10 for x in range(0, 101)]:
            self.assertEqual(
                rs.state_of_score(score), pairs[rs.score_to_direction(score)], msg=f"score={score}"
            )


class RuleRegimeTests(unittest.TestCase):
    def test_flat_market_scores_exactly_neutral(self) -> None:
        regime = rs._rule_regime([3000.0] * 180)

        self.assertEqual(regime["method"], "rule")
        self.assertEqual(regime["state"], "震荡")
        self.assertEqual(regime["regime_score"], rs.NEUTRAL_SCORE)

    def test_score_is_monotonic_in_trend_direction(self) -> None:
        flat = rs._rule_regime([3000.0] * 180)["regime_score"]
        up = rs._rule_regime(_series(3000, 0.004, 180))["regime_score"]
        down = rs._rule_regime(_series(4000, -0.004, 180))["regime_score"]

        self.assertGreater(up, flat)
        self.assertGreater(flat, down)


class ComputeRegimeTests(unittest.TestCase):
    def test_uptrend_is_classified_up(self) -> None:
        regime = rs.compute_regime(_series(3000, 0.004, 180), [1e8] * 180)

        self.assertEqual(regime["state"], "上行")
        self.assertGreater(regime["regime_score"], 6.0)
        self.assertIn(regime["method"], ("rule", "rule+hmm"))

    def test_downtrend_is_classified_down(self) -> None:
        regime = rs.compute_regime(_series(4000, -0.004, 180), [1e8] * 180)

        self.assertEqual(regime["state"], "下行")
        self.assertLess(regime["regime_score"], 4.0)

    def test_score_is_always_within_range(self) -> None:
        for daily in (-0.01, -0.002, 0.0, 0.002, 0.01):
            regime = rs.compute_regime(_series(3000, daily, 180))
            self.assertGreaterEqual(regime["regime_score"], 0.0)
            self.assertLessEqual(regime["regime_score"], 10.0)

    def test_insufficient_history_returns_neutral_without_raising(self) -> None:
        regime = rs.compute_regime([3000, 3010, 3020])

        self.assertEqual(regime["method"], "neutral")
        self.assertEqual(regime["state"], "震荡")
        self.assertEqual(regime["regime_score"], rs.NEUTRAL_SCORE)

    def test_empty_history_returns_neutral(self) -> None:
        self.assertEqual(rs.compute_regime([])["method"], "neutral")


def _multi_regime(phases: list[float], days: int = 70, seed: int = 19) -> list[float]:
    """三段式行情（每段一个 regime），贴近真实指数历史的多 regime 结构。"""
    rng = random.Random(seed)
    out: list[float] = []
    price = 3000.0
    for daily in phases:
        for _ in range(days):
            out.append(round(price, 2))
            price *= 1 + daily + rng.uniform(-0.004, 0.004)
    return out


class MultiRegimeTests(unittest.TestCase):
    """HMM 曾把单边下跌判成「上行」，这里把多 regime 场景固化成回归防线。

    实测（2026-09）：确定性规则 7/7 判对，HMM 单次拟合只有 3/7 —— 因此主判据是
    规则，HMM 只做一致性交叉验证。下面同时断言最终标签与 HMM 的独立意见，
    防止将来有人又把 HMM 提回主判据。
    """

    CASES = [
        ([0.005, 0.0, -0.005], "下行"),
        ([0.0, -0.005, 0.005], "上行"),
        ([0.005, -0.005, 0.0], "震荡"),
        ([0.005, -0.005, 0.004], "上行"),
        ([-0.005, 0.0, -0.004], "下行"),
    ]

    def test_last_phase_state_is_correct(self) -> None:
        for phases, expected in self.CASES:
            with self.subTest(phases=phases):
                regime = rs.compute_regime(_multi_regime(phases), [1e8] * 210)
                self.assertEqual(regime["state"], expected)

    def test_label_always_matches_the_score(self) -> None:
        for phases, _ in self.CASES:
            with self.subTest(phases=phases):
                regime = rs.compute_regime(_multi_regime(phases), [1e8] * 210)
                self.assertEqual(rs.state_of_score(regime["regime_score"]), regime["state"])

    def test_hmm_opinion_is_recorded_even_when_overruled(self) -> None:
        for phases, _ in self.CASES:
            with self.subTest(phases=phases):
                regime = rs.compute_regime(_multi_regime(phases), [1e8] * 210)
                self.assertIn("hmm_state", regime)
                if regime["method"] == "rule+hmm":
                    self.assertEqual(regime["hmm_state"], regime["state"])
                    self.assertIsNotNone(regime["state_persistence"])
                else:
                    # 不一致时必须留下 HMM 的意见与说明，便于复核
                    self.assertIsNotNone(regime["note"])

    def test_single_regime_history_falls_back_to_rule(self) -> None:
        """整段历史只有一个 regime 时 HMM 会退化成吸收态，必须降级而不是硬判。"""
        for daily in (0.004, -0.004):
            with self.subTest(daily=daily):
                regime = rs.compute_regime(_series(3000, daily, 180), [1e8] * 180)
                self.assertEqual(regime["method"], "rule")
                self.assertIsNone(regime["hmm_state"])


class BreadthTests(unittest.TestCase):
    def test_counts_ratio_limits_and_turnover(self) -> None:
        rows = [
            {"code": "600000", "change_pct": 10.0, "amount_yi": 10.0},   # 主板涨停
            {"code": "000001", "change_pct": 3.0, "amount_yi": 20.0},
            {"code": "300001", "change_pct": -20.0, "amount_yi": 5.0},   # 创业板 20cm 跌停
            {"code": "600001", "change_pct": -1.0, "amount_yi": 15.0},
            {"code": "830001", "change_pct": 30.0, "amount_yi": 999.0},  # 北交所：剔除
            {"code": "600002", "change_pct": None, "amount_yi": 1.0},    # 脏数据：剔除
        ]

        breadth = rs.compute_breadth(rows, prev_amount_yi=50.0)

        self.assertIsNotNone(breadth)
        self.assertEqual(breadth["up_count"], 2)
        self.assertEqual(breadth["down_count"], 2)
        self.assertEqual(breadth["limit_up_count"], 1)
        self.assertEqual(breadth["limit_down_count"], 1)
        # 北交所 999 亿不计入，缺失涨跌幅的行也不计入
        self.assertEqual(breadth["total_amount_yi"], 50.0)
        self.assertEqual(breadth["up_down_ratio"], 0.5)
        self.assertEqual(breadth["amount_change_pct"], 0.0)
        self.assertEqual(breadth["breadth_score"], rs.NEUTRAL_SCORE)

    def test_bullish_breadth_scores_above_neutral(self) -> None:
        rows = [{"code": f"60{i:04d}", "change_pct": 2.0, "amount_yi": 10.0} for i in range(8)]
        rows += [{"code": f"00{i:04d}", "change_pct": -2.0, "amount_yi": 10.0} for i in range(2)]

        breadth = rs.compute_breadth(rows)

        self.assertIsNotNone(breadth)
        self.assertAlmostEqual(breadth["up_down_ratio"], 0.8, places=3)
        self.assertGreater(breadth["breadth_score"], 7.0)

    def test_bearish_breadth_scores_below_neutral(self) -> None:
        rows = [{"code": f"60{i:04d}", "change_pct": -2.0, "amount_yi": 10.0} for i in range(8)]
        rows += [{"code": f"00{i:04d}", "change_pct": 2.0, "amount_yi": 10.0} for i in range(2)]

        breadth = rs.compute_breadth(rows)

        self.assertIsNotNone(breadth)
        self.assertLess(breadth["breadth_score"], 3.0)

    def test_missing_turnover_leaves_amount_change_none(self) -> None:
        rows = [{"code": "600000", "change_pct": 1.0, "amount_yi": 10.0}]

        breadth = rs.compute_breadth(rows)

        self.assertIsNotNone(breadth)
        self.assertIsNone(breadth["amount_change_pct"])

    def test_degenerate_inputs_return_none(self) -> None:
        self.assertIsNone(rs.compute_breadth([]))
        self.assertIsNone(rs.compute_breadth([{"code": "600000", "change_pct": None}]))


class BlendTests(unittest.TestCase):
    def test_breadth_only_tilts_a_little(self) -> None:
        # 宽度极端看多（10 分）时，对状态分的修正也被限制在 BREADTH_MAX_TILT 内
        self.assertAlmostEqual(
            rs.blend_evidence(5.0, 10.0), 5.0 + rs.BREADTH_MAX_TILT, places=2
        )
        self.assertAlmostEqual(
            rs.blend_evidence(5.0, 0.0), 5.0 - rs.BREADTH_MAX_TILT, places=2
        )

    def test_missing_breadth_keeps_regime_score(self) -> None:
        self.assertAlmostEqual(rs.blend_evidence(6.8, None), 6.8, places=2)

    def test_neutral_llm_score_does_not_move_the_needle(self) -> None:
        self.assertAlmostEqual(rs.blend_direction_score(6.0, 5.0), 6.0, places=2)
        self.assertEqual(rs.llm_contribution(5.0), 0.0)

    def test_llm_influence_is_capped_at_half_point(self) -> None:
        self.assertEqual(rs.llm_contribution(10.0), rs.LLM_MAX_ADJUST)
        self.assertEqual(rs.llm_contribution(0.0), -rs.LLM_MAX_ADJUST)
        # 截断点：0.3 × (x - 5) 达到 0.5 需要 x = 6.667
        self.assertLess(rs.llm_contribution(6.0), rs.LLM_MAX_ADJUST)
        # 超过截断点后，给 10.0 与给 7.0 的效果完全相同
        self.assertEqual(rs.llm_contribution(10.0), rs.llm_contribution(7.0))

    def test_missing_llm_score_is_treated_as_neutral(self) -> None:
        self.assertAlmostEqual(
            rs.blend_direction_score(5.0, None), rs.blend_direction_score(5.0, 5.0), places=2
        )

    def test_no_0_7_shrink_so_state_score_keeps_its_margin(self) -> None:
        """证据分原样传递：上行状态分 6.8 必须留在「上涨」带内，而不是被收缩到 6.26。"""
        score = rs.blend_direction_score(6.8, 5.0)

        self.assertAlmostEqual(score, 6.8, places=2)
        self.assertGreater(score - rs.SCORE_UP, 0.5)
        self.assertEqual(rs.score_to_direction(score), "上涨")


class ResolveDirectionTests(unittest.TestCase):
    def test_label_is_decided_by_evidence_only(self) -> None:
        # 证据分明确看空时，即使 LLM 打到满分、昨日是满分，标签也不能被翻成上涨
        direction, score = rs.resolve_direction(3.2, llm_score=10.0, prev_score=9.0)

        self.assertEqual(direction, "下跌")
        self.assertLessEqual(score, rs.SCORE_DOWN)

    def test_extreme_bearish_llm_cannot_flip_a_bullish_label(self) -> None:
        direction, score = rs.resolve_direction(6.8, llm_score=0.0, prev_score=1.0)

        self.assertEqual(direction, "上涨")
        self.assertGreaterEqual(score, rs.SCORE_UP)

    def test_score_always_matches_label(self) -> None:
        """分数与标签必须自洽：不能出现「方向=上涨」但分数落在震荡带的情况。"""
        for evidence in (1.0, 3.0, 3.8, 5.0, 6.2, 6.8, 9.0):
            for llm in (None, 0.0, 5.0, 10.0):
                for prev in (None, 2.0, 5.0, 8.0):
                    direction, score = rs.resolve_direction(evidence, llm, prev)
                    self.assertEqual(
                        rs.score_to_direction(score),
                        direction,
                        msg=f"evidence={evidence} llm={llm} prev={prev} -> {direction}/{score}",
                    )

    def test_evidence_5_stays_neutral(self) -> None:
        direction, score = rs.resolve_direction(5.0, llm_score=5.0)

        self.assertEqual(direction, "震荡")
        self.assertAlmostEqual(score, 5.0, places=2)

    def test_inertia_dampens_score_inside_the_same_band(self) -> None:
        # 同为「震荡」带：昨日 4.0，今日证据 5.0 → 平滑后 0.6×5.0 + 0.4×4.0 = 4.6
        direction, score = rs.resolve_direction(5.0, llm_score=5.0, prev_score=4.0)

        self.assertEqual(direction, "震荡")
        self.assertAlmostEqual(score, 4.6, places=2)

    def test_single_day_jump_is_capped_inside_a_band(self) -> None:
        # 带内：证据 6.0、昨日 3.9 → 平滑 5.16，相对昨日 +1.26 超限 → 收敛到 4.9
        direction, score = rs.resolve_direction(6.0, llm_score=5.0, prev_score=3.9)

        self.assertEqual(direction, "震荡")
        self.assertAlmostEqual(score, 4.9, places=2)

    def test_label_crossing_snaps_score_into_the_new_band(self) -> None:
        """证据分穿过阈值时，标签与分数一起切换 —— 真实切换不该被惯性掩盖。"""
        direction, score = rs.resolve_direction(6.8, llm_score=5.0, prev_score=3.0)

        self.assertEqual(direction, "上涨")
        self.assertGreaterEqual(score, rs.SCORE_UP)
        self.assertEqual(rs.score_to_direction(score), direction)


class InertiaTests(unittest.TestCase):
    def test_no_previous_score_returns_raw_value(self) -> None:
        self.assertAlmostEqual(rs.apply_inertia(6.26, None), 6.26, places=2)

    def test_smoothing_pulls_towards_previous_score(self) -> None:
        # 0.6*6.0 + 0.4*5.0 = 5.6
        self.assertAlmostEqual(rs.apply_inertia(6.0, 5.0), 5.6, places=2)

    def test_single_day_jump_is_capped(self) -> None:
        # 平滑后 0.6*6.8 + 0.4*3.2 = 5.36，相对昨日 +2.16 → 收敛到 3.2 + 1.0
        self.assertAlmostEqual(rs.apply_inertia(6.8, 3.2), 4.2, places=2)
        # 反向同理
        self.assertAlmostEqual(rs.apply_inertia(3.2, 6.8), 5.8, places=2)

    def test_small_change_is_not_capped(self) -> None:
        self.assertAlmostEqual(rs.apply_inertia(5.3, 5.0), 5.18, places=2)

    def test_result_is_clamped(self) -> None:
        self.assertLessEqual(rs.apply_inertia(10.0, 10.0), 10.0)
        self.assertGreaterEqual(rs.apply_inertia(0.0, 0.0), 0.0)


class FeatureTests(unittest.TestCase):
    def test_feature_matrix_alignment_and_shapes(self) -> None:
        closes = _series(3000, 0.002, 180)
        built = rs._build_features(closes, [1e8] * 180)

        self.assertIsNotNone(built)
        matrix, features = built
        # 前 20 根用于滚动窗口，观测序列从第 21 根起
        self.assertEqual(matrix.shape, (160, 5))
        self.assertIn("ret20_pct", features)
        self.assertIn("rsi14", features)
        self.assertTrue(all(math.isfinite(v) for v in matrix.flatten()))

    def test_short_history_returns_none(self) -> None:
        self.assertIsNone(rs._build_features([3000.0] * 80, None))

    def test_missing_volumes_are_tolerated(self) -> None:
        built = rs._build_features(_series(3000, 0.002, 180), None)

        self.assertIsNotNone(built)


if __name__ == "__main__":
    unittest.main()
