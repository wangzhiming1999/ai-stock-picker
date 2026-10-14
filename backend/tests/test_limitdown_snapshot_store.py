"""跌停池每日落库（limitdown_service.save_daily_snapshot / load_accumulated_snapshots）测试。

与涨停池（test_limitup_snapshot_store.py）对称，钉死三类错误：

1. **行映射** —— normalize_limit_down 输出 → 落库行的字段对齐，缺值兜底；
2. **回测读路径补样本** —— 空池日期有累积数据时回补，repair_backtest 窗口自积累；
3. **静默降级** —— Supabase 未配置 / 表未建不抛异常，实时链路不受影响。

⚠️ 跌停侧特有的两个坑（照抄涨停池会错）：
  · 字段名不同：``down_days``（不是 boards）、``last_seal_time``（跌停池没有 fbt 首封时间）；
  · ``seal_ratio`` 语义相反：涨停封单厚＝买盘强，跌停封单厚＝**卖不掉**。
"""
from __future__ import annotations

import asyncio
import datetime as dt

from app.services import limitdown_service as D


class SnapshotRowTests:
    def test_row_contains_all_columns(self) -> None:
        stock = D.normalize_limit_down({
            "c": "603668", "n": "天马科技", "p": 8470, "days": 2, "hybk": "饲料",
            "lbt": 92502, "fba": 4.665e8, "ltsz": 42.84e8,
            "hs": 0.47, "amount": 1.99e7, "zdp": -9.99,
        })
        rows = D._snapshot_rows("2026-10-13", [stock])
        assert len(rows) == 1
        row = rows[0]
        assert row["trade_date"] == "2026-10-13"
        assert row["code"] == "603668"
        assert row["name"] == "天马科技"
        assert row["down_days"] == 2
        assert row["sector"] == "饲料"
        assert row["last_seal_time"] == "09:25:02"
        assert abs(row["seal_fund_yi"] - 4.665) < 1e-6
        assert abs(row["price"] - 8.47) < 1e-6

    def test_columns_match_the_migration_contract(self) -> None:
        """落库列集合必须与 v19 表结构一致，多/少一列都会在 upsert 时静默失败或报错。"""
        assert set(D._SNAPSHOT_COLUMNS) == {
            "code", "name", "price", "change_pct", "down_days", "last_seal_time",
            "seal_fund_yi", "float_mv_yi", "seal_ratio", "turnover", "amount_yi", "sector",
        }

    def test_missing_values_fall_back(self) -> None:
        """缺值兜底：文本列空串、数值列 0，绝不能写 None 进 NOT NULL 列。"""
        rows = D._snapshot_rows("2026-10-13", [{"code": "600001", "name": None, "down_days": None}])
        row = rows[0]
        assert row["name"] == ""
        assert row["down_days"] == 0
        assert row["sector"] == ""
        assert row["last_seal_time"] == ""

    def test_rows_without_code_are_dropped(self) -> None:
        rows = D._snapshot_rows("2026-10-13", [{"code": "", "name": "x"}, {"code": None}])
        assert rows == []

    def test_derived_display_fields_are_not_written(self) -> None:
        """get_snapshot 传进来的是挂了 position 的 decorated 行 —— 派生字段不得进表。"""
        rows = D._snapshot_rows(
            "2026-10-13",
            [{"code": "600001", "name": "x", "position": {"tag": "连跌"}, "down_days": 2}],
        )
        assert "position" not in rows[0]


