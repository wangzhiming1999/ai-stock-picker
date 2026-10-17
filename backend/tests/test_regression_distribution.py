"""回归/影子策略的分布读数测试。

## 为什么突然加分布

`recommend_regression_service._metrics` 原来只输出 `avg_excess_return`（均值）。
但**均值可以被少数极端样本撑起来**：一组 selections 里若靠几个暴涨窗口
拉高平均，`avg > 0` 就让 `shadow_strategy` 的 blocker 检查通过，
而典型的那一次其实是亏的 —— 界面上完全看不出来。

`shadow_strategy` 原有 5 条 blocker（样本数 / 提升幅度 / 超额为正 /
超过基线 / 窗口稳定）都只看均值与胜率，**没有一维在看分布**。

## 分位数实现踩过的坑（值得记）

第一版用 `ordered[int(len*q)]` 取最近秩。它在大样本上「看起来对」，
但 **n 较小时索引会撞上末位**：n=7 时 `int(7*0.95)=6` 正好是最后一个元素，
于是把那个孤立的 +100 当成 p95 = 100.0，而真实 p95 只有 69.7。

这是最坏的一类错：**单点样本被当成尾部代表**，方向还往乐观那边偏 ——
恰好掩盖了「收益靠孤例」这个最该被看见的问题。

（排查时我一度以为是 n=31 的越界，实测 `[-1]*30+[100]` 下 `int(31*0.95)=29`
落在 −1 上，与 numpy 一致，并不是 bug。**真正的错在索引撞末位。**
教训：验证分位数实现要对**多个 n** 交叉核对 numpy，只试一个 n 很容易把对的当错的。）

改成线性插值（与 `numpy.percentile` 默认口径一致）后无此问题。
本文件用 numpy 交叉核对 7 组数据，把口径钉死。
"""
from __future__ import annotations

import math
from statistics import mean, median

import numpy as np
import pytest

from app.services import calibers
from app.services import recommend_regression_service as rrs
from app.services import shadow_strategy_service as shs


def _m(values: list[float]) -> dict:
    return rrs._metrics([{"excess_return": v} for v in values])


