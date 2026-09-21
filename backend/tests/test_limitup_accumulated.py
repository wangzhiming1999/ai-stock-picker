"""accumulated_stats 的降级诊断必须精确：区分 Supabase 未配置 / v10 表未迁移 / 读取真出错。

此前这三个状态被混成同一个「未接入」，用户分不清是配置问题还是迁移没跑；
而表已建但暂无数据（configured=True 且 days=0）又是另一回事。本测试把四种状态钉死。
"""
from __future__ import annotations

import asyncio

from app.services import limitup_service as L


def _run(coro):
    """复用线程已有的事件循环跑协程，绝不关闭它。

    用 asyncio.run() 会 set_event_loop(None) 并关掉当前循环，污染主线程循环状态，
    导致同进程内其它用 asyncio.get_event_loop().run_until_complete() 的测试
    （test_limitup_snapshot_store.AccumulatedBackfillTests）报「no current event loop」。
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


class _Query:
    def __init__(self, sink):
        self.sink = sink

    def select(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    async def execute(self):
        mode = self.sink.get("raise")
        if mode == "missing":
            raise RuntimeError('relation "limitup_daily_snapshot" does not exist')
        if mode == "conn":
            raise ConnectionError("connection refused")
        rows = [{"trade_date": d} for d in self.sink.get("dates", [])]
        return type("R", (), {"data": rows})()


class _Store:
    def __init__(self, configured=True):
        self.configured = configured
        self.sink: dict = {}

    def is_configured(self):
        return self.configured

    async def get_service_client(self):
        return _SB(self.sink)


class _SB:
    def __init__(self, sink):
        self.sink = sink

    def table(self, _name):
        return _Query(self.sink)


class AccumulatedStatsDiagnosisTests:
    def test_not_configured_reports_supabase_not_configured(self, monkeypatch):
        """Supabase 没配 → configured=False + note 精确，不是含糊的「未接入」。"""
        monkeypatch.setattr(L, "supabase_store", None)
        out = _run(L.accumulated_stats())
        assert out["configured"] is False
        assert out["note"] == "supabase_not_configured"
        assert out["days"] == 0

    def test_table_missing_detected(self, monkeypatch):
        """已配置但表不存在（v10 迁移没跑）→ configured 仍 True，note 指向迁移缺失。"""
        store = _Store(configured=True)
        store.sink["raise"] = "missing"
        monkeypatch.setattr(L, "supabase_store", store)
        out = _run(L.accumulated_stats())
        assert out["configured"] is True
        assert out["note"] == "table_missing"
        assert out["days"] == 0

    def test_read_error_reports_type(self, monkeypatch):
        """真实连接/权限错误 → note 带上异常类型，便于排查，而非静默成空表。"""
        store = _Store(configured=True)
        store.sink["raise"] = "conn"
        monkeypatch.setattr(L, "supabase_store", store)
        out = _run(L.accumulated_stats())
        assert out["configured"] is True
        assert out["note"].startswith("read_error:")
        assert "ConnectionError" in out["note"]
        assert out["days"] == 0

    def test_normal_counts_distinct_dates(self, monkeypatch):
        """正常命中：按交易日去重，rows 是原始行数。"""
        store = _Store(configured=True)
        store.sink["dates"] = ["2026-09-01", "2026-09-01", "2026-09-02"]
        monkeypatch.setattr(L, "supabase_store", store)
        out = _run(L.accumulated_stats())
        assert out["configured"] is True
        assert out["note"] is None
        assert out["days"] == 2
        assert out["rows"] == 3