class AccumulatedBackfillTests:
    """repair_backtest 的读路径：空池日期用累积表补齐。"""

    def test_load_returns_empty_when_not_configured(self, monkeypatch):
        """Supabase 未配置 → 空 dict，调用方按「无累积样本」处理。"""
        monkeypatch.setattr(D, "supabase_store", None)
        out = asyncio.run(D.load_accumulated_snapshots("2026-09-01", "2026-09-17"))
        assert out == {}

    def _patch_repair(self, monkeypatch, days, fetch, load):
        monkeypatch.setattr(D, "_completed_trading_days", days)
        monkeypatch.setattr(D, "_fetch_pool_sync", fetch)
        monkeypatch.setattr(D, "load_accumulated_snapshots", load)
        # 日 K 一律取不到 → 样本进不了统计行，但「补没补进 per_day」仍可断言
        monkeypatch.setattr(D, "get_history", lambda code, n: None)
        monkeypatch.setattr(D, "_REPAIR_CACHE", {})

    def test_backfill_replaces_empty_dates(self, monkeypatch):
        """空池日期有落库数据 → 回补 per_day 并从 empty 里移除。"""
        d1, d2 = dt.date(2026, 9, 1), dt.date(2026, 9, 2)

        async def fake_completed(n):
            return [d1, d2]

        def fake_fetch(endpoint, sort, date_str):
            return []  # 两天都空池（超回溯窗口）

        async def fake_load(start, end):
            return {d2.isoformat(): [{"code": "600001", "name": "x", "sector": "S", "down_days": 1}]}

        self._patch_repair(monkeypatch, fake_completed, fake_fetch, fake_load)
        out = asyncio.run(D.repair_backtest(days=5, force=True))

        assert out["accumulated_days"] == 1
        assert d2.isoformat() not in out["empty_dates"]
        assert out["empty_dates"] == [d1.isoformat()]
        # 累积样本进了候选集（未补前 candidate_size 会是 0）
        assert out["candidate_size"] == 1

    def test_backfill_off_when_nothing_saved(self, monkeypatch):
        """累积表没数据 → 行为与改动前完全一致（empty 原样、accumulated_days=0）。"""
        d1, d2 = dt.date(2026, 9, 1), dt.date(2026, 9, 2)

        async def fake_completed(n):
            return [d1, d2]

        def fake_fetch(endpoint, sort, date_str):
            return []

        async def fake_load(start, end):
            return {}

        self._patch_repair(monkeypatch, fake_completed, fake_fetch, fake_load)
        out = asyncio.run(D.repair_backtest(days=5, force=True))

        assert out["empty_dates"] == [d1.isoformat(), d2.isoformat()]
        assert out["accumulated_days"] == 0
        assert out["candidate_size"] == 0

    def test_backfill_only_touches_empty_dates(self, monkeypatch):
        """接口正常返回的日期不得被累积表覆盖 —— 累积表是补空，不是替换实时数据。"""
        d1 = dt.date(2026, 9, 1)

        async def fake_completed(n):
            return [d1]

        def fake_fetch(endpoint, sort, date_str):
            if endpoint == D._DT_ENDPOINT:
                return [{"c": "600001", "n": "live", "days": 1, "hybk": "实时", "p": 1000}]
            return []

        load_called = {"n": 0}

        async def fake_load(start, end):
            load_called["n"] += 1
            return {d1.isoformat(): [{"code": "600001", "name": "stale"}]}

        self._patch_repair(monkeypatch, fake_completed, fake_fetch, fake_load)
        out = asyncio.run(D.repair_backtest(days=5, force=True))

        assert load_called["n"] == 0, "没有空池日期时不该去读累积表"


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
        monkeypatch.setattr(D, "supabase_store", None)
        assert asyncio.run(D.purge_old_snapshots()) == 0

    def test_cutoff_is_today_minus_default_retention(self, monkeypatch):
        sink: dict = {}
        monkeypatch.setattr(D, "supabase_store", _FakeStore(sink))
        fixed = dt.datetime(2026, 10, 13, 16, 5, tzinfo=dt.timezone(dt.timedelta(hours=8)))
        monkeypatch.setattr(D.trade_calendar_service, "now_cn", lambda: fixed)

        n = asyncio.run(D.purge_old_snapshots())

        assert sink["table"] == "limitdown_daily_snapshot"
        assert sink["op"] == "delete"
        # 90 天保留 → 删除 2026-07-15 之前
        assert sink["filters"] == [("lt", "trade_date", "2026-07-15")]
        assert n == 0

    def test_retention_floor_blocks_whole_table_wipe(self, monkeypatch):
        """误传 0 / 负数不能清空全表 —— 那是不可逆的数据丢失。"""
        sink: dict = {}
        monkeypatch.setattr(D, "supabase_store", _FakeStore(sink))
        fixed = dt.datetime(2026, 10, 13, 16, 5, tzinfo=dt.timezone(dt.timedelta(hours=8)))
        monkeypatch.setattr(D.trade_calendar_service, "now_cn", lambda: fixed)

        for bad in (0, -5, "abc", None):
            sink.clear()
            asyncio.run(D.purge_old_snapshots(bad))  # type: ignore[arg-type]
            cutoff = sink["filters"][0][2]
            days_kept = (dt.date(2026, 10, 13) - dt.date.fromisoformat(cutoff)).days
            assert days_kept >= D._SNAPSHOT_MIN_RETENTION_DAYS, "%r 把窗口缩到了 %s 天" % (bad, days_kept)

    def test_returns_deleted_row_count(self, monkeypatch):
        sink = {"rows": 7}
        monkeypatch.setattr(D, "supabase_store", _FakeStore(sink))
        assert asyncio.run(D.purge_old_snapshots()) == 7

    def test_table_missing_does_not_raise(self, monkeypatch):
        """表未建（需执行 v19 迁移）是预期内降级，不能拖垮 cron。"""
        sink = {"raise": True}
        monkeypatch.setattr(D, "supabase_store", _FakeStore(sink))
        assert asyncio.run(D.purge_old_snapshots()) == 0

    def test_retention_default_is_at_least_the_floor(self):
        assert D._SNAPSHOT_RETENTION_DAYS >= D._SNAPSHOT_MIN_RETENTION_DAYS

    def test_daily_cron_wires_the_purge(self):
        """清理必须挂进每日 cron —— 写了函数没接线等于没写（本项目已踩过这类坑）。

        ⚠️ 判据必须带调用签名：只查 `"...purge_old_snapshots" in src` 是**前缀匹配**，
        把调用改名成 `purge_old_snapshots_TYPO()` 也照样「通过」（本测试的探针验证
        实测踩到过）—— 那种断言等于没有。
        """
        import pathlib
        import re

        cron_src = (
            pathlib.Path(__file__).resolve().parents[1] / "app" / "routes" / "cron.py"
        ).read_text(encoding="utf-8")
        assert re.search(
            r"limitdown_service\.purge_old_snapshots\s*\(", cron_src
        ), "每日 cron 没有调用跌停池快照清理"
        assert re.search(
            r"limitdown_service\.save_daily_snapshot\s*\(", cron_src
        ), "每日 cron 没有调用跌停池落库"


