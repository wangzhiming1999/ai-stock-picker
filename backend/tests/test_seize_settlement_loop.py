"""抢封板收益闭环的调度接线与失败可见性测试。

背景（2026-10-14 实测）：闭环此前只在 ``GET /api/seize/history`` 里触发 —— 也就是
「用户打开抢板历史页」才跑；而且结算串行跑在请求路径里，失败只打一行 print。
结果：20 天 56 条落库、0 条结算、``next_open`` 恒空，页面却一切正常。

本文件钉死四件事：
1. **调度接线** —— 判定/结算必须挂在每日 cron，落库必须挂在盘中 monitor cron（源码级断言）；
2. **读路径无副作用** —— ``get_history_log`` 不得再触发判定/结算/雷达；
3. **失败可见** —— 结构化返回（attempted / settled / failed 分类 / errors），不再用 0 表示一切；
4. **降级不炸** —— Supabase 未配置 / 表未建时不抛异常。
"""
from __future__ import annotations

import asyncio
import datetime as dt
import pathlib
import re

from app.services import seize_service as S

_CN = dt.timezone(dt.timedelta(hours=8))


# ---------- 测试替身 ----------


class _R:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, sink):
        self.sink = sink
        self.mode = "select"

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def is_(self, *a, **k):
        return self

    @property
    def not_(self):
        return self

    def lt(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def update(self, payload):
        self.mode = "update"
        self.sink.setdefault("updates", []).append(payload)
        return self

    async def execute(self):
        if self.mode == "select":
            if self.sink.get("raise_select"):
                raise RuntimeError("relation does not exist")
            return _R(self.sink.get("select_rows", []))
        if self.sink.get("raise_update"):
            raise RuntimeError("write failed")
        return _R([{"id": 1}])


class _SB:
    def __init__(self, sink):
        self.sink = sink

    def table(self, name):
        self.sink["table"] = name
        return _Q(self.sink)


class _Store:
    def __init__(self, sink, configured=True):
        self.sink = sink
        self.configured = configured

    def is_configured(self):
        return self.configured

    async def get_service_client(self):
        return _SB(self.sink)


class _Hist:
    def __init__(self, dates, opens):
        self.dates = dates
        self.opens = opens


# ---------- _close_out_today ----------


def test_close_out_reports_storage_absence_instead_of_a_bare_zero(monkeypatch):
    monkeypatch.setattr(S, "supabase_store", None)
    out = asyncio.run(S._close_out_today("2026-10-13", {"600001"}))
    assert out["enabled"] is False
    assert out["updated"] == 0
    assert out["error"] == "storage_not_configured"


def test_close_out_marks_rows_against_the_final_pool(monkeypatch):
    sink = {"select_rows": [{"id": 1, "code": "600001"}, {"id": 2, "code": "600002"}]}
    monkeypatch.setattr(S, "supabase_store", _Store(sink))

    out = asyncio.run(S._close_out_today("2026-10-13", {"600001"}))

    assert out == {"enabled": True, "pending": 2, "updated": 2, "error": None}
    # 在池里的标 True、不在池里的标 False —— 判定依据必须是收盘后的最终池
    assert [u["sealed_final"] for u in sink["updates"]] == [True, False]


def test_close_out_query_failure_is_reported(monkeypatch):
    monkeypatch.setattr(S, "supabase_store", _Store({"raise_select": True}))
    out = asyncio.run(S._close_out_today("2026-10-13", {"600001"}))
    assert out["enabled"] is True
    assert out["updated"] == 0
    assert out["error"] and "RuntimeError" in out["error"]


# ---------- _realize_pending ----------


def _pending(code="600001", trade_date="2026-09-30", buy_price=10.0):
    return {"id": 1, "code": code, "trade_date": trade_date, "buy_price": buy_price}


def test_realize_settles_and_writes_next_open(monkeypatch):
    sink = {"select_rows": [_pending()]}
    monkeypatch.setattr(S, "supabase_store", _Store(sink))
    monkeypatch.setattr(
        S.data_service, "get_history",
        lambda code, days: _Hist(["2026-09-30", "2026-10-09"], [10.0, 10.8]),
    )

    out = asyncio.run(S._realize_pending("2026-10-14"))

    assert out["attempted"] == 1
    assert out["settled"] == 1
    assert out["failed"] == {}
    assert out["error"] is None
    payload = sink["updates"][0]
    assert payload["next_open"] == 10.8
    assert payload["realized_return_pct"] == 8.0


def test_realize_classifies_every_failure_reason(monkeypatch):
    """取数抛异常 / 返回空 / 找不到 D+1 开盘价必须分开计数 —— 旧的 `continue` 把三者混成 0。"""
    sink = {
        "select_rows": [
            _pending(code="600001", trade_date="2026-09-30"),
            _pending(code="600002", trade_date="2026-09-30"),
            _pending(code="600003", trade_date="2026-10-13"),
        ]
    }
    monkeypatch.setattr(S, "supabase_store", _Store(sink))

    def fake_history(code, days):
        if code == "600001":
            raise RuntimeError("source down")
        if code == "600002":
            return _Hist([], [])
        return _Hist(["2026-10-13"], [9.0])  # 之后没有交易日 → next_open_missing

    monkeypatch.setattr(S.data_service, "get_history", fake_history)

    out = asyncio.run(S._realize_pending("2026-10-14"))

    assert out["attempted"] == 3
    assert out["settled"] == 0
    assert out["failed"] == {
        "history_error:RuntimeError": 1,
        "history_empty": 1,
        "next_open_missing": 1,
    }


def test_realize_write_failure_is_counted_not_swallowed(monkeypatch):
    sink = {"select_rows": [_pending()], "raise_update": True}
    monkeypatch.setattr(S, "supabase_store", _Store(sink))
    monkeypatch.setattr(
        S.data_service, "get_history",
        lambda code, days: _Hist(["2026-09-30", "2026-10-09"], [10.0, 11.0]),
    )

    out = asyncio.run(S._realize_pending("2026-10-14"))

    assert out["settled"] == 0
    assert out["failed"] == {"update_error:RuntimeError": 1}


def test_realize_not_configured_degrades(monkeypatch):
    monkeypatch.setattr(S, "supabase_store", None)
    out = asyncio.run(S._realize_pending("2026-10-14"))
    assert out["enabled"] is False
    assert out["error"] == "storage_not_configured"


# ---------- settle_daily ----------


def test_settle_daily_surfaces_pool_failure_but_still_realizes(monkeypatch):
    """涨停池拿不到时：判定跳过并进 errors，历史结算照跑（两件事不该互相拖死）。"""
    async def boom(kind, date_str, retries=1):
        raise RuntimeError("push2ex timeout")

    called = {}

    async def fake_realize(today_iso, cap=30):
        called["realize"] = today_iso
        return {"enabled": True, "attempted": 0, "settled": 0, "failed": {}, "error": None}

    monkeypatch.setattr(S, "_fetch_pool", boom)
    monkeypatch.setattr(S, "_realize_pending", fake_realize)
    monkeypatch.setattr(S, "_cn_now", lambda: dt.datetime(2026, 10, 14, 15, 30, tzinfo=_CN))

    out = asyncio.run(S.settle_daily())

    assert out["trade_date"] == "2026-10-14"
    assert out["closed_out"] is None
    assert out["realized"]["settled"] == 0
    assert called["realize"] == "2026-10-14"
    assert out["errors"] and out["errors"][0].startswith("zt_pool:")


def test_settle_daily_runs_both_steps(monkeypatch):
    async def pool(kind, date_str, retries=1):
        return [{"c": "600001", "n": "A", "p": 10000, "lbc": 1, "hybk": "S", "fbt": 100000}]

    async def close_out(trade_date, zt_codes):
        return {"enabled": True, "pending": 1, "updated": 1, "error": None}

    async def realize(today_iso, cap=30):
        return {"enabled": True, "attempted": 4, "settled": 3, "failed": {"history_empty": 1}, "error": None}

    monkeypatch.setattr(S, "_fetch_pool", pool)
    monkeypatch.setattr(S, "_close_out_today", close_out)
    monkeypatch.setattr(S, "_realize_pending", realize)
    monkeypatch.setattr(S, "_cn_now", lambda: dt.datetime(2026, 10, 14, 15, 30, tzinfo=_CN))

    out = asyncio.run(S.settle_daily())

    assert out["closed_out"]["updated"] == 1
    assert out["realized"]["settled"] == 3
    assert out["realized"]["failed"] == {"history_empty": 1}
    assert out["errors"] == []


# ---------- ingest_intraday ----------


def test_ingest_skips_when_market_closed(monkeypatch):
    monkeypatch.setattr(S, "_cn_now", lambda: dt.datetime(2026, 10, 14, 20, 0, tzinfo=_CN))
    out = asyncio.run(S.ingest_intraday())
    assert out["ok"] is True
    assert out["skipped"] == "market_closed"


def test_ingest_reuses_radar_during_market_hours(monkeypatch):
    monkeypatch.setattr(S, "_cn_now", lambda: dt.datetime(2026, 10, 14, 10, 0, tzinfo=_CN))

    async def fake_radar(force=False):
        return {"trade_date": "2026-10-14", "session": "早盘", "counts": {"just_sealed": 2, "reseal": 3}}

    monkeypatch.setattr(S, "get_radar", fake_radar)
    out = asyncio.run(S.ingest_intraday())

    assert out["ok"] is True
    assert out["counts"] == {"just_sealed": 2, "reseal": 3}


def test_ingest_reports_radar_failure(monkeypatch):
    monkeypatch.setattr(S, "_cn_now", lambda: dt.datetime(2026, 10, 14, 10, 0, tzinfo=_CN))

    async def boom(force=False):
        raise RuntimeError("涨停池获取失败")

    monkeypatch.setattr(S, "get_radar", boom)
    out = asyncio.run(S.ingest_intraday())
    assert out["ok"] is False
    assert "RuntimeError" in out["error"]


# ---------- 源码级守卫（本项目已多次踩「写了函数没接线」） ----------


def _cron_src() -> str:
    return (
        pathlib.Path(__file__).resolve().parents[1] / "app" / "routes" / "cron.py"
    ).read_text(encoding="utf-8")


def _seize_src() -> str:
    return (
        pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "seize_service.py"
    ).read_text(encoding="utf-8")


def test_daily_cron_wires_seize_settlement():
    """判定 + D+1 结算必须由每日 cron 驱动 —— 这正是它缺席三周的那一步。"""
    assert re.search(r"seize_service\.settle_daily\s*\(", _cron_src()), "每日 cron 没有调用抢封板结算"


def test_monitor_cron_wires_seize_ingest():
    """盘中落库必须由 monitor cron 驱动，否则没人打开「抢板」页的交易日就没有样本。"""
    assert re.search(r"seize_service\.ingest_intraday\s*\(", _cron_src()), "盘中 cron 没有调用抢封板落库"


def test_history_read_path_has_no_settlement_side_effects():
    """GET 读路径不得再触发判定 / 结算 / 雷达 —— 重副作用跑在请求里就是静默三周的根因。"""
    src = _seize_src()
    body = src.split("async def get_history_log(", 1)[1]
    body = body.split("\n# ----------", 1)[0]
    for forbidden in ("_close_out_today(", "_realize_pending(", "get_radar("):
        assert forbidden not in body, f"get_history_log 仍在调用 {forbidden}"
