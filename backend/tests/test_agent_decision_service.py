"""Agent 决策闭环（agent_decision_service + sim from-plan）行为锁定。

覆盖三块：
1. 记录落库与幂等（同票同日同用户不重复）；
2. 结算的 hit/pnl 口径与反思生成（含无入场价行的降级）；
3. stats 的样本门槛（<5 不给命中率）与口径下发。

Supabase 交互全部 monkeypatch 假 client —— 服务函数对「表未建/未配置」的静默降级
是闸门纪律的一部分，必须有直接断言。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from app.models import FundManagerVerdict, TradePlan
from app.services import agent_decision_service as ads
from app.services import calibers


# ---------- fixtures / helpers ----------

def _plan(action: str = "buy", entry: float | None = 10.0, stop: float | None = 9.5) -> TradePlan:
    return TradePlan(
        action=action, entry_price=entry, stop_price=stop, target_price=11.5, position_pct=20.0
    )


def _verdict(decision: str = "approved", pct: float = 20.0) -> FundManagerVerdict:
    return FundManagerVerdict(
        decision=decision, verdict_notes=["ok"], final_position_pct=pct, final_stop_price=9.5
    )


class _FakeTable:
    """最小 supabase table 桩：记录 insert/update 调用，返回预置数据。"""

    def __init__(self, store: dict):
        self._store = store
        self._pending: dict = {}
        self._select_cols = ""

    def insert(self, row: dict):
        self._pending["insert"] = row
        return self

    def update(self, payload: dict):
        self._pending.setdefault("updates", []).append(payload)
        return self

    def select(self, *cols):
        self._select_cols = ",".join(str(c) for c in cols)
        return self

    def eq(self, *_a, **_k):
        return self

    def in_(self, *_a, **_k):
        return self

    def lte(self, *_a, **_k):
        return self

    def is_(self, *_a, **_k):
        return self

    @property
    def not_(self):
        """postgrest 链式否定：not_.is_(...) —— 桩里直接返回自身即可（select 默认空数据）。"""
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, _n):
        return self

    def range(self, *_a):
        return self

    async def execute(self):
        if "insert" in self._pending:
            row = dict(self._pending.pop("insert"))
            self._store["next_id"] += 1
            row["id"] = self._store["next_id"]
            self._store.setdefault("rows", []).append(row)
            return type("R", (), {"data": [row]})()
        if "updates" in self._pending:
            self._store["updates"] = list(self._pending.pop("updates"))
            return type("R", (), {"data": [{"id": 1}]})()
        # select：返回预置行（查重命中场景）—— select 的列参数区分「查重」与普通查询
        if self._select_cols == "id":
            return type("R", (), {"data": self._store.get("preset_dup") or []})()
        return type("R", (), {"data": self._store.get("select_result") or []})()


class _FakeClient:
    def __init__(self):
        self.store: dict = {"next_id": 0, "rows": [], "updates": []}
        self._table = _FakeTable(self.store)

    def table(self, _name: str) -> _FakeTable:
        return self._table


@pytest.fixture()
def fake_client(monkeypatch):
    c = _FakeClient()

    async def _fake_get_sb():
        return c

    monkeypatch.setattr(ads, "_get_sb", _fake_get_sb)
    return c


# ---------- 落库 ----------

class TestRecord:
    @pytest.mark.asyncio
    async def test_rejected_verdict_lands_as_rejected_row(self, fake_client) -> None:
        """终审否决 → status=rejected（对照样本），无需用户动作。"""
        rid = await ads.record_from_analysis(
            code="600519", name="贵州茅台", data_date="2026-09-18",
            plan=_plan(), verdict=_verdict("rejected", 0),
        )
        assert rid is not None
        row = fake_client.store["rows"][0]
        assert row["status"] == "rejected"
        assert row["verdict"] == "rejected"
        assert row["position_pct"] == 0.0

    @pytest.mark.asyncio
    async def test_approved_lands_as_ignored_awaiting_adopt(self, fake_client) -> None:
        """终审通过 → status=ignored：等用户采纳，否则到期进未采纳对照组。"""
        rid = await ads.record_from_analysis(
            code="600519", name="贵州茅台", data_date="2026-09-18",
            plan=_plan(), verdict=_verdict(),
        )
        row = fake_client.store["rows"][0]
        assert rid is not None
        assert row["status"] == "ignored"
        assert row["position_pct"] == 20.0
        assert row["horizon_days"] == ads.DEFAULT_HORIZON

    @pytest.mark.asyncio
    async def test_no_supabase_returns_none(self, monkeypatch) -> None:
        """未配置 Supabase：静默返回 None，绝不抛异常（主链路保护）。"""

        async def _none():
            return None

        monkeypatch.setattr(ads, "_get_sb", _none)
        assert await ads.record_from_analysis(
            code="600519", name="x", data_date="2026-09-18", plan=_plan(), verdict=_verdict()
        ) is None

    @pytest.mark.asyncio
    async def test_duplicate_same_day_skipped(self, monkeypatch) -> None:
        """同票同日同用户只落一行。"""
        c = _FakeClient()
        c.store["preset_dup"] = [{"id": 7}]  # 查重命中

        async def _sb():
            return c

        monkeypatch.setattr(ads, "_get_sb", _sb)
        rid = await ads.record_for_user_if_absent(
            code="600519", name="x", data_date="2026-09-18", plan=_plan(), verdict=_verdict(), user_id="u1"
        )
        assert rid is None
        assert len(c.store["rows"]) == 0  # 没有新增


# ---------- 采纳 ----------

class TestAdopt:
    @pytest.mark.asyncio
    async def test_adopt_updates_status_and_trade_id(self, fake_client) -> None:
        res = await ads.adopt(7, user_id="u1", shares=200, sim_trade_id=42)
        assert res is not None
        upd = fake_client.store["updates"][0]
        assert upd["status"] == "adopted"
        assert upd["sim_trade_id"] == 42


# ---------- 结算口径 ----------

class TestSettle:
    @pytest.mark.asyncio
    async def test_bull_hit_when_settle_above_entry(self, fake_client) -> None:
        row = {"id": 1, "code": "600519", "action": "buy", "entry_price": 10.0,
               "horizon_days": 5, "data_date": "2026-09-10", "verdict": "approved", "stop_price": 9.5}
        assert await ads.settle_one(row, 11.0) is True
        upd = fake_client.store["updates"][0]
        assert upd["hit"] is True
        assert upd["pnl_pct"] == pytest.approx(10.0)
        assert upd["settle_basis"] == "close"
        assert "方向与计划一致" in upd["reflection"]

    @pytest.mark.asyncio
    async def test_bull_miss_when_settle_below_entry(self, fake_client) -> None:
        row = {"id": 1, "code": "600519", "action": "buy", "entry_price": 10.0,
               "horizon_days": 5, "data_date": "2026-09-10", "verdict": "approved"}
        assert await ads.settle_one(row, 9.0) is True
        upd = fake_client.store["updates"][0]
        assert upd["hit"] is False
        assert upd["pnl_pct"] == pytest.approx(-10.0)
        assert "方向与计划相反" in upd["reflection"]

    @pytest.mark.asyncio
    async def test_defensive_action_counts_rise_as_miss(self, fake_client) -> None:
        """reduce 类（看空方向）计划：结算价上涨应记未命中 —— 方向化口径。"""
        row = {"id": 1, "code": "600519", "action": "reduce", "entry_price": 10.0,
               "horizon_days": 5, "data_date": "2026-09-10", "verdict": "approved"}
        assert await ads.settle_one(row, 10.5) is True
        assert fake_client.store["updates"][0]["hit"] is False

    @pytest.mark.asyncio
    async def test_no_entry_price_marks_without_pnl(self, fake_client) -> None:
        """无入场价（hold/avoid 或缺字段）：只标记到期，不填 pnl/hit —— 不乱造基准。"""
        row = {"id": 1, "code": "600519", "action": "avoid", "entry_price": None,
               "horizon_days": 5, "data_date": "2026-09-10", "verdict": "approved"}
        assert await ads.settle_one(row, 10.5) is True
        upd = fake_client.store["updates"][0]
        assert upd["hit"] is None
        assert "pnl_pct" not in upd

    def test_reflection_contains_facts_not_advice(self) -> None:
        """反思只含事实与偏差，不含「应该/建议」类指令 —— 反思正确性无回测支撑。"""
        row = {"data_date": "2026-09-10", "code": "600519", "action": "buy", "verdict": "approved",
               "entry_price": 10.0, "stop_price": 9.5, "target_price": 11.5, "horizon_days": 5}
        text = ads.reflection_from(row, 9.0, hit=False)
        assert "9.0" in text
        assert "方向与计划相反" in text
        for banned in ("应该", "建议", "推荐"):
            assert banned not in text


# ---------- 决策记忆（P1） ----------

class TestMemoryBlock:
    def test_empty_when_no_rows(self) -> None:
        assert ads.memory_block([]) == ""

    def test_contains_outcome_and_deviation(self) -> None:
        rows = [{
            "data_date": "2026-09-10", "verdict": "approved", "action": "buy",
            "entry_price": 10.0, "settle_price": 9.0, "horizon_days": 5,
            "hit": False, "reflection": "上次方向错了（实际下跌 10.0%）",
        }]
        block = ads.memory_block(rows)
        assert "决策记忆" in block
        assert "9.0" in block
        assert "-10.0%" in block
        assert "方向相反" in block

    def test_rows_without_settle_price_skipped(self) -> None:
        rows = [{"data_date": "2026-09-10", "entry_price": 10.0, "settle_price": None}]
        assert ads.memory_block(rows) == ""


# ---------- 统计口径 ----------

class TestStats:
    @pytest.mark.asyncio
    async def test_below_5_samples_no_hit_rate(self, monkeypatch) -> None:
        """样本 <5 不给命中率 —— 2/3=67% 这类读数只会骗自己（纪律锁定）。"""
        c = _FakeClient()
        c.store["rows"] = [
            {"status": "adopted", "hit": True, "pnl_pct": 5.0},
            {"status": "adopted", "hit": False, "pnl_pct": -3.0},
        ]

        async def _sb():
            return c

        monkeypatch.setattr(ads, "_get_sb", _sb)
        stats = await ads.stats("u1")
        assert stats is not None
        assert stats["adopted"]["hit_rate"] is None
        assert "不足 5 条" in (stats["adopted"]["sample_note"] or "")

    @pytest.mark.asyncio
    async def test_caliber_always_carried(self, monkeypatch) -> None:
        """stats 必须带 agent_plan 口径 —— 裸百分比不允许出现在界面上。"""
        c = _FakeClient()
        c.store["rows"] = [{"status": "adopted", "hit": True, "pnl_pct": 1.0}]

        async def _sb():
            return c

        monkeypatch.setattr(ads, "_get_sb", _sb)
        stats = await ads.stats("u1")
        assert stats["caliber"]["key"] == "agent_plan"
        assert stats["caliber"]["registered"] is True

    def test_agent_plan_registered_in_calibers(self) -> None:
        """口径必须登记进 calibers（否则 describe 会返回「未登记口径」占位）。"""
        d = calibers.describe("agent_plan")
        assert d["registered"] is True
        assert "N 个交易日" in d["window"]
        assert "样本 < 5" in d["rule"]
