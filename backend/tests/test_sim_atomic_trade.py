import pytest

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
