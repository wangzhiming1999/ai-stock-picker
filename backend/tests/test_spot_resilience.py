"""行情源韧性与「失败可见」的回归测试。

背景（2026-09-18 诊断）：盯盘「成功率越来越差」的根因不是行情源全挂，而是三个机制
把「慢/局部失败」放大成了「用户以为没数据」：

1. `_fetch_qq_spot` 一次请求、零重试、异常吞成 `{}` → 整批变成空列表，
   上层看到的是 `HTTP 200 + count:0`，把行情源故障伪装成「这些票没有数据」；
2. `request.client.host` 作限流 key，在 Vercel 代理后语义不保证；
   且盯盘是 20s 轮询 + 「立即刷新」连点，60/分钟 的通用配额会被正常使用打到；
3. 未出结果的票只进一个 `missed` 列表且前端不读 —— 少 3 只和全失败长得一模一样。

对应三条约束在这里锁住：**分批重试 / 失败可区分 / 只读缓存不放大请求**。
"""
import time
import unittest
from unittest.mock import patch

from app.routes import monitor
from app.services import data_service, pattern_service


class _Resp:
    """腾讯接口响应的最小替身（只要 text / encoding 两个属性）。"""

    def __init__(self, text: str) -> None:
        self.text = text
        self.encoding = "gbk"


_OK_BODY = 'v_sh600000="1~测试~600000~10.00";'


class BatchFetchTests(unittest.TestCase):
    def setUp(self) -> None:
        data_service._hist_cache.clear()

    def test_codes_are_split_into_batches(self) -> None:
        # 单次请求 symbol 过多会被服务端静默截断（不报错、只是行数变少），必须分批。
        urls: list[str] = []

        def fake_get(url, **kwargs):
            urls.append(url)
            return _Resp(_OK_BODY)

        with patch.object(data_service.requests, "get", fake_get):
            data_service._fetch_qq_spot([f"600{i:03d}" for i in range(120)])

        self.assertEqual(len(urls), 3)  # 120 只 / 每批 50

    def test_every_batch_failing_raises_instead_of_returning_empty(self) -> None:
        def boom(url, **kwargs):
            raise ConnectionError("network down")

        with patch.object(data_service.requests, "get", boom), patch.object(data_service.time, "sleep", lambda *_: None):
            with self.assertRaises(RuntimeError) as ctx:
                data_service._fetch_qq_spot(["600000", "600001"])

        self.assertIn("连续失败", str(ctx.exception))

    def test_partial_failure_keeps_the_successful_batches(self) -> None:
        calls: list[str] = []

        def flaky(url, **kwargs):
            calls.append(url)
            if len(calls) in (2, 3):  # 第二批的首次 + 重试都失败
                raise ConnectionError("boom")
            return _Resp(_OK_BODY)

        with patch.object(data_service.requests, "get", flaky), patch.object(data_service.time, "sleep", lambda *_: None):
            raw = data_service._fetch_qq_spot([f"600{i:03d}" for i in range(120)])

        self.assertTrue(raw, "部分批次成功时必须返回成功的那部分")

    def test_empty_response_is_retried(self) -> None:
        # 空响应不等于「这批代码都不存在」，要重试；重试后仍空才算失败。
        calls: list[int] = []

        def empty_then_ok(url, **kwargs):
            calls.append(1)
            return _Resp("") if len(calls) == 1 else _Resp(_OK_BODY)

        with patch.object(data_service.requests, "get", empty_then_ok), patch.object(data_service.time, "sleep", lambda *_: None):
            raw = data_service._fetch_qq_spot(["600000"])

        self.assertEqual(len(calls), 2)
        self.assertIn("sh600000", raw)


class StrictModeTests(unittest.TestCase):
    def test_default_mode_degrades_to_empty_list(self) -> None:
        with patch.object(data_service, "_fetch_qq_spot", side_effect=RuntimeError("down")):
            self.assertEqual(data_service.get_spot_quote(["600000"]), [])

    def test_strict_mode_propagates_the_failure(self) -> None:
        with patch.object(data_service, "_fetch_qq_spot", side_effect=RuntimeError("down")):
            with self.assertRaises(RuntimeError):
                data_service.get_spot_quote(["600000"], strict=True)


class PeekHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        data_service._hist_cache.clear()

    def test_peek_never_hits_the_source(self) -> None:
        with patch.object(data_service, "_fetch_history") as fetch:
            self.assertIsNone(data_service.peek_history("600000", 400, period="week"))

        fetch.assert_not_called()

    def test_peek_returns_cached_value(self) -> None:
        sentinel = object()
        data_service._hist_cache[("600000", 400, "week")] = (time.time(), sentinel)

        self.assertIs(data_service.peek_history("600000", 400, period="week"), sentinel)

    def test_peek_ignores_expired_entries(self) -> None:
        data_service._hist_cache[("600001", 400, "week")] = (time.time() - 10**6, object())

        self.assertIsNone(data_service.peek_history("600001", 400, period="week"))


class CacheOnlyPeriodTests(unittest.IsolatedAsyncioTestCase):
    async def test_cache_only_does_not_call_the_source(self) -> None:
        calls: list[object] = []

        async def fake_gather(*args, **kwargs):
            calls.append(args)
            return []

        with patch.object(pattern_service.concurrency, "gather_limited", fake_gather):
            out = await pattern_service.load_period_histories(["600000"], "week", cache_only=True)

        self.assertEqual(calls, [], "cache_only 下不允许产生任何行情请求")
        self.assertEqual(out, {})

    async def test_cache_only_still_returns_cache_hits(self) -> None:
        sentinel = object()
        data_service._hist_cache[("600002", pattern_service._EXTRA_PERIOD_DAYS["week"], "week")] = (
            time.time(),
            sentinel,
        )
        try:
            out = await pattern_service.load_period_histories(["600002"], "week", cache_only=True)
        finally:
            data_service._hist_cache.pop(("600002", pattern_service._EXTRA_PERIOD_DAYS["week"], "week"), None)

        self.assertIs(out.get("600002"), sentinel)

    async def test_tactic_periods_passes_cache_only_through(self) -> None:
        # 盯盘轮询走的就是这条路径：只读缓存、不产生请求。
        recorded: dict[str, bool] = {}

        async def fake_periods(codes, period, *, cache_only=False):
            recorded[period] = cache_only
            return {}

        with patch.object(pattern_service, "load_period_histories", fake_periods):
            await pattern_service.load_tactic_periods(["600000"], cache_only=True)

        self.assertTrue(recorded, "应至少请求一个额外周期（多周期共振）")
        self.assertTrue(all(recorded.values()))


class MissReportTests(unittest.TestCase):
    def test_outcome_is_silent_when_every_code_succeeded(self) -> None:
        report = monitor._miss_report(["600000"], {})

        self.assertFalse(report["partial"])
        self.assertEqual(report["notice"], "")
        self.assertEqual(report["missed"], [])

    def test_reasons_are_classified_separately(self) -> None:
        report = monitor._miss_report(
            ["600000", "600001", "600002", "600003"],
            {"600001": "history_missing", "600002": "quote_missing", "600003": "signal_missing"},
        )

        self.assertTrue(report["partial"])
        self.assertEqual(report["missed"], ["600001", "600002", "600003"])
        self.assertEqual(report["missed_detail"]["quote_missing"], ["600002"])
        self.assertEqual(report["missed_detail"]["history_missing"], ["600001"])
        self.assertEqual(report["missed_detail"]["signal_missing"], ["600003"])

    def test_notice_states_total_and_reasons(self) -> None:
        report = monitor._miss_report(["600000", "600001"], {"600001": "quote_missing"})

        self.assertIn("共 2 只", report["notice"])
        self.assertIn("1 只未取到行情", report["notice"])
        self.assertNotIn("历史 K 线", report["notice"])


class LimitOrderTests(unittest.TestCase):
    def test_poll_paths_get_a_wider_quota_than_writes(self) -> None:
        # 盯盘 20s 轮询 + 连点「立即刷新」会撞到 60/分钟，那不是滥用。
        from app import main as m

        self.assertIn("/api/market/monitor", m._POLL_PATHS)
        self.assertGreater(m._poll_rate_limiter.max_requests, m._rate_limiter.max_requests)
        self.assertEqual(m._rate_limiter.max_requests, 60)

    def test_client_ip_prefers_forwarded_header(self) -> None:
        from app import main as m

        class _Req:
            def __init__(self, headers, host="10.0.0.1"):
                self.headers = headers
                self.client = type("C", (), {"host": host})()

        self.assertEqual(m._client_ip(_Req({"x-forwarded-for": "1.2.3.4, 10.0.0.9"})), "1.2.3.4")
        self.assertEqual(m._client_ip(_Req({"x-real-ip": "5.6.7.8"})), "5.6.7.8")
        self.assertEqual(m._client_ip(_Req({})), "10.0.0.1")


if __name__ == "__main__":
    unittest.main()
