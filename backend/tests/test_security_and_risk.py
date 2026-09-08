import pytest
from fastapi import HTTPException

from app.routes import history
from app.services.portfolio_service import _select_stop_price


@pytest.mark.asyncio
async def test_protected_history_rejects_missing_bearer_token(monkeypatch):
    monkeypatch.setattr(history.supabase_store, "is_configured", lambda: True)
    with pytest.raises(HTTPException) as exc:
        await history._history_user(None)

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_local_sqlite_history_remains_available_without_supabase(monkeypatch):
    monkeypatch.setattr(history.supabase_store, "is_configured", lambda: False)
    assert await history._history_user(None) is None


def test_technical_stop_cannot_expand_loss_beyond_fixed_risk_limit():
    assert _select_stop_price(cost_price=100, technical_stop=80) == 93


def test_closer_valid_technical_stop_tightens_risk():
    assert _select_stop_price(cost_price=100, technical_stop=96) == 96


def test_technical_stop_above_cost_is_ignored():
    assert _select_stop_price(cost_price=100, technical_stop=105) == 93
