"""连板接力自动建仓（sim_service.auto_relay_*）的回归测试。

重点钉死四类错误：

1. **目标筛选** —— 环境 hunt + tier1 双闸门，任何一侧不满足都不能建仓；
2. **一字板不可成交** —— 晋级率高不等于买得进，一字板必须记 missed 而不是假装成交；
3. **仓位换算** —— 预算百分比 → 整手数，不足 1 手不买；
4. **幂等** —— 同 (user, code, trade_date) 只写一次。
"""
from __future__ import annotations

import pytest

from app.services import sim_service as S


# ---------- 纯函数：目标筛选 ----------


def _relay_stock(code: str, tier: int, score: int) -> dict:
    return {"code": code, "name": f"票{code[-2:]}", "boards": 2, "score": score, "tier": tier}


def _snapshot(level: str, relays: list[dict]) -> dict:
    return {
        "trade_date": "2026-09-17",
        "play_advice": {"level": level},
        "relay_stocks": relays,
    }


class RelayPickTargetsTests:
    def test_hunt_environment_picks_tier1_only(self) -> None:
        snap = _snapshot("hunt", [
            _relay_stock("600001", 1, 3),
            _relay_stock("600002", 2, 2),
            _relay_stock("600003", 1, 3),
        ])
        targets = S._relay_pick_targets(snap)
        assert [t["code"] for t in targets] == ["600001", "600003"]

    def test_watch_environment_blocks_everything(self) -> None:
        snap = _snapshot("watch", [_relay_stock("600001", 1, 3)])
        assert S._relay_pick_targets(snap) == []

    def test_avoid_environment_blocks_everything(self) -> None:
        snap = _snapshot("avoid", [_relay_stock("600001", 1, 3)])
        assert S._relay_pick_targets(snap) == []

    def test_hunt_without_tier1_yields_nothing(self) -> None:
        snap = _snapshot("hunt", [_relay_stock("600001", 3, 0)])
        assert S._relay_pick_targets(snap) == []

    def test_missing_advice_is_safe(self) -> None:
        assert S._relay_pick_targets({}) == []
        assert S._relay_pick_targets(None) == []


# ---------- 纯函数：一字板不可成交 ----------


class RelayUnfillableTests:
    def test_flat_limit_up_open_is_unfillable(self) -> None:
        """一字板：high==low 且开盘即涨停（≥9.5%）→ 买不进。"""
        # 昨收 10.0，今日一字涨停 11.0
        assert S._relay_unfillable(11.0, 10.0, 11.0, 11.0) is True

    def test_normal_open_is_fillable(self) -> None:
        """正常开盘（有波动区间）→ 可成交。"""
        assert S._relay_unfillable(10.5, 10.0, 10.9, 10.2) is False

    def test_high_open_but_not_flat_is_fillable(self) -> None:
        """开盘大涨 9.8% 但日内有波动（炸板过）→ 仍可成交。"""
        assert S._relay_unfillable(10.98, 10.0, 11.0, 10.4) is False

    def test_flat_but_below_limit_is_fillable(self) -> None:
        """全天横盘但不是涨停价（如平盘横住）→ 可成交。"""
        assert S._relay_unfillable(10.0, 10.0, 10.01, 9.99) is False

    def test_guarded_against_zero_inputs(self) -> None:
        assert S._relay_unfillable(0, 10.0, 11.0, 11.0) is False
        assert S._relay_unfillable(11.0, 0, 11.0, 11.0) is False


# ---------- 纯函数：仓位换算 ----------


class RelaySharesTests:
    def test_budget_pct_to_lot_shares(self) -> None:
        """10 万本金、10% 预算、10 元股 → 1000 股。"""
        assert S._relay_build_shares(100_000.0, 10.0) == 1000

    def test_rounds_down_to_lot(self) -> None:
        """不足一手向下取整。"""
        # 10 万 × 10% = 1 万；价 33 元 → 303.03 股 → 300 股
        assert S._relay_build_shares(100_000.0, 33.0) == 300

    def test_insufficient_budget_returns_zero(self) -> None:
        """预算买不起一手返回 0（调用方跳过而不是报错）。"""
        assert S._relay_build_shares(100_000.0, 200.0) == 0
        assert S._relay_build_shares(0, 10.0) == 0
        assert S._relay_build_shares(100_000.0, 0) == 0


