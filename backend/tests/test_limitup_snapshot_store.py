"""涨停池每日落库（limitup_service.save_daily_snapshot / load_accumulated_snapshots）测试。

钉死三类错误：

1. **行映射** —— normalize_limit_up 输出 → 落库行的字段对齐，缺值兜底；
2. **回测读路径补样本** —— 空池日期有累积数据时回补，统计窗口自积累；
3. **静默降级** —— Supabase 未配置 / 表未建不抛异常，实时链路不受影响。
"""
from __future__ import annotations

from app.services import limitup_service as L


class SnapshotRowTests:
    def test_row_contains_all_columns(self) -> None:
        stock = L.normalize_limit_up({
            "c": "003026", "n": "中晶科技", "p": 37000, "lbc": 3, "hybk": "半导体",
            "fbt": 93100, "lbt": 143000, "zbc": 1, "fund": 2e8, "ltsz": 5e9,
            "hs": 12.5, "amount": 5e8, "zdp": 9.98, "zttj": {"days": 5, "ct": 3},
        })
        rows = L._snapshot_rows("2026-09-17", [stock])
        assert len(rows) == 1
        row = rows[0]
        assert row["trade_date"] == "2026-09-17"
        assert row["code"] == "003026"
        assert row["name"] == "中晶科技"
        assert row["boards"] == 3
        assert row["sector"] == "半导体"
        assert row["seal_time"] == "09:31:00"
        assert abs(row["seal_fund_yi"] - 2.0) < 1e-6
        assert row["stat_days"] == 5
        assert row["stat_boards"] == 3

    def test_missing_values_fall_back(self) -> None:
        """缺值兜底：文本列空串、数值列 0，绝不能写 None 进 NOT NULL 列。"""
        rows = L._snapshot_rows("2026-09-17", [{"code": "600001", "name": None, "boards": None}])
        row = rows[0]
        assert row["name"] == ""
        assert row["boards"] == 0
        assert row["sector"] == ""

    def test_rows_without_code_are_dropped(self) -> None:
        rows = L._snapshot_rows("2026-09-17", [{"code": "", "name": "x"}, {"code": None}])
        assert rows == []

    def test_multiple_stocks(self) -> None:
        stocks = [{"code": "600001", "boards": 2}, {"code": "600002", "boards": 3}]
        rows = L._snapshot_rows("2026-09-17", stocks)
        assert [r["code"] for r in rows] == ["600001", "600002"]
        assert all(r["trade_date"] == "2026-09-17" for r in rows)


class AccumulatedBackfillTests:
    """relay_backtest 的读路径：空池日期用累积表补齐。"""

    def test_load_returns_empty_when_not_configured(self, monkeypatch):
        """Supabase 未配置 → 空 dict，调用方按「无累积样本」处理。"""
        monkeypatch.setattr(L, "supabase_store", None)
        import asyncio

        out = asyncio.get_event_loop().run_until_complete(L.load_accumulated_snapshots("2026-09-01", "2026-09-17"))
        assert out == {}

    def test_backfill_replaces_empty_dates(self, monkeypatch):
        """空池日期有落库数据 → 回补 per_day 并从 empty 里移除。"""
        # 直接测 relay_backtest 内部的补样本逻辑：mock 拉取返回空 + mock 累积表有数据
        import asyncio
        import datetime as dt

        d1, d2 = dt.date(2026, 9, 1), dt.date(2026, 9, 2)

        async def fake_completed(n):
            return [d1, d2]

        def fake_fetch(kind, date_str):
            return []  # 两天都空池（超回溯窗口）

        async def fake_load(start, end):
            return {d2.isoformat(): [{"code": "600001", "boards": 2, "sector": "S"}]}

        monkeypatch.setattr(L, "_completed_trading_days", fake_completed)
        monkeypatch.setattr(L, "_fetch_pool_sync", fake_fetch)
        monkeypatch.setattr(L, "load_accumulated_snapshots", fake_load)
        monkeypatch.setattr(L, "_RELAY_CACHE", {})

        out = asyncio.get_event_loop().run_until_complete(L.relay_backtest(days=5, force=True))

        # d2 有累积数据 → 有效；d1 无 → 仍 empty
        assert d2.isoformat() in str(out["data_window"])
        assert d1.isoformat() in out["empty_dates"]
        assert out["accumulated_days"] == 1
        # 累积样本参与统计：d2 的 600001 是当天唯一样本，d1 空 → 无对子，total=0
        assert out["total_samples"] == 0

    def test_backfill_off_when_nothing_saved(self, monkeypatch):
        """累积表没数据 → 行为与改动前完全一致（empty 原样）。"""
        import asyncio
        import datetime as dt

        d1, d2 = dt.date(2026, 9, 1), dt.date(2026, 9, 2)

        async def fake_completed(n):
            return [d1, d2]

        def fake_fetch(kind, date_str):
            return []

        async def fake_load(start, end):
            return {}

        monkeypatch.setattr(L, "_completed_trading_days", fake_completed)
        monkeypatch.setattr(L, "_fetch_pool_sync", fake_fetch)
        monkeypatch.setattr(L, "load_accumulated_snapshots", fake_load)
        monkeypatch.setattr(L, "_RELAY_CACHE", {})

        out = asyncio.get_event_loop().run_until_complete(L.relay_backtest(days=5, force=True))
        assert out["empty_dates"] == [d1.isoformat(), d2.isoformat()]
        assert out["accumulated_days"] == 0


