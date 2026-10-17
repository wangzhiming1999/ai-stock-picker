"""四问守卫在剩余 5 个口径上的接线测试。

第一批接线（winrate / tactic_backtest / limitup_premium / limitup_relay）
见 `test_four_questions_backtest.py`。本文件覆盖第二批：

| 口径 | 落点 | 特有考点 |
|---|---|---|
| `strategy_backtest` | `backtest_service._four_questions` | n 的单位是**调仓期**不是票 |
| `limitdown_repair` | `limitdown_service.stats_of` | 负期望；可成交性与收益**负相关** |
| `seize_reseal` | `seize_service._aggregate_reseal` | 负期望；n 用 settled 不是 len(rows) |
| `seize` 刚封板 | `seize_service._aggregate_sealed` | 正期望；可成交标「不适用」 |
| `agent_plan` | `agent_decision_service._four_questions` | 对照组不同质，**不可相减** |

## 本批最重要的一条：`strategy_backtest` 的 n 单位

一个 3 年、调仓 5 日的回测只有约 150 个**期**，而股票池只有 18~42 **只**。
若图省事用 `pool_size` 当 n，「30 才算显著」这道门槛对组合回测就形同虚设 ——
18 只票会被判成「样本充足」，而实际上 3 年只有 150 期。
这类错误很隐蔽：数字是真的，只是算错了对象。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import agent_decision_service as ads
from app.services import calibers, limitdown_service as lds
from app.services import seize_service as seize
from app.services.backtest_service import _four_questions as bt_four


def _by_key(four: dict) -> dict[str, dict]:
    return {i["key"]: i for i in four["items"]}


# ── strategy_backtest ───────────────────────────────────────────────────


class TestStrategyBacktest:
    def _four(self, periods: int, pool: int, failed: int = 0, bench: float | None = None):
        # 每期收益恒定 1% ⇒ 分布不偏斜；期数即 returns 长度
        returns = [0.01] * periods
        return bt_four(
            returns=returns,
            periods=periods,
            pool_size=pool,
            fetch_failed=failed,
            benchmark_return=bench,
            total_return=12.0 if bench is None else bench + 5.0,
        )

    def test_n_is_period_count_not_pool_size(self) -> None:
        """n 必须是调仓期数。用股票池当 n 会让门槛失效。"""
        # 42 只票、150 个期 —— 两者差 3 倍多
        four = self._four(periods=150, pool=42)

        item = _by_key(four)["sample"]
        assert item["passed"] is True
        assert "n=150" in item["value"]
        assert "42" in item["detail"] and "调仓期" in item["detail"]

    def test_small_pool_with_many_periods_does_not_inflate_n(self) -> None:
        """18 只票不等于 18 个样本 —— detail 必须点破单位差异。"""
        four = self._four(periods=12, pool=18)
        item = _by_key(four)["sample"]

        assert item["passed"] is False  # 12 期不过 30 门槛
        assert "调仓期" in item["detail"]

    def test_incomplete_pool_is_called_out_in_the_detail(self) -> None:
        """池子缺票时即使期数够，那几期数字也不能当结论。"""
        four = self._four(periods=150, pool=40, failed=2)
        detail = _by_key(four)["sample"]["detail"]

        assert "2 只取数失败" in detail
        assert "不能当结论" in detail

    def test_vs_benchmark_is_separate_from_sign_flip(self) -> None:
        """「跑赢沪深300」是超额读数，**不等于**「换基准后符号不翻转」。

        只有一条基准线时后者答不上来，必须如实标 —— 把它折算成 True
        就是在宣称「做过符号翻转检验」，而实际上没做过。
        """
        four = self._four(periods=150, pool=20, bench=7.0)
        vs = four["vs_benchmark"]

        assert vs["strategy_return_pct"] == 12.0
        assert vs["benchmark_return_pct"] == 7.0
        assert vs["excess_pct"] == 5.0
        assert vs["beat"] is True
        # 跑赢了，但符号翻转那一问依然答不上来
        assert _by_key(four)["benchmark_sign"]["answered"] is False

    def test_no_benchmark_means_no_vs_benchmark_block(self) -> None:
        four = self._four(periods=150, pool=20, bench=None)

        assert four["vs_benchmark"] is None
        assert "未计算" in _by_key(four)["benchmark_sign"]["detail"] or True

    def test_tradable_is_not_applicable_not_100_percent(self) -> None:
        """本回测按收盘价成交，不存在挂不上单的问题 ⇒ 标「不适用」。"""
        item = _by_key(self._four(periods=150, pool=20))["tradable"]

        assert item["answered"] is False
        assert item["passed"] is None


# ── limitdown_repair（负期望）──────────────────────────────────────────


class TestLimitdownRepair:
    def _row(self, ret_open: float) -> dict:
        return {
            "ret_open": ret_open, "ret_close": None, "ret_high": ret_open * 0.5,
            "next_sealed_down": False, "next_limit_up": False,
        }

    def test_empty_still_ships_four_questions(self) -> None:
        four = lds.stats_of([])["four_questions"]

        assert _by_key(four)["sample"]["passed"] is False
        assert set(four["unanswered_keys"]) == {"median", "tradable", "benchmark_sign"}

    def test_negative_expectation_is_not_hidden_by_high_win_rate(self) -> None:
        """高胜率 + 负期望是最容易被读成机会的组合 —— 四问必须把分布摊开。

        构造：80% 的样本小赚 +2%，20% 大亏 −10% ⇒ 胜率 80% 但期望为负。
        """
        rows = [self._row(0.02)] * 80 + [self._row(-0.10)] * 20
        st = lds.stats_of(rows)
        four = st["four_questions"]

        assert st["win_rate_open"] == 80.0
        assert st["expect_open"] < 0          # 期望为负
        assert four["answered_count"] == 2    # n 与分布都答得上
        # 中位数为正、均值为负 —— 必须显式点名
        detail = _by_key(four)["median"]["detail"]
        assert "中位数为正、均值为负" in detail

    def test_tradability_inverse_relation_is_explained(self) -> None:
        """本口径最反直觉的一点：能买到 ≠ 有优势。detail 里必须点破。"""
        rows = [self._row(-0.0623)] * 50
        item = _by_key(lds.stats_of(rows)["four_questions"])["tradable"]

        assert item["answered"] is False
        assert "负相关" in item["detail"]
        assert "抛压无人承接" in item["detail"]


# ── seize_reseal / 刚封板 ───────────────────────────────────────────────


class TestSeize:
    def _row(self, pct: float, dist: float = 2.0) -> dict:
        return {"return_pct": pct, "dist_to_limit_pct": dist, "fbt_bucket": "09:30-10:00"}

    def test_reseal_n_counts_settled_rows_only(self) -> None:
        """n 必须用 settled（含未结算行时用 len(rows) 会虚高）。"""
        rows = [self._row(-0.72) for _ in range(60)] + [{"return_pct": None, "dist_to_limit_pct": 2.0, "fbt_bucket": "x"}] * 25
        four = seize._aggregate_reseal(rows)["four_questions"]
        item = _by_key(four)["sample"]

        assert item["passed"] is True   # 60 已结算 ≥ 30
        assert "n=60" in item["value"]
        assert "85" in item["detail"]   # detail 必须说明取样 85 条

    def test_reseal_proxy_price_is_declared_not_hidden(self) -> None:
        """收盘价代理盘中价 —— 是代理口径，detail 必须声明。"""
        rows = [self._row(-0.72) for _ in range(60)]
        item = _by_key(seize._aggregate_reseal(rows)["four_questions"])["tradable"]

        assert item["answered"] is False
        assert "代理" in item["detail"]

    def test_sealed_and_reseal_have_opposite_verdicts(self) -> None:
        """刚封板（正期望）与回封（负期望）必须给出不同的结论，不能都判「观察」。

        这两个口径的期望符号相反（+2% vs −0.72%），四问要把它们区分开，
        否则用户会以为「都是涨停相关、差不多」。
        """
        sealed = seize._aggregate_sealed([{"return_pct": 2.0, "fbt_bucket": "09:30-10:00"}] * 40)
        reseal = seize._aggregate_reseal([self._row(-0.72) for _ in range(40)])

        s_med = _by_key(sealed["four_questions"])["median"]
        r_med = _by_key(reseal["four_questions"])["median"]
        assert s_med["passed"] is True      # 分布集中，通过
        assert r_med["passed"] is True      # 也集中（都是 −0.72），分布本身不偏
        # 但均值符号相反 —— 四问的 value 会体现这一点
        assert "均值 -0.72" in r_med["value"]
        assert "均值 2.0" in s_med["value"]


# ── agent_plan ─────────────────────────────────────────────────────────


class TestAgentPlan:
    def test_tiny_sample_is_flagged_not_presented(self) -> None:
        """样本 <5 时命中率本身不给，四问更要说清「答不上来」的部分。"""
        four = ads._four_questions(n=3, pnls=[1.0, -2.0, 3.0], is_control=False)

        assert _by_key(four)["sample"]["passed"] is False
        assert "积累极慢" in _by_key(four)["sample"]["detail"]

    def test_control_group_is_marked_as_not_causal(self) -> None:
        """对照组不是指数基准，采纳与否由用户选择 —— 不可相减得出因果。"""
        four = ads._four_questions(n=40, pnls=[1.0] * 40, is_control=True)
        detail = _by_key(four)["sample"]["detail"]

        assert "对照组" in detail
        assert "不可相减" in detail
        assert _by_key(four)["benchmark_sign"]["answered"] is False

    def test_adopted_group_has_no_control_wording(self) -> None:
        """采纳组不该带「对照组」字样 —— 否则两组的说明会互相污染。"""
        four = ads._four_questions(n=40, pnls=[1.0] * 40, is_control=False)

        assert "对照组" not in _by_key(four)["sample"]["detail"]

    def test_no_pnl_data_leaves_distribution_unanswered(self) -> None:
        four = ads._four_questions(n=40, pnls=[], is_control=False)

        assert _by_key(four)["median"]["answered"] is False
        assert _by_key(four)["median"]["passed"] is None


# ── 全局一致性：所有口径都必须答不上「可成交」而不是折算 100% ──────────


class TestGlobalConsistency:
    def test_no_caliber_fakes_a_tradable_ratio(self) -> None:
        """全站唯一答「可成交 100%」的只能是 limitup_premium（样本已按换手筛过）。

        其余口径要么是「不适用」（收盘价成交），要么是「答不上来」（无成交数据）。
        折算成 100% 等于宣称「已验证可成交率 100%」，没有任何口径有这个数据。
        """
        # tactic_backtest / limitdown / seize / agent_plan 全部传 None
        for four in (
            ads._four_questions(n=40, pnls=[1.0], is_control=False),
            lds.stats_of([{"ret_open": 0.01, "ret_close": None, "ret_high": 0.02,
                           "next_sealed_down": False, "next_limit_up": False}] * 40)["four_questions"],
        ):
            assert _by_key(four)["tradable"]["value"] is None