# ---------- 异步：建仓流程（mock DB 与行情） ----------


class _Q:
    """supabase 查询链 mock：.select().eq()...().execute() 任意链式。"""

    def __init__(self, rows: list[dict]):
        self._rows = rows

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    async def execute(self):
        class R:
            data = self._rows

        return R()


class _FakeSB:
    def __init__(self, existing: list[dict] | None = None):
        self.existing = existing or []

    def table(self, _name):
        return _Q(self.existing)


class _Hist:
    """data_service.get_history 的最小 mock。"""

    def __init__(self, dates, closes, opens, highs, lows):
        self.dates = dates
        self.closes = closes
        self.opens = opens
        self.highs = highs
        self.lows = lows


@pytest.mark.asyncio
async def test_auto_relay_buy_buys_tier1_at_next_open(monkeypatch):
    snap = _snapshot("hunt", [_relay_stock("600001", 1, 3)])

    async def fake_profile(uid):
        return {"user_id": uid, "total_capital": 100_000.0, "cash": 100_000.0}

    async def fake_next_open(code, base_date):
        assert code == "600001"
        # T 日收盘 10.0，T+1 开盘 10.3（非一字）→ 可成交
        return {"date": "2026-09-18", "open": 10.3, "high": 10.6, "low": 10.2, "prev_close": 10.0}

    bought = {}

    async def fake_buy(uid, code, shares, price=None, **kw):
        bought[code] = (shares, price, kw.get("source"))

    monkeypatch.setattr(S, "_get_or_create_profile", fake_profile)
    monkeypatch.setattr(S, "_relay_next_open", fake_next_open)
    monkeypatch.setattr(S, "buy", fake_buy)
    monkeypatch.setattr(S, "_relay_already_done", lambda *a, **k: _async(False))

    summary = await S.auto_relay_buy_for_user("u1", snap)

    # 10 万本金 × 10% 预算 ÷ 10.3 元 → 970 股 → 整手 900 股
    assert bought["600001"] == (900, 10.3, "limitup_relay")
    assert summary["bought"] == ["600001:900股@10.3"]
    assert summary["missed"] == []


@pytest.mark.asyncio
async def test_auto_relay_buy_marks_flat_limit_up_as_missed(monkeypatch):
    """一字板开盘必须记 missed —— 假装成交是这条链路最危险的自欺。"""
    snap = _snapshot("hunt", [_relay_stock("600001", 1, 3)])

    async def fake_profile(uid):
        return {"user_id": uid, "total_capital": 100_000.0, "cash": 100_000.0}

    async def fake_next_open(code, base_date):
        return {"date": "2026-09-18", "open": 11.0, "high": 11.0, "low": 11.0, "prev_close": 10.0}

    monkeypatch.setattr(S, "_get_or_create_profile", fake_profile)
    monkeypatch.setattr(S, "_relay_next_open", fake_next_open)
    monkeypatch.setattr(S, "buy", _fail_if_called)
    monkeypatch.setattr(S, "_relay_already_done", lambda *a, **k: _async(False))

    summary = await S.auto_relay_buy_for_user("u1", snap)

    assert summary["bought"] == []
    assert len(summary["missed"]) == 1
    assert "600001" in summary["missed"][0]


@pytest.mark.asyncio
async def test_auto_relay_buy_is_idempotent(monkeypatch):
    """同 (user, code, trade_date) 已有流水 → 跳过，绝不重复建仓。"""
    snap = _snapshot("hunt", [_relay_stock("600001", 1, 3)])

    async def fake_profile(uid):
        return {"user_id": uid, "total_capital": 100_000.0, "cash": 100_000.0}

    monkeypatch.setattr(S, "_get_or_create_profile", fake_profile)
    monkeypatch.setattr(S, "_relay_already_done", lambda *a, **k: _async(True))
    monkeypatch.setattr(S, "buy", _fail_if_called)

    summary = await S.auto_relay_buy_for_user("u1", snap)

    assert summary["bought"] == []
    assert any("already_done" in s for s in summary["skipped"])


