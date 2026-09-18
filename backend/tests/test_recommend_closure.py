"""推荐/四维榜结算闭环落库的守卫测试。

背景：两条推荐链路都没有结算闭环 —— quad 快照只写 quad_snapshots（结算只读
daily_recommendations），空推荐日提前 return 不落库 → 「推荐链路质量差」在系统
内部不可见。本文件锁定：
1. 四维榜 Top10 必须落 daily_recommendations（source='quad'）接入结算；
2. 空推荐日的观察层必须落库（source='watch'）；
3. 落库幂等：同日已有行不重复写；
4. 表未建/未配置时静默降级，不抛异常拖垮主链路。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import quad_service, recommend_service


class _Table:
    """PostgREST 链式调用的最小替身：记录调用并返回预置行。"""

    def __init__(self, store: dict, name: str):
        self._store = store
        self._name = name
        self._filters: list[tuple] = []
        self._pending_insert = None

    def select(self, *_cols):
        return self

    def eq(self, _col, _val):
        self._filters.append(("eq", _col, _val))
        return self

    async def execute(self):
        rows = self._store.get(self._name, [])
        data = rows
        if self._pending_insert is not None:
            self._store.setdefault(self._name, []).extend(self._pending_insert)
            data = self._pending_insert
            self._pending_insert = None
        return SimpleNamespace(data=data)

    # insert 由 _Client 层截获（见下），这里只兜底

    def insert(self, rows):
        self._pending_insert = rows
        return self


def _make_client(store: dict):
    class _Client:
        def table(self, name: str) -> _Table:
            return _Table(store, name)

    async def _get():
        return _Client()

    return _get


def _configured(monkeypatch, store: dict) -> None:
    monkeypatch.setattr(quad_service.supabase_store, "is_configured", lambda: True)
    monkeypatch.setattr(quad_service.supabase_store, "get_service_client", _make_client(store))


def _quad_result() -> dict:
    return {
        "date": "2026-09-18",
        "items": [
            {"code": f"60000{i}", "name": f"股{i}", "price": 10.0 + i, "rank": i + 1, "overall_score": 7.5}
            for i in range(3)
        ],
    }


class TestQuadToRecommendations:
    @pytest.mark.asyncio
    async def test_quad_top10_lands_in_daily_recommendations(self, monkeypatch) -> None:
        store: dict = {"daily_recommendations": []}
        _configured(monkeypatch, store)

        saved = await quad_service._save_quad_to_recommendations("2026-09-18", _quad_result())

        assert saved == 3
        rows = store["daily_recommendations"]
        assert all(r["source"] == "quad" for r in rows)
        assert rows[0]["rec_date"] == "2026-09-18"
        assert rows[0]["recommend_price"] == 10.0
        assert "四维榜" in rows[0]["reason"]

    @pytest.mark.asyncio
    async def test_quad_save_is_idempotent(self, monkeypatch) -> None:
        store: dict = {"daily_recommendations": []}
        _configured(monkeypatch, store)

        await quad_service._save_quad_to_recommendations("2026-09-18", _quad_result())
        saved = await quad_service._save_quad_to_recommendations("2026-09-18", _quad_result())

        assert saved == 0
        assert len(store["daily_recommendations"]) == 3

    @pytest.mark.asyncio
    async def test_quad_save_skips_codes_already_recommended(self, monkeypatch) -> None:
        """同日推荐链路已落的票不重复记（幂等键是 code 不是 source）。"""
        store: dict = {"daily_recommendations": [{"code": "600000"}]}
        _configured(monkeypatch, store)

        saved = await quad_service._save_quad_to_recommendations("2026-09-18", _quad_result())

        assert saved == 2  # 600000 已存在
        codes = [r["code"] for r in store["daily_recommendations"]]
        assert codes.count("600000") == 1

    @pytest.mark.asyncio
    async def test_quad_save_degrades_silently_when_table_missing(self, monkeypatch) -> None:
        class _Boom:
            def table(self, *_a, **_k):
                raise RuntimeError('relation "daily_recommendations" does not exist')

        async def boom():
            return _Boom()

        monkeypatch.setattr(quad_service.supabase_store, "is_configured", lambda: True)
        monkeypatch.setattr(quad_service.supabase_store, "get_service_client", boom)

        saved = await quad_service._save_quad_to_recommendations("2026-09-18", _quad_result())

        assert saved == 0  # 静默降级，不抛异常

    @pytest.mark.asyncio
    async def test_quad_save_skips_items_without_price(self, monkeypatch) -> None:
        """没有价格的条目不能进结算闭环（结算需要基准价）。"""
        store: dict = {"daily_recommendations": []}
        _configured(monkeypatch, store)
        result = _quad_result()
        result["items"].append({"code": "600009", "name": "无价股", "price": None, "rank": 4})

        saved = await quad_service._save_quad_to_recommendations("2026-09-18", result)

        assert saved == 3


class TestWatchlistSave:
    def _watchlist(self) -> list[dict]:
        return [
            {"code": "00000{i}".format(i=i), "name": f"观察{i}", "price": 8.0 + i, "score": 4.2, "status": "动量不足"}
            for i in range(2)
        ]

    @pytest.mark.asyncio
    async def test_empty_day_watchlist_lands_with_watch_source(self, monkeypatch) -> None:
        store: dict = {"daily_recommendations": []}
        monkeypatch.setattr(recommend_service.supabase_store, "is_configured", lambda: True)
        monkeypatch.setattr(recommend_service.supabase_store, "get_service_client", _make_client(store))

        saved = await recommend_service.save_watchlist("2026-09-18", self._watchlist())

        assert saved == 2
        rows = store["daily_recommendations"]
        assert all(r["source"] == "watch" for r in rows)
        assert rows[0]["reason"] == "动量不足"  # 存拦截原因，不存买入文案

    @pytest.mark.asyncio
    async def test_watchlist_save_is_idempotent(self, monkeypatch) -> None:
        store: dict = {"daily_recommendations": []}
        monkeypatch.setattr(recommend_service.supabase_store, "is_configured", lambda: True)
        monkeypatch.setattr(recommend_service.supabase_store, "get_service_client", _make_client(store))

        await recommend_service.save_watchlist("2026-09-18", self._watchlist())
        saved = await recommend_service.save_watchlist("2026-09-18", self._watchlist())

        assert saved == 0
        assert len(store["daily_recommendations"]) == 2

    @pytest.mark.asyncio
    async def test_watchlist_skipped_when_recommendations_exist(self, monkeypatch) -> None:
        """同日已有推荐行：观察层不再落（避免同票双行搅浑口径）。"""
        store: dict = {"daily_recommendations": [{"code": "000000"}]}
        monkeypatch.setattr(recommend_service.supabase_store, "is_configured", lambda: True)
        monkeypatch.setattr(recommend_service.supabase_store, "get_service_client", _make_client(store))

        saved = await recommend_service.save_watchlist("2026-09-18", self._watchlist())

        assert saved == 1  # 只有 000001（000000 已存在）

    @pytest.mark.asyncio
    async def test_watchlist_degrades_silently(self, monkeypatch) -> None:
        class _Boom:
            def table(self, *_a, **_k):
                raise RuntimeError('relation "daily_recommendations" does not exist')

        async def boom():
            return _Boom()

        monkeypatch.setattr(recommend_service.supabase_store, "is_configured", lambda: True)
        monkeypatch.setattr(recommend_service.supabase_store, "get_service_client", boom)

        saved = await recommend_service.save_watchlist("2026-09-18", self._watchlist())

        assert saved == 0
