import time

import pandas as pd
import pytest

from app.routes import market
from app.services import spot_service


def _frame(price: float, size: int = 100) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"代码": f"600{i:03d}", "名称": "测试", "最新价": price, "涨跌幅": 1.2, "成交额": 2e9}
            for i in range(size)
        ]
    )


def test_zero_price_snapshot_is_not_usable():
    rows = [{"code": "600519", "name": "贵州茅台", "price": 0, "change": 0, "amount": 0}] * 100
    assert market._is_usable_spot(rows) is False


def test_live_snapshot_with_priced_stocks_is_usable():
    rows = [{"code": f"600{i:03d}", "name": "测试", "price": 10, "change": 1, "amount": 1e8} for i in range(100)]
    assert market._is_usable_spot(rows) is True


def test_spot_frame_falls_back_when_eastmoney_fails(monkeypatch):
    """东财整体失败时降级新浪。"""
    calls = []

    def fail_em(**_kwargs):
        calls.append("em")
        raise RuntimeError("东财行情请求失败: RemoteDisconnected")

    def ok_sina(**_kwargs):
        calls.append("sina")
        return _frame(10)

    monkeypatch.setattr(spot_service, "_fetch_eastmoney", fail_em)
    monkeypatch.setattr(spot_service, "_fetch_sina", ok_sina)
    monkeypatch.setattr(spot_service, "_SOURCE_ATTEMPTS", 1)
    monkeypatch.setattr(spot_service.time, "sleep", lambda *_args: None)

    df = spot_service.fetch_spot_frame()

    assert calls == ["em", "sina"]
    assert len(df) == 100


def test_spot_frame_retries_sources_before_giving_up(monkeypatch):
    """首轮东财+新浪都失败后，第二轮东财恢复即采用东财数据。"""
    calls = []

    def flaky_em(**_kwargs):
        calls.append("em")
        if len(calls) < 3:
            raise RuntimeError("东财行情请求失败: RemoteDisconnected")
        return _frame(12)

    def flaky_sina(**_kwargs):
        calls.append("sina")
        raise RuntimeError("新浪返回 HTML 风控页（请求过于频繁，请稍后重试）")

    monkeypatch.setattr(spot_service, "_fetch_eastmoney", flaky_em)
    monkeypatch.setattr(spot_service, "_fetch_sina", flaky_sina)
    monkeypatch.setattr(spot_service, "_SOURCE_ATTEMPTS", 2)
    monkeypatch.setattr(spot_service.time, "sleep", lambda *_args: None)

    df = spot_service.fetch_spot_frame()

    assert calls == ["em", "sina", "em"]
    assert len(df) == 100
    assert df.iloc[0]["最新价"] == 12


def _em_page(pn: int, size: int, total: int) -> dict:
    return {
        "rc": 0,
        "data": {
            "total": total,
            "diff": [
                {"f12": f"{pn}{i:05d}", "f14": "测试", "f2": 10.0, "f3": 1.5, "f6": 2e8}
                for i in range(size)
            ],
        },
    }


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _FakeSession:
    def __init__(self, pages: dict[int, dict], bad_host: str = ""):
        self.pages = pages
        self.bad_host = bad_host
        self.urls: list[str] = []

    def get(self, url, params=None, timeout=None, **_kwargs):
        self.urls.append(url)
        if self.bad_host and self.bad_host in url:
            raise RuntimeError("RemoteDisconnected")
        return _FakeResponse(self.pages[int(params["pn"])])


def test_eastmoney_pagination_merges_all_pages(monkeypatch):
    pages = {1: _em_page(1, 200, 500), 2: _em_page(2, 200, 500), 3: _em_page(3, 100, 500)}
    session = _FakeSession(pages)
    monkeypatch.setattr(spot_service, "_session", lambda _referer: session)
    monkeypatch.setattr(spot_service.time, "sleep", lambda *_args: None)

    df = spot_service._fetch_eastmoney()

    assert len(df) == 500
    assert [url.split("//")[1].split("/")[0] for url in session.urls][0] == spot_service._EM_HOSTS[0]
    assert df.iloc[0]["最新价"] == 10.0
    assert df.iloc[0]["涨跌幅"] == 1.5


def test_eastmoney_rotates_host_when_primary_is_down(monkeypatch):
    """82.push2 断连时自动切到备用域名（线上最常见的故障形态）。"""
    attempts: list[str] = []

    class Session(_FakeSession):
        def get(self, url, params=None, timeout=None, **_kwargs):
            attempts.append(url)
            return super().get(url, params=params, timeout=timeout)

    monkeypatch.setattr(spot_service, "_EM_HOSTS", ("bad.push2.eastmoney.com", "good.push2.eastmoney.com"))
    monkeypatch.setattr(
        spot_service,
        "_session",
        lambda _referer: Session({1: _em_page(1, 5, total=5)}, bad_host="bad."),
    )
    monkeypatch.setattr(spot_service.time, "sleep", lambda *_args: None)

    df = spot_service._fetch_eastmoney()

    assert len(df) == 5
    assert any("good.push2" in url for url in attempts)


def test_spot_frame_rejects_all_zero_snapshot(monkeypatch):
    """盘前全 0 快照视为不可用，继续降级而不是直接返回。"""
    monkeypatch.setattr(spot_service, "_fetch_eastmoney", lambda **_kwargs: _frame(0))
    monkeypatch.setattr(spot_service, "_fetch_sina", lambda **_kwargs: _frame(0))
    monkeypatch.setattr(spot_service, "_SOURCE_ATTEMPTS", 1)
    monkeypatch.setattr(spot_service.time, "sleep", lambda *_args: None)

    with pytest.raises(RuntimeError) as exc:
        spot_service.fetch_spot_frame()

    assert "有效价格不足" in str(exc.value)


@pytest.mark.asyncio
async def test_force_refresh_bypasses_persistent_snapshot(monkeypatch):
    async def fail_if_loaded():
        raise AssertionError("force refresh must not load the persistent snapshot")

    async def ignore_save(_rows):
        return None

    monkeypatch.setattr(market, "_load_spot_db", fail_if_loaded)
    monkeypatch.setattr(market, "_save_spot_db", ignore_save)
    monkeypatch.setattr(market.spot_service, "fetch_spot_frame", lambda: _frame(10))
    market._spot_cache = None
    market._last_live_fetch = None
    market._last_live_failure = None

    rows = await market._get_spot(force=True)

    assert rows[0]["price"] == 10


@pytest.mark.asyncio
async def test_cooldown_skips_throttled_source(monkeypatch):
    """行情源被风控后进入冷却：不再重复打源，直接快速失败。"""

    async def no_db(**_kwargs):
        return None

    monkeypatch.setattr(market, "_load_spot_db", no_db)
    monkeypatch.setattr(
        market,
        "_fetch_live_spot_rows",
        lambda: pytest.fail("冷却期内不应再请求行情源"),
    )
    market._spot_cache = None
    market._last_live_failure = time.monotonic()

    with pytest.raises(RuntimeError) as exc:
        await market._get_spot(force=True)

    assert "冷却" in str(exc.value)
    market._last_live_failure = None


def test_live_fetch_falls_back_to_service_when_sources_are_unusable(monkeypatch):
    monkeypatch.setattr(
        market.spot_service,
        "fetch_spot_frame",
        lambda: _frame(0),  # 全 0 快照
    )

    with pytest.raises(RuntimeError) as exc:
        market._fetch_live_spot_rows()

    assert "有效价格不足" in str(exc.value)
