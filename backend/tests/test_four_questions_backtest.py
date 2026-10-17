"""四问守卫在回测口径上的接线测试。

## 覆盖的三个口径与它们的差别

| 口径 | n | median/mean | tradable | 符号翻转 | 性质 |
|---|---|---|---|---|---|
| `tactic_backtest` | 有 | 有 | 不适用 | 有（edge 符号） | **四项全答** |
| `limitup_premium` | 有 | 有 | 恒 100%（已筛过） | 有（双基准同号） | **四项全答** |
| `limitup_relay` | 有 | 无 | 无 | 无 | 只答一问答不上来三问 |

第三行是本文件最重要的一类断言：**答不上来的必须真答不上来**。
`limitup_relay` 特别容易被"补全"成假数据 ——
它的 `overall_rate` 是个漂亮的百分比，很容易顺手写成「均�� = 该率、中位 = 该率」
把分布那一问"答满"。但晋级率是**二分类封板状态延续率**，没有收益分布可言；
把「晋级=1、未晋级=0」当收益会把连续收益压成 0/1，而未晋级时单日亏 10% 以上
很常见 —— 那个 0 是彻底错的。这类"看起来无害的补全"正是守卫要拦的。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import calibers, limitup_service as lus
from app.services import tactic_backtest_service as tbs


def _by_key(four: dict) -> dict[str, dict]:
    return {i["key"]: i for i in four["items"]}


# ── tactic_backtest ─────────────────────────────────────────────────────


def _signals(values: list[float]) -> list[tuple[float, float, float, str]]:
    return [(v, abs(v), -abs(v) * 0.5, "000001") for v in values]


def _tactic(direction: str = "buy") -> dict:
    return {
        "key": "t",
        "name": "测试形态",
        "category": "c",
        "direction": direction,
        "desc": "d",
        "warmup": 60,
    }


class TestTacticBacktest:
    def test_answers_every_answerable_question(self) -> None:
        """形态回测是唯一「该答的都答得上」的口径 —— 四问必须真的干净。

        注意是 3/4 而非 4/4：可成交那一问标的是「不适用」（收盘价入场本身不存在
        挂不上单的问题），刻意不折算成 100%。详见
        `test_tradable_is_not_answered_rather_than_faked`。
        """
        # 40 次命中，收益集中在 +2%~+3%，基准为 0 ⇒ edge 为正、无符号翻转
        signals = _signals([2.0 + i * 0.02 for i in range(40)])
        result = tbs._pack(_tactic(), 5, signals, [0.0] * 40, 1, {"000001": [s[0] for s in signals]})
        four = result["four_questions"]

        # 该答的三问全过：n / 分布 / 符号翻转
        assert _by_key(four)["sample"]["passed"] is True
        assert _by_key(four)["median"]["passed"] is True
        assert _by_key(four)["benchmark_sign"]["passed"] is True
        # 唯一没答的是「不适用」的可成交
        assert four["answered_count"] == 3
        assert four["unanswered_keys"] == ["tradable"]
        # 有未答项 ⇒ 恒不为 credible（宁可保守，不可虚报合格）
        assert four["verdict"] == "unknown"
        assert four["failed_keys"] == []

    def test_blank_state_still_ships_four_questions(self) -> None:
        """空态必须下发四问（n=0），而不是留 None。

        前端拿到 None 会分不清「没接线」与「样本为零」—— 而后者恰恰是
        回测结论最需要说清的一种状态。
        """
        result = tbs._pack(_tactic(), 5, [], [], 0, {})

        assert result["four_questions"] is not None
        assert _by_key(result["four_questions"])["sample"]["passed"] is False

    def test_negative_edge_is_reported_as_sign_flip(self) -> None:
        """形态收益比基准还差 ⇒ edge < 0 ⇒ 符号翻转（收益来自方向而非形态）。"""
        signals = _signals([1.0] * 40)
        # 基准平均 +5%：买入形态 edge = 1 − 5 = −4 ⇒ 换基准后超额翻向
        result = tbs._pack(_tactic(), 5, signals, [5.0] * 40, 1, {"000001": [1.0] * 40})
        four = result["four_questions"]

        assert result["edge_return"] == -4.0
        assert four["verdict"] == "inflated"
        assert "benchmark_sign" in four["failed_keys"]

    def test_sell_direction_edge_is_sign_flipped_correctly(self) -> None:
        """卖出形态的 edge 已在上游取反 —— 四问必须跟着取反后的符号判，不能再翻一次。

        卖出形态：跌得比基准更多才算超额。若在这里再取反一次，
        「超额为正」会被误判成「符号翻转」。
        """
        # 卖出形态，收益 −6%（跌得多），基准 −3%（跌得少）⇒ 超额为正
        signals = _signals([-6.0] * 40)
        result = tbs._pack(_tactic("sell"), 5, signals, [-3.0] * 40, 1, {"000001": [-6.0] * 40})

        # edge = baseline_avg − avg_return = −3 −(−6) = +3 ⇒ 超额为正
        assert result["edge_return"] == 3.0
        assert _by_key(result["four_questions"])["benchmark_sign"]["passed"] is True

    def test_tradable_is_not_answered_rather_than_faked(self) -> None:
        """形态回测是收盘价入场，本身可成交 —— 但「不适用」不能折算成 100%。

        折算成 1.0 等于宣称「已验证可成交」，而实际只是「这个口径下没有这个问题」。
        """
        signals = _signals([2.0] * 40)
        result = tbs._pack(_tactic(), 5, signals, [0.0] * 40, 1, {"000001": [2.0] * 40})
        item = _by_key(result["four_questions"])["tradable"]

        assert item["answered"] is False
        assert item["passed"] is None

    def test_median_uses_raw_returns_not_rounded_average(self) -> None:
        """中位数必须来自 returns 本体；用四舍五入的均值会掩盖分布偏斜。"""
        # 39 次 +1%，1 次 +40% ⇒ 中位 1.0、均值约 1.95
        signals = _signals([1.0] * 39 + [40.0])
        result = tbs._pack(_tactic(), 5, signals, [0.0] * 40, 1, {"000001": [1.0] * 40})
        item = _by_key(result["four_questions"])["median"]

        assert "中位 1.0" in item["value"]
        assert item["passed"] is False  # 均值被极端值拉偏 ⇒ 必须点名引用中位数

    def test_small_sample_is_insufficient_not_credible(self) -> None:
        """样本不足时不得出现 credible —— 这是最容易被绕过的一处。"""
        signals = _signals([2.0] * 12)
        result = tbs._pack(_tactic(), 5, signals, [0.0] * 12, 1, {"000001": [2.0] * 12})
        four = result["four_questions"]

        assert four["verdict"] != "credible"
        assert "sample" in four["failed_keys"]


# ── limitup_premium ─────────────────────────────────────────────────────


def _premium_row(ret: float, bench: float | None = 0.0, bench2: float | None = 0.0) -> dict:
    return {"d": "2026-10-01", "code": "000001", "name": "x", "sector": "s",
            "turnover": 8.0, "ret_open": ret, "bench_ret": bench, "bench2_ret": bench2}


class TestPremiumBacktest:
    def test_all_four_answered_when_both_benchmarks_present(self) -> None:
        rows = [_premium_row(0.02 + i * 0.0002) for i in range(40)]
        stats = lus._aggregate_premium(rows)
        four = stats["four_questions"]

        assert four["answered_count"] == 4
        assert four["verdict"] == "credible"

    def test_median_is_computed_on_excess_not_raw_premium(self) -> None:
        """中位数/均值必须用**超额**样本，不能用原始溢价。

        原始溢价里混着大盘贝塔（普涨时全体为正），用它算分布会把贝塔算进形态溢价。
        """
        # 全部原始溢价 +5%（像普涨行情），但基准 +5% ⇒ 超额全为 0
        rows = [_premium_row(0.05, bench=0.05, bench2=0.05) for _ in range(40)]
        stats = lus._aggregate_premium(rows)
        item = _by_key(stats["four_questions"])["median"]

        assert "中位 0.0" in item["value"]

    def test_tradable_is_100_because_samples_were_pre_filtered(self) -> None:
        """本函数只取换手 ≥5% 的样本 ⇒ 样本内可成交比例恒为 100%。

        这是「已按可成交筛过」的事实陈述，不是「已验证可成交率 100%」。
        """
        rows = [_premium_row(0.02) for _ in range(40)]
        item = _by_key(lus._aggregate_premium(rows)["four_questions"])["tradable"]

        assert item["answered"] is True
        assert item["passed"] is True
        assert "100.0%" in item["value"]

    def test_sign_flip_detected_when_benchmarks_disagree(self) -> None:
        """主基准 +2%（超额为正）、翻转基准 −8%（超额翻负）⇒ 符号不一致。"""
        rows = [_premium_row(0.02, bench=0.02, bench2=-0.08) for _ in range(40)]
        stats = lus._aggregate_premium(rows)

        assert stats["sign_consistent"] is False
        assert stats["verified_candidate"] is False
        assert _by_key(stats["four_questions"])["benchmark_sign"]["passed"] is False

    def test_missing_flip_benchmark_is_unanswered_not_passed(self) -> None:
        """只有主基准、没有翻转基准 ⇒ 符号检验答不上来，不能当通过。"""
        rows = [_premium_row(0.02, bench=0.0, bench2=None) for _ in range(40)]
        item = _by_key(lus._aggregate_premium(rows)["four_questions"])["benchmark_sign"]

        assert item["answered"] is False
        assert item["passed"] is None

    def test_empty_samples_still_ship_four_questions(self) -> None:
        stats = lus._aggregate_premium([])

        assert stats["n"] == 0
        assert stats["four_questions"] is not None
        assert _by_key(stats["four_questions"])["sample"]["passed"] is False

    def test_four_questions_never_overturns_verified_candidate(self) -> None:
        """四问是补充闸，不改判 verified_candidate —— 后者由证据等级链管。

        两者职责不同：四问问「数字站不站得住」，verified 问「证据够不够格」。
        混在一起会让任何一次口径调整都能悄悄改变证据等级。
        """
        rows = [_premium_row(0.02, bench=0.0, bench2=0.0) for _ in range(40)]
        stats = lus._aggregate_premium(rows)

        assert stats["verified_candidate"] is True
        # 四问这里也恰好是 credible，但两者是独立算出来的，不是同一个字段
        assert "four_questions" in stats
        assert stats["verified_candidate"] is not stats["four_questions"]["verdict"]


# ── limitup_relay（只答一问的口径）──────────────────────────────────────


class TestRelayBacktest:
    def _stats(self, total: int = 60) -> dict:
        days = [SimpleNamespace(isoformat=lambda self=None, d=i: f"2026-10-{i:02d}") for i in range(1, 6)]
        # 构造 5 天 → 4 个交易对，每天 1 只，boards 递增
        per_day = {}
        for idx, d in enumerate(range(1, 5)):
            per_day[f"2026-10-{d:02d}"] = [{"code": f"c{d}", "boards": 1 + d, "sector": "s"}]
        per_day["2026-10-05"] = [{"code": "c4", "boards": 6, "sector": "s"}]
        return lus._relay_stats(days, per_day)

    def test_relay_refuses_to_fabricate_a_distribution(self) -> None:
        """晋级率没有收益分布 —— 这一问必须答不上来。

        它有 `overall_rate` 这个漂亮的百分比，最容易被顺手写成
        「均值=该率、中位=该率」把分布问"答满"。那是错的：
        晋级率是二分类封板延续率，不是收益。
        """
        four = self._stats()["four_questions"]
        item = _by_key(four)["median"]

        assert item["answered"] is False
        assert item["passed"] is None

    def test_relay_never_reaches_credible(self) -> None:
        """只有一问答得上 ⇒ verdict 恒不为 credible。"""
        four = self._stats()["four_questions"]

        assert four["answered_count"] == 1
        assert four["verdict"] != "credible"
        assert set(four["unanswered_keys"]) == {"median", "tradable", "benchmark_sign"}

    def test_relay_tradable_gap_is_called_out_as_the_core_trap(self) -> None:
        """可成交这一问的缺失本身就是本口径的头号陷阱，必须写在 detail 里。

        calibers.limitup_relay 的 pitfall 说的就是这件事：晋级率高 ≠ 能赚钱，
        中间隔着的正是「能不能买到」。四问把它放到最显眼的位置。
        """
        item = _by_key(self._stats()["four_questions"])["tradable"]

        assert "答不上来" not in item["detail"] or "成交" in item["detail"]
        assert "一字板" in item["detail"] or "成交不了" in item["detail"]


# ── 补充说明层（four_questions_with_notes）──────────────────────────────


class TestNotesLayer:
    def test_notes_append_without_changing_verdict(self) -> None:
        """补充说明只追加文字，绝不能改变判定（否则就成了绕过守卫的后门）。"""
        base = calibers.four_questions(n=10)
        noted = calibers.four_questions_with_notes({"sample": "额外说明"}, n=10)

        assert noted["verdict"] == base["verdict"]
        assert noted["failed_keys"] == base["failed_keys"]
        assert "额外说明" in _by_key(noted)["sample"]["detail"]

    def test_notes_for_unknown_key_are_ignored(self) -> None:
        noted = calibers.four_questions_with_notes({"no_such_key": "x"}, n=10)

        assert noted["verdict"] == "inflated"
        assert all("x" not in i["detail"] for i in noted["items"])

    def test_notes_preserve_the_original_detail(self) -> None:
        """补充不能覆盖原句 —— 原句是通用判据，补充只是加一层语境。"""
        base = calibers.four_questions(n=10)
        noted = calibers.four_questions_with_notes({"sample": "补充"}, n=10)

        assert _by_key(base)["sample"]["detail"] in _by_key(noted)["sample"]["detail"]