class _FakeQuery:
    """记录 delete/lt 调用，execute 返回预设行数。"""

    def __init__(self, sink):
        self.sink = sink

    def delete(self):
        self.sink["op"] = "delete"
        return self

    def lt(self, col, value):
        self.sink.setdefault("filters", []).append(("lt", col, value))
        return self

    async def execute(self):
        if self.sink.get("raise"):
            raise RuntimeError("relation does not exist")
        return type("R", (), {"data": [{}] * self.sink.get("rows", 0)})()


class _FakeSB:
    def __init__(self, sink):
        self.sink = sink

    def table(self, name):
        self.sink["table"] = name
        return _FakeQuery(self.sink)


class _FakeStore:
    def __init__(self, sink, configured=True):
        self.sink = sink
        self.configured = configured

    def is_configured(self):
        return self.configured

    async def get_service_client(self):
        return _FakeSB(self.sink)


class PurgeOldSnapshotsTests:
    """保留窗口清理：只写不删会撞 Supabase 免费额度，而写失败是静默的。"""

    def test_not_configured_degrades_silently(self, monkeypatch):
        monkeypatch.setattr(L, "supabase_store", None)
        import asyncio

        assert asyncio.run(L.purge_old_snapshots()) == 0

    def test_cutoff_is_today_minus_default_retention(self, monkeypatch):
        import asyncio
        import datetime as dt

        sink: dict = {}
        monkeypatch.setattr(L, "supabase_store", _FakeStore(sink))
        fixed = dt.datetime(2026, 9, 20, 16, 5, tzinfo=dt.timezone(dt.timedelta(hours=8)))
        monkeypatch.setattr(L.trade_calendar_service, "now_cn", lambda: fixed)

        n = asyncio.run(L.purge_old_snapshots())

        assert sink["table"] == "limitup_daily_snapshot"
        assert sink["op"] == "delete"
        # 90 天保留 → 删除 2026-06-22 之前
        assert sink["filters"] == [("lt", "trade_date", "2026-06-22")]
        assert n == 0

    def test_retention_floor_blocks_whole_table_wipe(self, monkeypatch):
        """误传 0 / 负数不能清空全表 —— 那是不可逆的数据丢失。"""
        import asyncio
        import datetime as dt

        sink: dict = {}
        monkeypatch.setattr(L, "supabase_store", _FakeStore(sink))
        fixed = dt.datetime(2026, 9, 20, 16, 5, tzinfo=dt.timezone(dt.timedelta(hours=8)))
        monkeypatch.setattr(L.trade_calendar_service, "now_cn", lambda: fixed)

        for bad in (0, -5, "abc", None):
            sink.clear()
            asyncio.run(L.purge_old_snapshots(bad))  # type: ignore[arg-type]
            cutoff = sink["filters"][0][2]
            days_kept = (dt.date(2026, 9, 20) - dt.date.fromisoformat(cutoff)).days
            assert days_kept >= L._SNAPSHOT_MIN_RETENTION_DAYS, "%r 把窗口缩到了 %s 天" % (bad, days_kept)

    def test_returns_deleted_row_count(self, monkeypatch):
        import asyncio

        sink = {"rows": 7}
        monkeypatch.setattr(L, "supabase_store", _FakeStore(sink))
        assert asyncio.run(L.purge_old_snapshots()) == 7

    def test_table_missing_does_not_raise(self, monkeypatch):
        """表未建（需执行 v10 迁移）是预期内降级，不能拖垮 cron。"""
        import asyncio

        sink = {"raise": True}
        monkeypatch.setattr(L, "supabase_store", _FakeStore(sink))
        assert asyncio.run(L.purge_old_snapshots()) == 0

    def test_retention_default_is_at_least_the_floor(self):
        assert L._SNAPSHOT_RETENTION_DAYS >= L._SNAPSHOT_MIN_RETENTION_DAYS

    def test_daily_cron_wires_the_purge(self):
        """清理必须挂进每日 cron —— 写了函数没接线等于没写（本项目已踩过这类坑）。"""
        import pathlib

        cron_src = (
            pathlib.Path(__file__).resolve().parents[1] / "app" / "routes" / "cron.py"
        ).read_text(encoding="utf-8")
        assert "purge_old_snapshots" in cron_src, "每日 cron 没有调用快照清理"

