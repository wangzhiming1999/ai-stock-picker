"""涨停次日溢价「可成交档」walk-forward 实测的回归测试。

这条是 ROADMAP 第五节 🔴 最高主线（把可成交性从代理变实测）的落地。测试分两层：

1. **纯函数 `_aggregate_premium`**（不碰网络）：锁死验证闸门的四个判据 ——
   n ≥ 30、主基准超额 >0、超额胜率 >50%、与翻转基准符号一致，缺一即 `verified_candidate=False`。
2. **编排 `premium_backtest`**（mock 取数，无网络）：锁死
   (a) 只统计换手 ≥5% 的可成交档、剔除缩量一字/秒板；
   (b) 「涨停价买入 → 次日开盘卖」的收益计算与沪深300 对齐；
   (c) 缓存命中与空池排除不污染样本。

⚠️ 本文件**不触发任何真实行情请求**。真实跑批（≈200 次逐只 K）是高风险外部动作，
由 `premium_backtest` 的 `force=true` + 受控端点承担，不在此处执行。
"""
import asyncio
import unittest
from datetime import date
from unittest import mock

from app.models import StockHistory
from app.services import data_service, limitup_service as L


def _canned_hist(open_next: float) -> StockHistory:
    """构造 [09-15, 09-16, 09-17] 三天的 K：close 恒为 10，次日开盘 = open_next。

    这样 D=15→16、D=16→17 的「次日开盘 ÷ 当日收盘 − 1」都 = open_next/10 − 1，
    与样本日期无关，便于断言。
    """
    return StockHistory(
        dates=["2026-09-15", "2026-09-16", "2026-09-17"],
        closes=[10.0, 10.0, 10.0],
        opens=[10.0, open_next, open_next],
    )


def _raw(code: str, turnover: float) -> dict:
    """东财涨停池原始记录（price 单位为「厘」，10000 = 10.00 元）。"""
    return {
        "c": code,
        "n": f"S{code}",
        "p": 10000,
        "hs": turnover,
        "hybk": "半导体",
        "lbc": 1,
        "zdp": 10.0,
        "fbt": 93000,
        "zbc": 0,
        "fund": 0,
        "ltsz": 1e10,
        "amount": 1e8,
    }


def _mock_get_history(code: str, days: int, period: str = "day") -> StockHistory:
    # 主基准 / 翻转基准给 +0.5%（open_next=10.05），个股给 +1.5%（open_next=10.15）。
    if code in (L._PREMIUM_BENCHMARK, L._PREMIUM_BENCHMARK_FLIP):
        return _canned_hist(10.05)
    return _canned_hist(10.15)


class AggregateTests(unittest.TestCase):
    def _rows(self, n: int, ret: float, bench: float, bench2: float) -> list[dict]:
        return [{"ret_open": ret, "bench_ret": bench, "bench2_ret": bench2} for _ in range(n)]

    def test_positive_excess_passes_gate(self) -> None:
        # n=40、超额 +1.0%、超额胜率 100%、双基准同号为正 → 满足 verified 判据。
        stats = L._aggregate_premium(self._rows(40, 0.015, 0.005, 0.005))
        self.assertEqual(stats["n"], 40)
        self.assertEqual(stats["mean_premium_pct"], 1.5)
        self.assertEqual(stats["mean_excess_pct"], 1.0)
        self.assertEqual(stats["excess_win_rate_pct"], 100.0)
        self.assertTrue(stats["sign_consistent"])
        self.assertTrue(stats["verified_candidate"])

    def test_small_sample_fails_gate(self) -> None:
        # n < 30 即使超额为正也不够门槛。
        stats = L._aggregate_premium(self._rows(10, 0.015, 0.005, 0.005))
        self.assertEqual(stats["n"], 10)
        self.assertFalse(stats["verified_candidate"])

    def test_negative_excess_fails_gate(self) -> None:
        # 收益高于基准但绝对超额为负（基准涨更多）→ 不算赢。
        stats = L._aggregate_premium(self._rows(40, 0.0, 0.01, 0.01))
        self.assertFalse(stats["verified_candidate"])
        self.assertLess(stats["mean_excess_pct"], 0)

    def test_sign_flip_fails_gate(self) -> None:
        # 主基准超额为正、翻转基准超额为负 → 符号翻转，结论不稳，闸门关闭。
        stats = L._aggregate_premium(self._rows(40, 0.02, 0.005, 0.05))
        self.assertFalse(stats["sign_consistent"])
        self.assertFalse(stats["verified_candidate"])

    def test_missing_benchmark_excluded_from_excess(self) -> None:
        # 部分样本缺基准：超额只在有基准的样本上算，n 仍是全量。
        rows = [{"ret_open": 0.015, "bench_ret": 0.005, "bench2_ret": 0.005} for _ in range(30)]
        rows += [{"ret_open": 0.015, "bench_ret": None, "bench2_ret": None} for _ in range(10)]
        stats = L._aggregate_premium(rows)
        self.assertEqual(stats["n"], 40)
        self.assertEqual(stats["benchmark_available"], 30)
        self.assertEqual(stats["mean_excess_pct"], 1.0)
        self.assertTrue(stats["verified_candidate"])

    def test_empty_returns_safe_defaults(self) -> None:
        stats = L._aggregate_premium([])
        self.assertEqual(stats["n"], 0)
        self.assertIsNone(stats["mean_premium_pct"])
        self.assertFalse(stats["verified_candidate"])


