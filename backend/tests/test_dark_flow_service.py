"""暗盘资金 G/S 信号测试。

重点守三件事：
1. G/S 判定边界（明暗背离形态 + 涨幅条件 + 中单占比噪声闸门）；
2. **红线**：``actionable=False`` / ``signal_status=unsupported`` 恒定，不受规则分支影响；
3. 缓存 / force 节流锚点是「上一次真实取数」，失败降级不抛异常。
"""
from __future__ import annotations

import asyncio
import datetime as dt
import inspect

import pytest

from app.services import dark_flow_service as S


def _row(
    code: str = "600001",
    main_net: float | None = -2e8,
    mid_net: float | None = 1e8,
    small_net: float | None = 0.0,
    amount: float | None = 5e9,
    change_pct: float | None = 1.0,
) -> dict:
    return {
        "code": code,
        "name": f"票{code}",
        "price": 10.0,
        "change_pct": change_pct,
        "sector": "测试行业",
        "main_net": main_net,
        "mid_net": mid_net,
        "small_net": small_net,
        "amount": amount,
    }


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    S.clear_caches()
    # 共享行情源冷却默认放行；单测里要验冷却的用例自行覆盖。
    async def _no_cooldown() -> float:
        return 0.0

    monkeypatch.setattr(
        "app.routes.market.spot_cooldown_seconds", _no_cooldown, raising=False
    )
    # 持续性历史默认不可用（降级单日）：别让单测去连真实 Supabase。
    # 要验历史的用例自行 stub `_load_history_rows` 或 is_configured。
    monkeypatch.setattr(S.supabase_store, "is_configured", lambda: False)
    yield
    S.clear_caches()


# ───────────────────────── G/S 判定 ─────────────────────────


class ClassifyTests:
    def test_mixed_outflow_with_mid_inflow_marks_g(self) -> None:
        item = S._classify(_row(main_net=-2e8, mid_net=1e8, change_pct=1.0))
        assert item is not None
        assert item["signal"] == "G"
        assert "拆单吸筹" in item["reason"]

    def test_mixed_inflow_with_mid_outflow_marks_s(self) -> None:
        item = S._classify(_row(main_net=2e8, mid_net=-1e8, change_pct=5.0))
        assert item is not None
        assert item["signal"] == "S"
        assert "拉高派发" in item["reason"]

    def test_same_direction_yields_no_signal(self) -> None:
        """明暗同向不是背离形态：双双流入不判 G，双双流出不判 S。"""
        assert S._classify(_row(main_net=2e8, mid_net=1e8, change_pct=1.0)) is None
        assert S._classify(_row(main_net=-2e8, mid_net=-1e8, change_pct=5.0)) is None

    def test_g_requires_change_below_ceiling(self) -> None:
        """涨幅超过 3% 已是拉高形态，不再判 G。"""
        assert S._classify(_row(main_net=-2e8, mid_net=1e8, change_pct=3.0)) is not None
        assert S._classify(_row(main_net=-2e8, mid_net=1e8, change_pct=3.1)) is None

    def test_g_rejects_deep_fall(self) -> None:
        """深跌日（< -5%）中单流入以散户抄底为主，「吸筹嫌疑」不成立，宁可漏判。"""
        assert S._classify(_row(main_net=-2e8, mid_net=1e8, change_pct=-5.0)) is not None
        assert S._classify(_row(main_net=-2e8, mid_net=1e8, change_pct=-5.1)) is None
        assert S._classify(_row(main_net=-2e8, mid_net=1e8, change_pct=-14.4)) is None

    def test_s_requires_change_at_or_above_floor(self) -> None:
        assert S._classify(_row(main_net=2e8, mid_net=-1e8, change_pct=3.0)) is not None
        assert S._classify(_row(main_net=2e8, mid_net=-1e8, change_pct=2.9)) is None

    def test_small_mid_share_is_noise_not_signal(self) -> None:
        """中单净额占成交额不到 2% 视为噪声（金额太小的背离没有信息量）。"""
        assert S._classify(_row(main_net=-2e8, mid_net=1e8, amount=1e10)) is None  # 1%
        assert S._classify(_row(main_net=-2e8, mid_net=2e8, amount=1e10)) is not None  # 2%

    def test_missing_amount_or_change_skips_without_crash(self) -> None:
        assert S._classify(_row(amount=None)) is None
        assert S._classify(_row(amount=0)) is None
        assert S._classify(_row(change_pct=None)) is None
        assert S._classify(_row(main_net=None)) is None
        assert S._classify(_row(mid_net=None)) is None


