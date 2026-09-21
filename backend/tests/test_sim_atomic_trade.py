import pytest

from app.services import sim_service as S
from app.services.sim_service import _execute_trade_atomic


class _Response:
    data = {"trade": {"id": 7, "side": "buy"}, "cash": 8995.0}


class _RpcCall:
    async def execute(self):
        return _Response()


class _FakeSupabase:
    def __init__(self):
        self.name = None
        self.params = None

    def rpc(self, name, params):
        self.name = name
        self.params = params
        return _RpcCall()


@pytest.mark.asyncio
async def test_trade_uses_single_database_rpc_with_all_accounting_fields():
    sb = _FakeSupabase()
    result = await _execute_trade_atomic(
        sb,
        user_id="u1",
        code="600000",
        name="浦发银行",
        side="buy",
        price=10.0,
        shares=100,
        fee=5.0,
        amount=1005.0,
        source="manual",
        related_reco_id=None,
        note="",
    )

    assert sb.name == "execute_sim_trade"
    assert sb.params["p_user_id"] == "u1"
    assert sb.params["p_amount"] == 1005.0
    assert result["trade"]["id"] == 7


# ---------- 预期价格回填（v13 可选列） ----------


class _UpdateCall:
    def __init__(self, sink: dict) -> None:
        self.sink = sink

    async def execute(self):
        if self.sink.get("raise_on_update"):
            raise RuntimeError('column "expected_price" of relation "sim_trades" does not exist')
        self.sink["updates"].append(self.sink["payload"])
        return _Response()


class _UpdateTable:
    def __init__(self, sink: dict) -> None:
        self.sink = sink

    def update(self, payload: dict):
        self.sink["payload"] = payload
        return self

    def eq(self, column: str, value):
        self.sink["eq"] = (column, value)
        return self

    async def execute(self):
        return await _UpdateCall(self.sink).execute()


class _UpdateSupabase:
    def __init__(self, raise_on_update: bool = False) -> None:
        self.sink = {"updates": [], "raise_on_update": raise_on_update}

    def table(self, name: str):
        self.sink["table"] = name
        return _UpdateTable(self.sink)


@pytest.fixture(autouse=True)
def _reset_optional_columns():
    """`_OPTIONAL_TRADE_COLUMNS` 是模块级记忆位，测试之间必须隔离。"""
    S._OPTIONAL_TRADE_COLUMNS.clear()
    yield
    S._OPTIONAL_TRADE_COLUMNS.clear()


@pytest.mark.asyncio
async def test_expected_price_backfills_the_existing_trade_row():
    sb = _UpdateSupabase()

    await S._write_expected_price(sb, 7, 12.30)

    assert sb.sink["table"] == "sim_trades"
    assert sb.sink["payload"] == {"expected_price": 12.30}
    assert sb.sink["eq"] == ("id", 7)


@pytest.mark.asyncio
async def test_missing_column_degrades_silently_and_is_remembered():
    """v13 迁移没跑时只丢锚点，**绝不能让整笔建仓失败**（现金与胜率都挂在它后面）。"""
    sb = _UpdateSupabase(raise_on_update=True)

    await S._write_expected_price(sb, 7, 12.30)  # 不抛异常
    assert S._OPTIONAL_TRADE_COLUMNS == {"expected_price"}

    # 记住之后不再重复撞：第二次连 update 都不会发起
    sb2 = _UpdateSupabase(raise_on_update=True)
    await S._write_expected_price(sb2, 8, 11.0)
    assert sb2.sink.get("payload") is None


@pytest.mark.asyncio
async def test_invalid_or_absent_expected_price_is_a_noop():
    sb = _UpdateSupabase()

    for bad in (None, 0, -1.5, "abc"):
        await S._write_expected_price(sb, 7, bad)

    assert sb.sink["updates"] == []