class OrchestrationTests(unittest.TestCase):
    def setUp(self) -> None:
        L.clear_caches()
        # 2 个交易日；每日常规 20 只可成交(换手8) + 1 只边界可成交(换手5) + 5 只不可成交(换手2) + 1 只边界不可成交(换手4.99)
        self.tradable_per_day = 20 + 1
        self.unbuyable_per_day = 5 + 1
        self.days = [date(2026, 9, 15), date(2026, 9, 16)]

        raw_pool = (
            [_raw(f"60{i:04d}", 8.0) for i in range(20)]
            + [_raw("60009999", 5.0)]          # 边界：恰好 5.0 → 可成交
            + [_raw(f"60{i:04d}", 2.0) for i in range(5)]
            + [_raw("60008888", 4.99)]         # 边界：4.99 → 不可成交
        )

        self.patchers = [
            mock.patch.object(L, "_completed_trading_days", new=mock.AsyncMock(return_value=self.days)),
            mock.patch.object(L, "_fetch_pool_sync", new=lambda kind, ds: list(raw_pool)),
            mock.patch.object(L, "load_accumulated_snapshots", new=mock.AsyncMock(return_value={})),
            mock.patch.object(data_service, "get_history", new=_mock_get_history),
        ]
        for p in self.patchers:
            p.start()

    def tearDown(self) -> None:
        for p in self.patchers:
            p.stop()

    def test_only_tradable_bucket_is_counted(self) -> None:
        # 候选数 = 可成交(21/天) × 2 天 = 42；缩量一字/秒板(换手<5)被剔除。
        result = asyncio.run(L.premium_backtest(days=2, force=True))
        self.assertEqual(result["candidate_size"], self.tradable_per_day * 2)
        self.assertEqual(result["samples_used"], self.tradable_per_day * 2)
        self.assertEqual(result["effective_days"], 2)
        self.assertEqual(result["empty_dates"], [])

    def test_realized_premium_and_excess_match_canned_data(self) -> None:
        result = asyncio.run(L.premium_backtest(days=2, force=True))
        # 个股次日开盘 +1.5%、沪深300 +0.5% → 实测溢价 1.5%、超额 1.0%。
        self.assertEqual(result["mean_premium_pct"], 1.5)
        self.assertEqual(result["mean_excess_pct"], 1.0)
        # 样本充足且双基准同号为正 → 闸门打开。
        self.assertTrue(result["verified_candidate"])

    def test_cache_is_used_on_second_call(self) -> None:
        first = asyncio.run(L.premium_backtest(days=2, force=True))
        self.assertFalse(first["cached"])
        # 第二次（非 force）直接命中缓存，不再触发取数编排。
        second = asyncio.run(L.premium_backtest(days=2, force=False))
        self.assertTrue(second["cached"])

    def test_static_expectation_is_tradable_only(self) -> None:
        # 静态对照 = 换手≥5% 三档期望的均值（1.62+1.10+0.40）/3 = 1.04。
        result = asyncio.run(L.premium_backtest(days=2, force=True))
        self.assertAlmostEqual(result["static_tradable_expectation_pct"], (1.62 + 1.10 + 0.40) / 3, places=2)


class DisciplineTests(unittest.TestCase):
    def test_evidence_stays_preliminary_until_real_run(self) -> None:
        # 没跑真实批、代码未升级：仍 preliminary 且不进买点。
        from app.services import tactic_evidence as E

        self.assertEqual(E.tier_of("limitup_premium"), "preliminary")
        self.assertFalse(E.is_actionable("limitup_premium"))


if __name__ == "__main__":
    unittest.main()
