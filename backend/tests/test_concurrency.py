"""行情源并发闸门测试。

背景：腾讯历史 K 线按 code 逐只请求，一句无上限的 `asyncio.gather` 会瞬间对同一出口 IP
甩出几十个请求，触发 IP 级风控后全站 502 数分钟（2026-09-15 线上实测）。
本文件锁定「并发必须被全局上限压住」这一约束，防止以后被改回无上限写法。
"""
import asyncio
import threading
import time

import pytest

from app.services import concurrency


def _peak_tracker():
    """返回 (包装函数, 读取峰值)：线程安全地记录同时在飞的任务数。"""
    lock = threading.Lock()
    state = {"in_flight": 0, "peak": 0}

    def enter():
        with lock:
            state["in_flight"] += 1
            state["peak"] = max(state["peak"], state["in_flight"])

    def leave():
        with lock:
            state["in_flight"] -= 1

    return enter, leave, lambda: state["peak"]


@pytest.mark.asyncio
async def test_gather_limited_caps_concurrency():
    enter, leave, peak = _peak_tracker()

    async def _job():
        enter()
        try:
            await asyncio.sleep(0.01)
            return "ok"
        finally:
            leave()

    results = await concurrency.gather_limited([_job() for _ in range(30)])

    assert results == ["ok"] * 30
    assert peak() <= concurrency.FETCH_CONCURRENCY
    # 确认是真并发而非被串行化（否则「加了上限」会变成「变成单线程」的隐性性能事故）
    assert peak() > 1


@pytest.mark.asyncio
async def test_quota_is_shared_across_concurrent_batches():
    """两个同时发起的批次共用同一份配额 —— 这正是保护同一个出口 IP 的关键。

    若改成「每次调用各建一个 Semaphore」，本用例会失败（峰值变成 2×上限）。
    """
    enter, leave, peak = _peak_tracker()

    async def _job():
        enter()
        try:
            await asyncio.sleep(0.01)
        finally:
            leave()

    def _batch():
        return [_job() for _ in range(20)]

    await asyncio.gather(
        concurrency.gather_limited(_batch()),
        concurrency.gather_limited(_batch()),
    )

    assert peak() <= concurrency.FETCH_CONCURRENCY


@pytest.mark.asyncio
async def test_gather_limited_preserves_input_order():
    """返回顺序必须与入参一致：调用方普遍用 zip(codes, results) 回填映射。"""

    async def _echo(i: int) -> int:
        await asyncio.sleep((10 - i) * 0.001)
        return i

    assert await concurrency.gather_limited(_echo(i) for i in range(10)) == list(range(10))


@pytest.mark.asyncio
async def test_gather_limited_empty_input_returns_empty():
    assert await concurrency.gather_limited([]) == []


@pytest.mark.asyncio
async def test_gather_limited_can_collect_exceptions():
    """return_exceptions=True 时单只票失败不能拖垮整批。"""

    async def _boom():
        raise RuntimeError("行情源挂了")

    async def _ok() -> int:
        return 1

    out = await concurrency.gather_limited([_ok(), _boom(), _ok()], return_exceptions=True)

    assert out[0] == 1
    assert isinstance(out[1], RuntimeError)
    assert out[2] == 1


@pytest.mark.asyncio
async def test_apply_strategy_history_fetch_is_bounded(monkeypatch):
    """回归测试：策略扫描对 30 只候选拉 K 线，峰值并发必须被压住。"""
    from app.routes import market
    from app.services import data_service

    enter, leave, peak = _peak_tracker()
    codes = [f"600{i:03d}" for i in range(30)]

    class _Quote:
        def __init__(self, code: str):
            self.code = code
            self.name = code
            self.price = 10.0
            self.change_pct = 1.0
            self.pe = 15.0
            self.pb = 1.5
            self.turnover = 3.0
            self.market_cap = 1e10
            self.volume = 1e6

    def _fake_history(code: str, days: int):
        enter()
        try:
            time.sleep(0.005)
            return None
        finally:
            leave()

    monkeypatch.setattr(data_service, "get_spot_quote", lambda cs: [_Quote(c) for c in cs])
    monkeypatch.setattr(data_service, "get_history", _fake_history)

    await market._apply_strategy(codes, "trend")

    assert peak() <= concurrency.FETCH_CONCURRENCY
