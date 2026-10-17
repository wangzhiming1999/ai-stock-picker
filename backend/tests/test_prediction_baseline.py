"""大盘方向预测的基线对照测试。

## 这个模块在解决什么

大盘方向预测是**三分类**（上涨/震荡/下跌），而「震荡」是方向分中间带
（`regime_service.SCORE_DOWN=3.8 ~ SCORE_UP=6.2`）的默认标签
—— 分数落在中间就输出震荡，所以**大多数日子它都输出震荡**。

而震荡恰好是三分类里最好蒙对一个的。实测线上 n=50：

| 标签 | n | 命中率 |
|---|---|---|
| 震荡 | 36 | 75.0% |
| 下跌 | 12 | 50.0% |
| 上涨 | 2 | 0.0% |
| **整体** | **50** | **66.0%** |

整体 66% 看着不错，但它几乎全由「震荡 75%」撑着，而后者主要反映
**「震荡日有多少天」**，不是「预测准不准」。**这个数字本身不含能力信息。**

所以本模块做两件事：
  1. `always_flat_rate` —— 朴素基线（无脑全猜震荡）= 震荡日占比
  2. `edge_over_baseline` —— 整体命中率减去基线，剩下的才是超出「无脑猜」的部分
  3. `directional_hit_rate` —— 剔除震荡后的方向命中率（真正在判断方向的样本）

## 三条不能违反的纪律

1. **基线只能用有 `actual_direction` 的行当分母**。
   老行缺该字段，若把它们算成「不是震荡」，基线会被压低、edge 虚高。
2. **不能用整体命中率顶替方向命中率**。方向子集通常小得可怜（实测 n=14），
   小就如实标小。
3. **edge ≤ 0 必须判不过**（映射到四问的 `benchmark_sign_flips`）。
   「还不如无脑猜震荡」是明确的失真，不能因为样本够就放过去。
"""
from __future__ import annotations

import pytest

from app.services import winrate_service as wr


def _rows(items: list[tuple[str, str, bool]]) -> list[dict]:
    """(预测方向, 实际方向, 是否命中) → 行"""
    return [
        {"direction": d, "actual_direction": a, "hit": h}
        for d, a, h in items
    ]


def _skill(items: list[tuple[str, str, bool]]) -> dict:
    return wr._prediction_skill(_rows(items))


class TestNaiveBaseline:
    def test_baseline_is_the_share_of_flat_days(self) -> None:
        """朴素基线 = **实际**为震荡的天数占比（无脑全猜震荡能蒙对多少）。"""
        # 10 天里实际 7 天是震荡（预测结果与是否命中都不影响基线）
        items = [("震荡", "震荡", True)] * 7 + [("下跌", "上涨", False)] * 3
        skill = _skill(items)

        assert skill["always_flat_rate"] == 70.0

    def test_baseline_counts_actual_not_predicted(self) -> None:
        """⚠️ 基线数的是 actual_direction，不是 direction。

        「无脑全猜震荡」的命中率 = 实际为震荡的天数 / 总天数。
        若错用预测标签来数，预测「震荡」的天数越多基线越高，
        会把自己的命中率也一起抬高 —— 等于用「我常猜震荡」给自己加分。
        """
        # 预测 8 次震荡，但实际只有 2 天是震荡（其余 8 天是非震荡）
        items = (
            [("震荡", "震荡", True)] * 2
            + [("震荡", "上涨", False)] * 6
            + [("震荡", "下跌", False)] * 2
        )
        skill = _skill(items)

        assert skill["always_flat_rate"] == 20.0   # 不是 80%

    def test_edge_subtracts_the_baseline(self) -> None:
        """edge = 整体命中率 − 基线。"""
        items = [("震荡", "震荡", True)] * 7 + [("下跌", "上涨", False)] * 3
        skill = _skill(items)

        # 整体 7/10 = 70.0%，基线 70.0% ⇒ edge 0.0
        assert skill["edge_over_baseline"] == 0.0

    def test_beating_the_baseline_gives_a_positive_edge(self) -> None:
        """震荡日并非全猜中时，才有超出基线的部分。

        ⚠️ 注意 `always_flat_rate` 数的是**实际为震荡的天数**，
        不是「预测为震荡的天数」—— 基线是「无脑全猜震荡」能蒙对多少，
        所以分母分子都取 actual_direction。混淆这两个是最容易写错的地方。
        """
        # 10 天：实际 4 天震荡（预测全对）、4 天上涨（猜对 3）、2 天下跌（猜错）
        items = (
            [("震荡", "震荡", True)] * 4
            + [("下跌", "上涨", True)] * 3
            + [("下跌", "上涨", False)] * 1
            + [("震荡", "下跌", False)] * 2
        )
        skill = _skill(items)

        assert skill["always_flat_rate"] == 40.0        # 实际 4/10 天是震荡
        assert skill["edge_over_baseline"] == 30.0      # 整体 70% − 40%

    def test_missing_actual_direction_rows_excluded_from_baseline_denominator(self) -> None:
        """⚠️ 老行缺 actual_direction，不能算成「不是震荡」——那会把基线压低、edge 虚高。

        这是本模块最容易写错的一处：分母必须只算「知道自己实际方向」的行。
        """
        # 4 行有 actual（3 天震荡），2 行没有
        items = [("震荡", "震荡", True)] * 3
        skill = wr._prediction_skill(
            [{"direction": d, "hit": h} for d, h in [("震荡", True), ("震荡", True)]]
            + _rows(items)
        )

        # 基线 = 3/3 = 100%（不是 3/5 = 60%）
        assert skill["always_flat_rate"] == 100.0
        assert skill["n"] == 5


