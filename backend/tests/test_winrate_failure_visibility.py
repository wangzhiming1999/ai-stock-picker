"""胜率看板静默失败修复：DB 查询异常必须随响应返回，不能变成「暂无数据」。

winrate_service.get_winrate_stats 原本对 prediction_records / daily_recommendations /
winrate_snapshot 三处查询都 `except Exception: pass`，表缺失或 RLS 失败时返回 total=0 /
hit_rate=None，前端把「取数炸了」显示成「每日收盘后自动结算（今日收盘后回来看第一批结果）」。
"""
from __future__ import annotations

import asyncio

import pytest

from app.services import winrate_service as W


def _run(coro):
    """复用线程已有事件循环，避免 asyncio.run() 污染其它测试。"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


class _FilterProxy:
    """模拟 supabase-py 的 `.not_.is_("settled_at", None)` 链式调用。"""

    def __init__(self, query):
        self.query = query

    def is_(self, *_a, **_k):
        return self.query

    def eq(self, *_a, **_k):
        return self.query

    def lt(self, *_a, **_k):
        return self.query


class _Query:
    def __init__(self, sink, name):
        self.sink = sink
        self.name = name

    def select(self, *_a, **_k):
        return self

    @property
    def not_(self):
        return _FilterProxy(self)

    def is_(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    async def execute(self):
        exc = self.sink.get("raise", {}).get(self.name)
        if exc:
            raise exc
        return type("R", (), {"data": self.sink.get(self.name, [])})()


class _SB:
    def __init__(self, sink):
        self.sink = sink

    def table(self, name):
        return _Query(self.sink, name)


class _Store:
    def __init__(self, configured=True):
        self.configured = configured
        self.sink: dict = {"raise": {}, "prediction_records": [], "daily_recommendations": [], "winrate_snapshot": []}

    def is_configured(self):
        return self.configured

    async def get_service_client(self):
        return _SB(self.sink)


@pytest.fixture
def patch_store(monkeypatch):
    store = _Store()
    monkeypatch.setattr(W, "supabase_store", store)
    return store


class WinrateFailureVisibilityTests:
    def test_supabase_not_configured_returns_error(self, monkeypatch):
        monkeypatch.setattr(W, "supabase_store", _Store(configured=False))
        out = _run(W.get_winrate_stats())
        assert out["error"] == "supabase_not_configured"
        assert out["prediction"] is None
        assert out["recommendation"] is None

    def test_prediction_query_failed_surface_error(self, patch_store):
        patch_store.sink["raise"]["prediction_records"] = RuntimeError('relation "prediction_records" does not exist')
        patch_store.sink["prediction_records"] = [{"direction": "up", "hit": True}]
        out = _run(W.get_winrate_stats())
        assert out["error"] is not None
        assert "prediction_records" in out["error"]
        assert out["prediction"]["error"] is not None
        assert out["prediction"]["total"] == 0
        assert out["recommendation"]["error"] is None

    def test_recommendation_query_failed_surface_error(self, patch_store):
        patch_store.sink["raise"]["daily_recommendations"] = ConnectionError("timeout")
        patch_store.sink["daily_recommendations"] = [{"hit": True, "source": "llm"}]
        out = _run(W.get_winrate_stats())
        assert out["error"] is not None
        assert "daily_recommendations" in out["error"]
        assert out["recommendation"]["error"] is not None
        assert out["recommendation"]["total"] == 0
        assert out["prediction"]["error"] is None

    def test_snapshot_query_failed_surface_error(self, patch_store):
        patch_store.sink["raise"]["winrate_snapshot"] = PermissionError("RLS")
        out = _run(W.get_winrate_stats())
        assert out["snapshot_error"] is not None
        assert "PermissionError" in out["snapshot_error"]
        assert out["prediction"]["error"] is None
        assert out["recommendation"]["error"] is None

    def test_refresh_snapshot_skips_write_on_query_error(self, patch_store, monkeypatch):
        """查询失败时刷新快照不应把 total=0 写入历史快照。"""
        inserted = []

        class _TrackingSB(_SB):
            async def get_service_client(self):
                return self

            def table(self, name):
                if name == "winrate_snapshot":
                    return type("Q", (), {"insert": lambda _self, row: type("R", (), {"execute": lambda: inserted.append(row) or type("R", (), {"data": [row]})()})()})()
                return _SB.table(self, name)

        patch_store.sink["raise"]["prediction_records"] = RuntimeError("boom")
        tracking = _TrackingSB(patch_store.sink)
        monkeypatch.setattr(patch_store, "get_service_client", tracking.get_service_client)

        _run(W.refresh_winrate_snapshot())
        assert inserted == []

    def test_happy_path_no_error(self, patch_store):
        patch_store.sink["prediction_records"] = [{"direction": "up", "hit": True}, {"direction": "down", "hit": False}]
        patch_store.sink["daily_recommendations"] = [{"hit": True, "source": "llm"}, {"hit": False, "source": "rule"}]
        patch_store.sink["winrate_snapshot"] = [{"snapshot_date": "2026-09-21", "prediction_rate": 50.0, "recommend_rate": 50.0}]
        out = _run(W.get_winrate_stats())
        assert out["error"] is None
        assert out["prediction"]["error"] is None
        assert out["recommendation"]["error"] is None
        assert out["snapshot_error"] is None
        assert out["prediction"]["total"] == 2
        assert out["recommendation"]["total"] == 2


class _FallbackQuery:
    """首次查询 daily_recommendations 报「excess_return 列不存在」，第二次（降级查询）成功。"""

    def __init__(self, sb, name):
        self.sb = sb
        self.name = name

    def select(self, *_a, **_k):
        return self

    @property
    def not_(self):
        return self

    def is_(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    async def execute(self):
        self.sb.calls[self.name] = self.sb.calls.get(self.name, 0) + 1
        if self.name == "daily_recommendations" and self.sb.calls[self.name] == 1:
            raise RuntimeError(
                "Could not find the 'excess_return' column of 'daily_recommendations' in the schema cache"
            )
        return type("R", (), {"data": self.sb.sink.get(self.name, [])})()


class _FallbackSB:
    def __init__(self, sink):
        self.sink = sink
        self.calls: dict = {}

    def table(self, name):
        return _FallbackQuery(self, name)


class _FallbackStore:
    def __init__(self, sink):
        self.sink = sink

    def is_configured(self):
        return True

    async def get_service_client(self):
        return _FallbackSB(self.sink)


class WinrateExcessColumnMissingTests:
    def test_reco_read_falls_back_when_v14_not_run(self, monkeypatch):
        """v14 迁移未跑（excess_return 列不存在）时，读路径必须静默降级到旧字段，
        不能把「列不存在」显示成「推荐记录查询失败」、把整个推荐块打空。"""
        sink = {
            "prediction_records": [{"direction": "up", "hit": True}, {"direction": "down", "hit": False}],
            "daily_recommendations": [{"hit": True, "source": "llm"}, {"hit": False, "source": "rule"}],
            "winrate_snapshot": [{"snapshot_date": "2026-09-21", "prediction_rate": 50.0, "recommend_rate": 50.0}],
        }
        monkeypatch.setattr(W, "supabase_store", _FallbackStore(sink))
        out = _run(W.get_winrate_stats())
        assert out["recommendation"]["error"] is None
        assert out["recommendation"]["total"] == 2
        # 降级后超额口径不可信：显式标记 unavailable，前端据此回退旧「次日胜率」。
        assert out["recommendation"]["benchmark_available"] is False
        assert out["recommendation"]["excess_hit_rate"] is None


class _V16MissingQuery(_FallbackQuery):
    def select(self, *cols, **_kwargs):
        self.sb.selected.setdefault(self.name, []).append(cols)
        self._cols = cols
        return self

    async def execute(self):
        if self.name == "daily_recommendations" and any(
            "execution_status" in str(col) for col in getattr(self, "_cols", ())
        ):
            raise RuntimeError(
                "Could not find the 'execution_status' column of 'daily_recommendations' in the schema cache"
            )
        return type("R", (), {"data": self.sb.sink.get(self.name, [])})()


class _V16MissingSB(_FallbackSB):
    def __init__(self, sink):
        super().__init__(sink)
        self.selected: dict = {}

    def table(self, name):
        return _V16MissingQuery(self, name)


class _V16MissingStore:
    def __init__(self, sink):
        self.sb = _V16MissingSB(sink)

    def is_configured(self):
        return True

    async def get_service_client(self):
        return self.sb


class WinrateExecutionColumnMissingTests:
    def test_v16_missing_keeps_v14_excess_metrics(self, monkeypatch):
        """只缺 v16 时不能把已经存在的 v14 超额收益能力一起丢掉。"""
        sink = {
            "prediction_records": [],
            "daily_recommendations": [
                {"hit": True, "source": "rule", "excess_return": 1.25}
            ],
            "winrate_snapshot": [],
        }
        store = _V16MissingStore(sink)
        monkeypatch.setattr(W, "supabase_store", store)

        out = _run(W.get_winrate_stats())

        assert out["recommendation"]["error"] is None
        assert out["recommendation"]["benchmark_available"] is True
        assert out["recommendation"]["avg_excess_return"] == 1.25
        selected = store.sb.selected["daily_recommendations"]
        assert any("excess_return" in str(cols) for cols in selected[1:])


class DailyCronIsolationTests:
    def test_prediction_failure_does_not_skip_recommendation_settlement(self, monkeypatch):
        calls: list[str] = []

        async def fail_predictions():
            calls.append("prediction")
            raise RuntimeError("prediction source down")

        async def settle_recommendations():
            calls.append("recommendation")
            return 3

        async def stats():
            calls.append("stats")
            return {"ok": True}

        monkeypatch.setattr(W.market_prediction, "settle_predictions", fail_predictions)
        monkeypatch.setattr(W, "settle_daily_recommendations", settle_recommendations)
        monkeypatch.setattr(W, "get_winrate_stats", stats)

        result = _run(W.run_daily_cron())

        assert calls == ["prediction", "recommendation", "stats"]
        assert result["ok"] is False
        assert result["settled_recommendations"] == 3
        assert "settled_predictions" in result["errors"]

    def test_recommendation_failure_does_not_skip_stats_read(self, monkeypatch):
        calls: list[str] = []

        async def settle_predictions():
            calls.append("prediction")
            return 2

        async def fail_recommendations():
            calls.append("recommendation")
            raise RuntimeError("recommendation DB down")

        async def stats():
            calls.append("stats")
            return {"ok": True}

        monkeypatch.setattr(W.market_prediction, "settle_predictions", settle_predictions)
        monkeypatch.setattr(W, "settle_daily_recommendations", fail_recommendations)
        monkeypatch.setattr(W, "get_winrate_stats", stats)

        result = _run(W.run_daily_cron())

        assert calls == ["prediction", "recommendation", "stats"]
        assert result["ok"] is False
        assert result["settled_predictions"] == 2
        assert result["stats"] == {"ok": True}
        assert "settled_recommendations" in result["errors"]
