"""推荐结算批量隔离回归：单只取数异常 / 单行结算异常不得清空全天结算。

背景（2026-10-06）：生产 `daily_recommendations` 累计 231 行待结算、0 行已结算，
连续 31 天。旧实现里历史 K 线批量取数走 `gather_limited(return_exceptions=False)`，
任何单只异常（如某行 code 非字符串 → `_code_to_symbol` 抛 TypeError）都会让整批
结算当场终止；而触发异常的那一行自身也永远结算不了 —— 形成无报错的「永久 0 结算」
死锁。同时整条链路不打印任何一行诊断，运维在 Vercel 日志里看不到现场。
"""
from __future__ import annotations

import asyncio
import datetime as dt

from app.models import StockHistory
from app.services import winrate_service as W


def _run(coro):
    """复用线程已有事件循环，避免 asyncio.run() 污染其它测试。"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# 推荐日 09-04 的次一交易日 09-07 收盘 11.0：legacy 口径下 10.0 → 11.0
HIST = StockHistory(
    dates=["2026-09-04", "2026-09-07"],
    opens=[10.0, 10.2],
    highs=[10.2, 11.2],
    lows=[9.8, 9.9],
    closes=[10.0, 11.0],
)


class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, client, table):
        self.client = client
        self.table = table
        self.op = "select"
        self.payload = None
        self.filters: dict = {}

    def select(self, *_a, **_k):
        self.op = "select"
        return self

    def update(self, payload):
        self.op = "update"
        self.payload = payload
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def is_(self, *_a, **_k):
        return self

    def lt(self, *_a, **_k):
        return self

    async def execute(self):
        if self.op == "update":
            row_id = self.filters.get("id")
            self.client.updates.append((row_id, self.payload))
            if row_id in self.client.update_fail_ids:
                raise RuntimeError("update rejected by constraint")
            return _Resp([self.payload])
        if self.table in self.client.select_fail_tables:
            raise RuntimeError(f"column {self.table}.unexpected does not exist")
        return _Resp(self.client.rows.get(self.table, []))


class _Client:
    def __init__(self, rows):
        self.rows = {"daily_recommendations": rows}
        self.updates: list = []
        self.update_fail_ids: set = set()
        self.select_fail_tables: set = set()

    def table(self, name):
        return _Query(self, name)


class _Store:
    def __init__(self, client):
        self._client = client

    def is_configured(self):
        return True

    async def get_service_client(self):
        return self._client


class _Calendar:
    @staticmethod
    async def last_trading_day():
        return dt.date(2026, 9, 30)  # 国庆假期内：最近交易日为 09-30


def _row(row_id, code, rec_date="2026-09-04", price=10.0, expected=None):
    return {
        "id": row_id,
        "code": code,
        "rec_date": rec_date,
        "recommend_price": price,
        "expected_price": expected,
        "execution_status": None,
        "entry_price": None,
    }


def _setup(monkeypatch, rows, *, raise_for=(), none_for=(), update_fail_ids=()):
    client = _Client(rows)
    client.update_fail_ids = set(update_fail_ids)
    refresh_calls = {"n": 0}

    def fake_history(code, days=200, **_kw):
        if code in raise_for:
            raise TypeError("脏 code：模拟 _code_to_symbol 抛错")
        if code in none_for:
            return None
        return HIST

    async def fake_refresh():
        refresh_calls["n"] += 1

    monkeypatch.setattr(W, "supabase_store", _Store(client))
    monkeypatch.setattr(W, "trade_calendar_service", _Calendar())
    monkeypatch.setattr(W.data_service, "get_history", fake_history)
    monkeypatch.setattr(W, "refresh_winrate_snapshot", fake_refresh)
    return client, refresh_calls


class SettlementIsolationTests:
    def test_poison_fetch_does_not_kill_batch(self, monkeypatch, capsys):
        """单只取数抛异常 + 一行 null code：其余行必须照常结算（旧实现整批中断）。"""
        rows = [_row(1, "000001"), _row(2, "600000"), _row(3, None)]
        client, refresh = _setup(monkeypatch, rows, raise_for=("000001",))

        settled = _run(W.settle_daily_recommendations())

        assert settled == 1, "只有 600000 可结算；旧实现会在这里直接抛错"
        settled_ids = [row_id for row_id, _fields in client.updates]
        assert settled_ids == [2]
        assert refresh["n"] == 1
        out = capsys.readouterr().out
        assert "hist_err=1" in out
        assert "skip_no_history=2" in out  # 000001（取数炸）+ null code 各一行
        assert "settled=1" in out

    def test_row_update_failure_is_isolated(self, monkeypatch, capsys):
        """单行写入失败只计 row_errors，其它行照常结算。"""
        rows = [_row(1, "000001"), _row(2, "600000")]
        client, _refresh = _setup(monkeypatch, rows, update_fail_ids=(1,))

        settled = _run(W.settle_daily_recommendations())

        assert settled == 1
        assert [row_id for row_id, _f in client.updates] == [1, 2]
        out = capsys.readouterr().out
        assert "row_errors=1" in out
        assert "settled=1" in out

    def test_all_history_missing_is_reported_not_silent(self, monkeypatch, capsys):
        """全部取数失败时不抛错，但必须打印原因分布（不能静默返回 0）。"""
        rows = [_row(1, "000001"), _row(2, "600000")]
        _client, _refresh = _setup(monkeypatch, rows, none_for=("000001", "600000"))

        settled = _run(W.settle_daily_recommendations())

        assert settled == 0
        out = capsys.readouterr().out
        assert "skip_no_history=2" in out
        assert "settled=0" in out

    def test_zero_pending_rows_is_reported(self, monkeypatch, capsys):
        _setup(monkeypatch, [])

        settled = _run(W.settle_daily_recommendations())

        assert settled == 0
        assert "待结算 0 行" in capsys.readouterr().out

    def test_benchmark_fetch_failure_does_not_block_settlement(self, monkeypatch, capsys):
        """基准指数取数异常时降级继续，不中止个股结算。"""
        rows = [_row(1, "000001")]
        client, _refresh = _setup(monkeypatch, rows, raise_for=(W.RECO_BENCHMARK,))

        settled = _run(W.settle_daily_recommendations())

        assert settled == 1
        assert client.updates[0][0] == 1
        out = capsys.readouterr().out
        assert "bench:" in out

    def test_benchmark_history_lands_in_settlement_fields(self, monkeypatch, capsys):
        """回归锁：基准取数必须走 to_thread 卸载。

        旧代码 `bench_hist = await data_service.get_history(...)` 直接 await 同步
        函数 → TypeError → 整批 0 结算且不落任何一行（2026-10-06 生产事故根因）。
        本测试断言基准收益率真实落到结算字段里 —— 该断言在旧实现下必然失败：
        先因 TypeError 全批中断；若仅用 except 兜住而不修取数方式，则
        benchmark_return 缺失（降级旧口径），同样不通过。
        """
        rows = [_row(1, "000001")]
        client, _refresh = _setup(monkeypatch, rows)

        settled = _run(W.settle_daily_recommendations())

        assert settled == 1
        _row_id, fields = client.updates[0]
        assert "benchmark_return" in fields
        assert "excess_return" in fields
        assert "bench:" not in capsys.readouterr().out