class TestDirectionalRate:
    def test_directional_rate_excludes_flat_predictions(self) -> None:
        """方向命中率只在预测了上涨/下跌的日子上算。"""
        items = (
            [("震荡", "震荡", True)] * 36        # 震荡 36 天，全中
            + [("下跌", "下跌", True)] * 6        # 方向判断 6 次，中 3
            + [("下跌", "上涨", False)] * 3
            + [("上涨", "上涨", False)] * 2
        )
        skill = _skill(items)

        assert skill["directional_n"] == 11
        assert skill["directional_hit_rate"] == 54.5   # 6/11
        # 整体命中率很高，但方向子集小得多 —— 两者不可互相顶替
        assert skill["directional_sample_status"] == "insufficient"

    def test_never_directional_is_called_out_explicitly(self) -> None:
        """从未给过方向判断时，note 必须明说「无方向能力可评」。"""
        skill = _skill([("震荡", "震荡", True)] * 10)

        assert skill["directional_n"] == 0
        assert skill["directional_hit_rate"] is None
        assert "无方向能力可评" in skill["note"]

    def test_small_directional_sample_is_flagged_in_note(self) -> None:
        """方向子集不足 30 时 note 要说清，且不得给方向结论。"""
        items = [("下跌", "下跌", True)] * 8 + [("下跌", "上涨", False)] * 2
        skill = _skill(items)

        assert skill["directional_n"] == 10
        assert "需 ≥30 才判显著" in skill["note"]


class TestNotes:
    def test_no_edge_warns_loudly(self) -> None:
        """edge ≤ 0 时 note 必须说「不含可辨识的方向能力」，不能轻描淡写。"""
        items = [("震荡", "震荡", True)] * 8 + [("震荡", "上涨", False)] * 2
        note = _skill(items)["note"]

        assert "未超过" in note
        assert "不含可辨识的方向能力" in note

    def test_positive_edge_is_stated_plainly(self) -> None:
        items = (
            [("震荡", "震荡", True)] * 6
            + [("震荡", "上涨", False)] * 2
            + [("下跌", "下跌", True)] * 2
        )
        note = _skill(items)["note"]

        assert "高" in note and "个百分点" in note
        assert "不含可辨识" not in note


class TestEmptyAndEdgeCases:
    def test_empty_rows(self) -> None:
        skill = _skill([])

        assert skill["n"] == 0
        assert skill["always_flat_rate"] is None
        assert skill["edge_over_baseline"] is None
        assert skill["directional_n"] == 0
        assert skill["note"] is None

    def test_all_actual_direction_missing(self) -> None:
        """全部行都缺 actual_direction ⇒ 基线算不出（None），不是 0。"""
        skill = wr._prediction_skill([{"direction": "震荡", "hit": True} for _ in range(5)])

        assert skill["always_flat_rate"] is None
        assert skill["edge_over_baseline"] is None


class TestFourQuestionsIntegration:
    @pytest.mark.asyncio
    async def test_non_positive_edge_trips_the_fourth_question(self, monkeypatch) -> None:
        """edge ≤ 0 ⇒ 四问第四问判不通过。

        这是本模块与四问的接口：语义上它替代了「换基准符号翻转」——
        两者问的都是「命中是不是全靠大盘给的口粮」。
        """
        from types import SimpleNamespace

        class _Chain:
            def __init__(self, rows): self._rows = rows
            def __getattr__(self, _n): return self
            def __call__(self, *_a, **_k): return self
            async def execute(self): return SimpleNamespace(data=self._rows)

        class _Client:
            def table(self, name):
                data = {
                    # 8 天震荡全中 + 2 天非震荡猜错 ⇒ edge ≤ 0
                    "prediction_records": [
                        {"direction": "震荡", "actual_direction": "震荡", "hit": True} for _ in range(8)
                    ] + [
                        {"direction": "震荡", "actual_direction": "上涨", "hit": False} for _ in range(2)
                    ],
                    "daily_recommendations": [],
                    "winrate_snapshot": [],
                }
                return _Chain(data.get(name, []))

        async def _get():
            return _Client()

        monkeypatch.setattr(wr.supabase_store, "is_configured", lambda: True)
        monkeypatch.setattr(wr.supabase_store, "get_service_client", _get)

        stats = await wr.get_winrate_stats()
        pred = stats["prediction"]
        four = {i["key"]: i for i in pred["four_questions"]["items"]}

        assert pred["hit_rate"] == 80.0
        assert pred["baseline_comparison"]["edge_over_baseline"] == 0.0
        assert four["benchmark_sign"]["answered"] is True
        assert four["benchmark_sign"]["passed"] is False

    @pytest.mark.asyncio
    async def test_prediction_caliber_documents_the_baseline(self) -> None:
        """口径的 pitfall 必须写明「震荡撑起整体命中率」这件事。

        这是最容易被漏掉的一类信息：数字没算错，但单独看会被读成能力。
        """
        from app.services import calibers

        caliber = calibers.describe("prediction")

        assert "朴素基线" in caliber["benchmark"]
        assert "震荡" in caliber["pitfall"]
        assert "edge_over_baseline" in caliber["pitfall"]
        assert "directional_hit_rate" in caliber["pitfall"]

    def test_prediction_cannot_claim_a_market_benchmark(self) -> None:
        """它预测的就是上证指数本身，不允许写沪深300 这类指数基准。"""
        from app.services import calibers

        benchmark = calibers.describe("prediction")["benchmark"]

        assert "沪深300" not in benchmark
        assert "无法「换基准」" in benchmark