class SaveDailySnapshotTests:
    """写路径：幂等 upsert、未配置降级、表未建不抛异常。"""

    def test_not_configured_returns_zero(self, monkeypatch):
        monkeypatch.setattr(D, "supabase_store", None)
        assert asyncio.run(D.save_daily_snapshot("2026-10-13", [{"code": "600001"}])) == 0

    def test_upsert_targets_the_right_table_and_conflict_key(self, monkeypatch):
        sink: dict = {}

        class _Q:
            async def execute(self):
                return type("R", (), {"data": [{"id": 1}, {"id": 2}]})()

        class _SB:
            def table(self, name):
                sink["table"] = name
                return self

            def upsert(self, rows, on_conflict=None):
                sink["rows"] = rows
                sink["on_conflict"] = on_conflict
                return _Q()

        class _Store:
            def is_configured(self):
                return True

            async def get_service_client(self):
                return _SB()

        monkeypatch.setattr(D, "supabase_store", _Store())
        n = asyncio.run(D.save_daily_snapshot("2026-10-13", [{"code": "600001", "down_days": 2}]))

        assert sink["table"] == "limitdown_daily_snapshot"
        assert sink["on_conflict"] == "trade_date,code"
        assert sink["rows"][0]["trade_date"] == "2026-10-13"
        assert n == 2

    def test_empty_pool_writes_nothing(self, monkeypatch):
        """当日零跌停 → 不写库（避免造空行 / 无谓请求）。"""
        called = {"n": 0}

        class _Store:
            def is_configured(self):
                return True

            async def get_service_client(self):
                called["n"] += 1
                return None

        monkeypatch.setattr(D, "supabase_store", _Store())
        assert asyncio.run(D.save_daily_snapshot("2026-10-13", [])) == 0
        assert called["n"] == 0

    def test_table_missing_does_not_raise(self, monkeypatch):
        class _Q:
            async def execute(self):
                raise RuntimeError('relation "limitdown_daily_snapshot" does not exist')

        class _SB:
            def table(self, name):
                return self

            def upsert(self, rows, on_conflict=None):
                return _Q()

        class _Store:
            def is_configured(self):
                return True

            async def get_service_client(self):
                return _SB()

        monkeypatch.setattr(D, "supabase_store", _Store())
        assert asyncio.run(D.save_daily_snapshot("2026-10-13", [{"code": "600001"}])) == 0


class AccumulatedStatsTests:
    """观察期读数：三种降级状态必须能区分（配置问题 vs 迁移没跑）。"""

    def test_not_configured_says_why(self, monkeypatch):
        monkeypatch.setattr(D, "supabase_store", None)
        out = asyncio.run(D.accumulated_stats())
        assert out["note"] == "supabase_not_configured"
        assert out["days"] == 0

    def test_table_missing_is_not_confused_with_not_configured(self, monkeypatch):
        class _Q:
            async def execute(self):
                raise RuntimeError('relation "limitdown_daily_snapshot" does not exist')

        class _SB:
            def table(self, name):
                return self

            def select(self, cols):
                return self

            def limit(self, n):
                return self

            async def execute(self):
                return await _Q().execute()

        class _Store:
            def is_configured(self):
                return True

            async def get_service_client(self):
                return _SB()

        monkeypatch.setattr(D, "supabase_store", _Store())
        out = asyncio.run(D.accumulated_stats())
        assert out["configured"] is True
        assert out["note"] == "table_missing"

    def test_counts_distinct_days(self, monkeypatch):
        class _Q:
            async def execute(self):
                return type("R", (), {"data": [
                    {"trade_date": "2026-10-12"}, {"trade_date": "2026-10-12"},
                    {"trade_date": "2026-10-13"},
                ]})()

        class _SB:
            def table(self, name):
                return self

            def select(self, cols):
                return self

            def limit(self, n):
                return self

            async def execute(self):
                return await _Q().execute()

        class _Store:
            def is_configured(self):
                return True

            async def get_service_client(self):
                return _SB()

        monkeypatch.setattr(D, "supabase_store", _Store())
        out = asyncio.run(D.accumulated_stats())
        assert out["days"] == 2
        assert out["rows"] == 3
        assert out["first_date"] == "2026-10-12"
        assert out["last_date"] == "2026-10-13"