# ───────────────────────── 红线守卫 ─────────────────────────


class RedLineTests:
    def test_payload_pins_unsupported_and_not_actionable(self) -> None:
        """未定义收益口径前不给买卖动作：G/S 恒为 unsupported，任何分支不得改写。"""
        payload = S._build_payload([_row()], "note", fetched_at=1.0)
        assert payload["signal_status"] == "unsupported"
        assert payload["actionable"] is False
        assert payload["status"] == "ok"

    def test_empty_payload_still_carries_red_line(self) -> None:
        payload = S._empty_payload("unavailable", "端点不可用")
        assert payload["signal_status"] == "unsupported"
        assert payload["actionable"] is False
        assert payload["available"] is False

    def test_caveats_state_proxy_caliber_and_no_advice(self) -> None:
        joined = " ".join(S.CAVEATS)
        assert "混合体" in joined          # 中单不是真暗盘
        assert "不是真实暗盘" in joined
        assert "unsupported" in joined
        assert "不是买卖建议" in joined
        assert "越连续" in joined           # 持续性不许读成胜率/期望收益
        assert "结构读数" in joined

    def test_rule_source_never_sets_actionable_true(self) -> None:
        """静态守卫：载荷装配处不得把 actionable 翻成 True。"""
        source = inspect.getsource(S._build_payload) + inspect.getsource(S._empty_payload)
        assert 'actionable": True' not in source
        assert "'actionable': True" not in source

    def test_decision_logic_never_reads_small_net(self) -> None:
        """小单只随条目透传供展示；判定区（return 条目之前）不得读它。"""
        assert "small_net" not in inspect.getsource(S._mid_pct)
        decision_part = inspect.getsource(S._classify).split("return {")[0]
        assert "small_net" not in decision_part


# ───────────────────────── 载荷与排序 ─────────────────────────


class PayloadTests:
    def test_sides_sorted_by_mid_amount(self) -> None:
        rows = [
            _row(code="600001", main_net=-1e8, mid_net=1e8, change_pct=1.0),
            _row(code="600002", main_net=-3e8, mid_net=3e8, change_pct=1.0),
            _row(code="600003", main_net=1e8, mid_net=-2e8, change_pct=5.0),
            _row(code="600004", main_net=1e8, mid_net=-5e8, change_pct=5.0),
        ]
        payload = S._build_payload(rows, "note", fetched_at=1.0)
        assert [r["code"] for r in payload["g_items"]] == ["600002", "600001"]
        assert [r["code"] for r in payload["s_items"]] == ["600004", "600003"]
        assert payload["counts"] == {"g": 2, "s": 2, "scanned": 4}

    def test_side_size_is_capped(self) -> None:
        rows = [
            _row(code=f"6000{i:02d}", main_net=-1e8, mid_net=1e8 + i, change_pct=1.0)
            for i in range(S._SIDE_SIZE + 5)
        ]
        payload = S._build_payload(rows, "note", fetched_at=1.0)
        assert len(payload["g_items"]) == S._SIDE_SIZE


# ───────────────────────── 缓存 / 节流 / 降级 ─────────────────────────


class CacheAndDegradeTests:
    def _fake_rows(self, monkeypatch, rows=None):
        calls: list[tuple] = []

        def fake_fetch(sort_field, ascending, max_pages=3):
            calls.append((sort_field, ascending))
            return rows if rows is not None else [_row()]

        monkeypatch.setattr(S.spot_service, "fetch_fund_flow_rows", fake_fetch)
        return calls

    def test_second_call_hits_cache(self, monkeypatch) -> None:
        calls = self._fake_rows(monkeypatch)

        first = asyncio.run(S.get_signals())
        second = asyncio.run(S.get_signals())
        assert first["status"] == "ok"
        assert second["status"] == "cached"
        assert len(calls) == 2  # 两端各一次

    def test_force_throttle_returns_previous_payload(self, monkeypatch) -> None:
        calls = self._fake_rows(monkeypatch)
        asyncio.run(S.get_signals())
        n = len(calls)

        result = asyncio.run(S.get_signals(force=True))
        assert result["status"] == "cached"
        assert "刷新间隔过短" in result["note"]
        assert len(calls) == n  # 未再打端点（锚点是上一次真实取数）

    def test_failure_enters_cooldown_without_crash(self, monkeypatch) -> None:
        def boom(*_a, **_k):
            raise RuntimeError("风控")

        monkeypatch.setattr(S.spot_service, "fetch_fund_flow_rows", boom)
        result = asyncio.run(S.get_signals())
        assert result["status"] == "unavailable"
        assert result["available"] is False
        assert result["signal_status"] == "unsupported"

        again = asyncio.run(S.get_signals())
        assert again["status"] == "unavailable"
        assert "冷却中" in again["note"]

    def test_shared_cooldown_skips_source(self, monkeypatch) -> None:
        calls = self._fake_rows(monkeypatch)

        async def fake_cooldown() -> float:
            return 120.0

        monkeypatch.setattr("app.routes.market.spot_cooldown_seconds", fake_cooldown)
        result = asyncio.run(S.get_signals())
        assert result["status"] == "cooldown"
        assert "冷却" in result["note"]
        assert calls == []  # 冷却期不打端点