class TestPercentile:
    """`_percentile` 必须与 numpy.percentile 同口径（线性插值）。"""

    @pytest.mark.parametrize(
        "values",
        [
            [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
            [5.0],
            [-3.0, 0.0, 0.0, 0.0, 7.0],
            [2.0, 2.0],
            [0.0] * 7,
            list(range(101)),
        ],
    )
    def test_matches_numpy_default(self, values: list[float]) -> None:
        ordered = sorted(values)
        assert rrs._percentile(ordered, 0.05) == pytest.approx(np.percentile(values, 5))
        assert rrs._percentile(ordered, 0.95) == pytest.approx(np.percentile(values, 95))

    def test_nearest_rank_never_promotes_a_single_sample_to_p95(self) -> None:
        """回归：6 个 −1 + 1 个 +100（n=7）。

        第一版用 `ordered[int(len*q)]` 取最近秩：
        `int(7*0.95)=6` 正好落在**最后一个元素**上，于是把那个孤立的 +100
        当成 p95 = 100.0，而真实的 p95 只有 69.7。

        这是最坏的一类错：**单点样本被当成尾部代表**，
        方向还是往乐观那边偏 —— 恰好掩盖了「收益靠孤例」这个最该被看见的问题。

        （顺带澄清：n=31 那组 `[-1]*30+[100]` 下 `int(31*0.95)=29` 落在 −1 上，
        与 numpy 一致，并不是 bug。真正的错在 n 较小、索引撞上末位时。）
        """
        values = [-1.0] * 6 + [100.0]
        ordered = sorted(values)

        assert len(ordered) == 7
        # 朴素最近秩会取到末位
        assert ordered[int(len(ordered) * 0.95)] == 100.0
        # 线性插值给出真实分位
        p95 = rrs._percentile(ordered, 0.95)
        assert p95 == pytest.approx(69.7)
        assert p95 == pytest.approx(np.percentile(values, 95))
        assert p95 < 100.0

    def test_single_value_returns_itself(self) -> None:
        assert rrs._percentile([3.3], 0.05) == 3.3
        assert rrs._percentile([3.3], 0.95) == 3.3

    def test_empty_is_rejected_loudly(self) -> None:
        """空序列必须抛错 —— 返回 0 会被读成「p05 = 0%」这个具体结论。"""
        with pytest.raises(ValueError):
            rrs._percentile([], 0.05)


class TestMetricsDistribution:
    def test_median_is_the_distribution_anchor(self) -> None:
        result = _m([1.0] * 19 + [40.0])

        assert result["median_excess_return"] == 1.0
        # 均值被拉高到 2.95 —— 这正是需要中位数的原因
        assert result["avg_excess_return"] == pytest.approx(2.95)

    def test_all_distribution_fields_present(self) -> None:
        result = _m([0.5, -0.2, 1.1, 0.3])

        assert result["selections"] == 4
        assert result["median_excess_return"] == pytest.approx(median([0.5, -0.2, 1.1, 0.3]))
        assert result["p05_excess_return"] == pytest.approx(np.percentile([0.5, -0.2, 1.1, 0.3], 5))
        assert result["p95_excess_return"] == pytest.approx(np.percentile([0.5, -0.2, 1.1, 0.3], 95))

    def test_empty_sample_is_all_none_not_zero(self) -> None:
        """空样本全部 None —— 返回 0 会把「没数据」读成「超额为 0%」。"""
        result = _m([])

        assert result["selections"] == 0
        for key in ("hit_rate", "avg_excess_return", "median_excess_return",
                    "p05_excess_return", "p95_excess_return"):
            assert result[key] is None, key

    def test_raw_values_are_not_exposed(self) -> None:
        """不下发原始序列 —— 分布特征（3 个数）已够复核，避免响应体膨胀。"""
        result = _m([1.0, 2.0, 3.0])

        assert "values" not in result
        assert "samples" not in result


class TestShadowFourQuestions:
    """影子策略接四问：补上「分布」这一维。"""

    def _candidate(self, **kw) -> dict:
        metrics = kw.get("metrics") or {}
        baseline = kw.get("baseline") or {}
        return shs.assess_shadow_candidate(
            key="k",
            label="候选组",
            metrics=metrics,
            baseline=baseline,
            windows=kw.get("windows", []),
            evidence_ready=kw.get("evidence_ready", True),
            min_oos_selections=kw.get("min_oos_selections", 60),
        )

    def test_distribution_is_the_missing_dimension(self) -> None:
        """均值被极端值撑高、中位数为负 ⇒ 四问必须判分布不过。

        同样的数据在旧版只有 `avg > 0` 一条判据，会通过 blocker 检查。
        """
        report = self._candidate(
            metrics={"selections": 100, "hit_rate": 70.0, "avg_excess_return": 2.0,
                     "median_excess_return": -0.4},
            baseline={"hit_rate": 50.0, "avg_excess_return": 0.5},
        )
        items = {i["key"]: i for i in report["four_questions"]["items"]}

        assert items["median"]["answered"] is True
        assert items["median"]["passed"] is False
        assert report["four_questions"]["verdict"] == "inflated"
        assert "median" in report["four_questions"]["failed_keys"]

    def test_clean_distribution_passes(self) -> None:
        report = self._candidate(
            metrics={"selections": 100, "hit_rate": 70.0, "avg_excess_return": 1.2,
                     "median_excess_return": 1.1},
            baseline={"hit_rate": 50.0, "avg_excess_return": 0.5},
        )
        items = {i["key"]: i for i in report["four_questions"]["items"]}

        assert items["median"]["passed"] is True
        assert items["benchmark_sign"]["passed"] is True

    def test_sign_question_maps_to_baseline_comparison(self) -> None:
        """第四问映射为「是否超过同窗口基线」（语义替代符号翻转）。"""
        below = self._candidate(
            metrics={"selections": 100, "hit_rate": 60.0, "avg_excess_return": 0.3,
                     "median_excess_return": 0.3},
            baseline={"hit_rate": 50.0, "avg_excess_return": 0.8},
        )
        items = {i["key"]: i for i in below["four_questions"]["items"]}

        assert items["benchmark_sign"]["passed"] is False
        assert "基线" in items["benchmark_sign"]["value"]
        assert "贝塔" not in items["benchmark_sign"]["detail"]

    def test_sample_threshold_note_refuses_the_module_threshold(self) -> None:
        """n 用本模块更严的门槛（60），不是四问通用的 30。"""
        report = self._candidate(
            metrics={"selections": 40, "hit_rate": 60.0, "avg_excess_return": 1.0,
                     "median_excess_return": 1.0},
            baseline={"hit_rate": 50.0, "avg_excess_return": 0.3},
            min_oos_selections=60,
        )
        detail = {i["key"]: i for i in report["four_questions"]["items"]}["sample"]["detail"]

        assert "40" in detail
        assert "60" in detail
        assert str(calibers.MIN_SAMPLE) in detail   # 也点明通用门槛更低

    def test_tradable_is_unanswered_not_faked(self) -> None:
        report = self._candidate(
            metrics={"selections": 100, "hit_rate": 70.0, "avg_excess_return": 1.2,
                     "median_excess_return": 1.1},
            baseline={"hit_rate": 50.0, "avg_excess_return": 0.5},
        )
        item = {i["key"]: i for i in report["four_questions"]["items"]}["tradable"]

        assert item["answered"] is False
        assert item["passed"] is None

    def test_four_questions_do_not_change_eligibility(self) -> None:
        """⚠️ 四问是**补充闸**，不得改变 promotion_eligible。

        它的职责是「这个数字站不站得住」，而准入是证据链的事。
        两者混在一起会让任何一次口径调整都能悄悄改变准入判定。
        """
        # 均值被极端值撑高、中位数为负 ⇒ 四问 inflated，但 blocker 规则不变
        report = self._candidate(
            metrics={"selections": 100, "hit_rate": 70.0, "avg_excess_return": 2.0,
                     "median_excess_return": -0.4},
            baseline={"hit_rate": 50.0, "avg_excess_return": 0.5},
            windows=[{"hit_rate_win": True, "return_win": True}] * 3,
        )

        assert report["four_questions"]["verdict"] == "inflated"
        # 既有 blocker 规则里没有分布这一条，所以 eligible 仍按旧规则算
        assert report["promotion_eligible"] is True
