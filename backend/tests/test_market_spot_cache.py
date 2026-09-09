import pandas as pd
import pytest

from app.routes import market


def test_zero_price_snapshot_is_not_usable():
    rows = [{"code": "600519", "name": "贵州茅台", "price": 0, "change": 0, "amount": 0}] * 100
    assert market._is_usable_spot(rows) is False


def test_live_snapshot_with_priced_stocks_is_usable():
    rows = [{"code": f"600{i:03d}", "name": "测试", "price": 10, "change": 1, "amount": 1e8} for i in range(100)]
    assert market._is_usable_spot(rows) is True


@pytest.mark.asyncio
async def test_force_refresh_bypasses_persistent_snapshot(monkeypatch):
    async def fail_if_loaded():
        raise AssertionError("force refresh must not load the persistent snapshot")

    async def ignore_save(_rows):
        return None

    frame = pd.DataFrame(
        [
            {"代码": f"600{i:03d}", "名称": "测试", "最新价": 10, "涨跌幅": 1.2, "成交额": 2e9}
            for i in range(100)
        ]
    )
    monkeypatch.setattr(market, "_load_spot_db", fail_if_loaded)
    monkeypatch.setattr(market, "_save_spot_db", ignore_save)
    monkeypatch.setattr(market.akshare_guard, "call", lambda _fn: frame)
    market._spot_cache = None

    rows = await market._get_spot(force=True)

    assert rows[0]["price"] == 10