# ───────────────────────── 持续性 / 落库 ─────────────────────────


class StreakTests:
    """compute_streaks 纯函数：连续性按「有快照的交易日」序列数。"""

    def test_consecutive_same_signal_days_count_up(self) -> None:
        rows = [
            {"signal_date": "2026-10-05", "code": "600001", "signal": "G"},
            {"signal_date": "2026-10-06", "code": "600001", "signal": "G"},
        ]
        streaks = S.compute_streaks(rows, "2026-10-07", {"600001": "G"})
        assert streaks["current"]["600001"] == 3
        assert streaks["sample_days"] == 2

    def test_no_signal_day_breaks_the_run(self) -> None:
        """10-06 有快照数据（别的票出形态）但本票当日无形态 → 连续段断开。"""
        rows = [
            {"signal_date": "2026-10-05", "code": "600001", "signal": "G"},
            {"signal_date": "2026-10-06", "code": "600002", "signal": "S"},
        ]
        streaks = S.compute_streaks(rows, "2026-10-07", {"600001": "G"})
        assert streaks["current"]["600001"] == 1

    def test_missing_data_days_do_not_break_the_run(self) -> None:
        """全表无数据的日子（缺采/节假日）不在时间轴上 —— 不算断档。"""
        rows = [
            {"signal_date": "2026-10-05", "code": "600001", "signal": "G"},
            {"signal_date": "2026-10-07", "code": "600001", "signal": "G"},
        ]
        streaks = S.compute_streaks(rows, "2026-10-08", {"600001": "G"})
        assert streaks["current"]["600001"] == 3

    def test_signal_flip_breaks_the_run(self) -> None:
        rows = [{"signal_date": "2026-10-06", "code": "600001", "signal": "G"}]
        streaks = S.compute_streaks(rows, "2026-10-07", {"600001": "S"})
        assert streaks["current"]["600001"] == 1

    def test_no_history_degrades_to_single_day(self) -> None:
        streaks = S.compute_streaks([], "2026-10-07", {"600001": "G"})
        assert streaks["current"] == {"600001": 1}
        assert streaks["sample_days"] == 0
        # 今日进行中的段照记（episodes 含今日段），但 sample_days=0 ⇒ 调用方降级单日
        assert streaks["episodes"] == [1]

    def test_episodes_capture_run_length_distribution(self) -> None:
        rows = [
            {"signal_date": "2026-10-05", "code": "600001", "signal": "G"},
            {"signal_date": "2026-10-06", "code": "600001", "signal": "G"},
            {"signal_date": "2026-10-07", "code": "600001", "signal": "G"},
        ]
        streaks = S.compute_streaks(rows, "2026-10-08", {"600001": "S"})
        # 历史一段 G×3；今日 S 起新段 ×1
        assert sorted(streaks["episodes"]) == [1, 3]