@pytest.mark.asyncio
async def test_auto_relay_buy_skips_when_not_hunt(monkeypatch):
    """环境非 hunt 直接返回空摘要，不打任何行情请求。"""
    snap = _snapshot("watch", [_relay_stock("600001", 1, 3)])
    monkeypatch.setattr(S, "buy", _fail_if_called)

    summary = await S.auto_relay_buy_for_user("u1", snap)

    assert summary["targets"] == []
    assert summary["skipped"] == ["no_targets_or_not_hunt"]


@pytest.mark.asyncio
async def test_auto_relay_buy_skips_uninitialized_account(monkeypatch):
    snap = _snapshot("hunt", [_relay_stock("600001", 1, 3)])

    async def fake_profile(uid):
        return {"user_id": uid, "total_capital": 0, "cash": 0}

    monkeypatch.setattr(S, "_get_or_create_profile", fake_profile)
    monkeypatch.setattr(S, "buy", _fail_if_called)

    summary = await S.auto_relay_buy_for_user("u1", snap)
    assert summary["skipped"] == ["account_not_initialized"]


@pytest.mark.asyncio
async def test_auto_relay_buy_skips_insufficient_budget(monkeypatch):
    """预算不足一手 → 跳过该票而非报错。"""
    snap = _snapshot("hunt", [_relay_stock("600001", 1, 3)])

    async def fake_profile(uid):
        return {"user_id": uid, "total_capital": 100_000.0, "cash": 100_000.0}

    async def fake_next_open(code, base_date):
        return {"date": "2026-09-18", "open": 500.0, "high": 505.0, "low": 499.0, "prev_close": 490.0}

    monkeypatch.setattr(S, "_get_or_create_profile", fake_profile)
    monkeypatch.setattr(S, "_relay_next_open", fake_next_open)
    monkeypatch.setattr(S, "buy", _fail_if_called)
    monkeypatch.setattr(S, "_relay_already_done", lambda *a, **k: _async(False))

    summary = await S.auto_relay_buy_for_user("u1", snap)
    assert summary["bought"] == []
    assert any("insufficient_budget" in s for s in summary["skipped"])


@pytest.mark.asyncio
async def test_single_stock_failure_does_not_block_rest(monkeypatch):
    """一只票行情拉取失败 → errors 里记录，其余票继续。"""
    snap = _snapshot("hunt", [_relay_stock("600001", 1, 3), _relay_stock("600002", 1, 3)])

    async def fake_profile(uid):
        return {"user_id": uid, "total_capital": 100_000.0, "cash": 100_000.0}

    calls = {"n": 0}

    async def fake_next_open(code, base_date):
        calls["n"] += 1
        if code == "600001":
            raise RuntimeError("network down")
        return {"date": "2026-09-18", "open": 5.0, "high": 5.2, "low": 4.9, "prev_close": 4.8}

    bought = {}

    async def fake_buy(uid, code, shares, price=None, **kw):
        bought[code] = shares

    monkeypatch.setattr(S, "_get_or_create_profile", fake_profile)
    monkeypatch.setattr(S, "_relay_next_open", fake_next_open)
    monkeypatch.setattr(S, "buy", fake_buy)
    monkeypatch.setattr(S, "_relay_already_done", lambda *a, **k: _async(False))

    summary = await S.auto_relay_buy_for_user("u1", snap)

    assert bought == {"600002": 2000}
    assert len(summary["errors"]) == 1
    assert "600001" in summary["errors"][0]


# ---------- helpers ----------


def _async(v):
    """返回一个 awaitable（协程对象）。注意必须调用一次 _f() 才是协程。"""

    async def _f(*_a, **_k):
        return v

    return _f()


async def _fail_if_called(*_a, **_k):  # pragma: no cover - 被调用即测试失败
    raise AssertionError("buy() should not have been called")