class PersistenceAttachTests:
    def test_unavailable_history_degrades_single_day_with_note(self, monkeypatch) -> None:
        payload = S._build_payload([_row(code="600001")], "note", fetched_at=1.0)
        asyncio.run(S._attach_persistence(payload))

        p = payload["persistence"]
        assert p["available"] is False
        assert "降级单日" in p["note"]
        assert payload["g_items"][0]["streak"] == 1
        # 没有四问 ≠ 四问过了：缺样本时必须显式下发缺席原因
        assert p["four_questions"] is None
        assert p["four_questions_absent_reason"]

    def test_history_attaches_streaks_and_four_questions(self, monkeypatch) -> None:
        async def fake_history():
            return [
                {"signal_date": "2026-10-05", "code": "600001", "signal": "G"},
                {"signal_date": "2026-10-06", "code": "600001", "signal": "G"},
            ]

        monkeypatch.setattr(S, "_load_history_rows", fake_history)
        monkeypatch.setattr(
            S.trade_calendar_service, "now_cn", lambda: dt.datetime(2026, 10, 7)
        )
        payload = S._build_payload([_row(code="600001")], "note", fetched_at=1.0)
        asyncio.run(S._attach_persistence(payload))

        p = payload["persistence"]
        assert p["available"] is True
        assert payload["g_items"][0]["streak"] == 3
        assert p["sample_days"] == 2
        assert p["streak_stats"]["n"] == 1
        four = p["four_questions"]
        assert four is not None
        by_key = {i["key"]: i for i in four["items"]}
        assert by_key["sample"]["answered"] is True
        # 不涉及成交 / 无收益基准 —— 这两问答不上来，且文案不许借收益口径
        assert by_key["tradable"]["passed"] is None
        assert "不涉及成交" in by_key["tradable"]["detail"]
        assert by_key["benchmark_sign"]["passed"] is None
        assert "不等于" in by_key["benchmark_sign"]["detail"]

    def test_red_line_survives_persistence_attach(self, monkeypatch) -> None:
        payload = S._build_payload([_row(code="600001")], "note", fetched_at=1.0)
        asyncio.run(S._attach_persistence(payload))
        assert payload["signal_status"] == "unsupported"
        assert payload["actionable"] is False


class SnapshotSaveTests:
    def _payload(self) -> dict:
        item = S._classify(_row(code="600001"))
        item2 = S._classify(_row(code="600002", main_net=2e8, mid_net=-1e8, change_pct=5.0))
        return {"all_signals": [item, item2], "g_items": [item], "s_items": [item2]}

    def test_save_uses_full_signal_set_and_upserts(self, monkeypatch) -> None:
        captured: dict = {}

        class _T:
            def upsert(self, rows, on_conflict=None):
                captured["rows"] = rows
                captured["on_conflict"] = on_conflict
                return self

            async def execute(self):
                return type("R", (), {"data": captured["rows"]})()

        class _C:
            def table(self, name):
                captured["table"] = name
                return _T()

        async def _get():
            return _C()

        monkeypatch.setattr(S.supabase_store, "is_configured", lambda: True)
        monkeypatch.setattr(S.supabase_store, "get_service_client", _get)

        n = asyncio.run(S.save_daily_snapshot("2026-10-07", self._payload()))

        assert n == 2
        assert captured["table"] == "dark_flow_daily_snapshot"
        assert captured["on_conflict"] == "signal_date,code"
        assert {r["code"] for r in captured["rows"]} == {"600001", "600002"}
        assert all(r["signal_date"] == "2026-10-07" for r in captured["rows"])

    def test_save_degrades_to_zero_when_table_missing(self, monkeypatch) -> None:
        class _Boom:
            def table(self, *_a):
                raise RuntimeError('relation "dark_flow_daily_snapshot" does not exist')

        async def boom():
            return _Boom()

        monkeypatch.setattr(S.supabase_store, "is_configured", lambda: True)
        monkeypatch.setattr(S.supabase_store, "get_service_client", boom)

        assert asyncio.run(S.save_daily_snapshot("2026-10-07", self._payload())) == 0

    def test_purge_degrades_to_zero_when_table_missing(self, monkeypatch) -> None:
        class _Boom:
            def table(self, *_a):
                raise RuntimeError('relation "dark_flow_daily_snapshot" does not exist')

        async def boom():
            return _Boom()

        monkeypatch.setattr(S.supabase_store, "is_configured", lambda: True)
        monkeypatch.setattr(S.supabase_store, "get_service_client", boom)

        assert asyncio.run(S.purge_old_snapshots()) == 0


class CaliberTests:
    def test_dark_flow_caliber_is_registered(self) -> None:
        from app.services import calibers

        entry = calibers.CALIBERS.get("dark_flow")
        assert entry is not None
        assert "unsupported" in entry["pitfall"]
        assert "streak" in entry["name"]
        assert "不能" in entry["pitfall"]  # 不许读成胜率/期望收益
