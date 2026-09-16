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


# ---------------- 冷却状态跨实例共享 ----------------
# 背景：Serverless 多实例内存不互通，只做进程内冷却会出现「A 实例已被风控、
# B 实例仍去撞行情源」，既慢又延长封禁。失败时间落共享表后，冷却窗口对所有实例生效。


async def _no_db(**_kwargs):
    return None


async def _noop(*_args, **_kwargs):
    return None


def _reset_spot_state() -> None:
    market._spot_cache = None
    market._last_live_failure = None
    market._last_live_fetch = None


@pytest.mark.asyncio
async def test_shared_failure_puts_other_instances_into_cooldown(monkeypatch):
    """本实例内存里没有失败记录，但共享表里有 → 仍必须进入冷却、不打行情源。"""

    async def shared_failure():
        return time.time() - 10  # 10 秒前失败过

    monkeypatch.setattr(market, "_load_spot_db", _no_db)
    monkeypatch.setattr(market, "_load_shared_failure", shared_failure)
    monkeypatch.setattr(market, "_fetch_live_spot_rows", lambda: pytest.fail("冷却期内不应请求行情源"))
    _reset_spot_state()

    with pytest.raises(RuntimeError) as exc:
        await market._get_spot(force=True)

    assert "冷却" in str(exc.value)
    _reset_spot_state()


@pytest.mark.asyncio
async def test_stale_shared_failure_does_not_block_forever(monkeypatch):
    """共享标记超出冷却窗口后必须放行，否则一次风控会永久锁死行情源。"""

    async def old_failure():
        return time.time() - (market._SPOT_COOLDOWN + 5)

    monkeypatch.setattr(market, "_load_spot_db", _no_db)
    monkeypatch.setattr(market, "_load_shared_failure", old_failure)
    monkeypatch.setattr(market, "_save_spot_db", _noop)
    monkeypatch.setattr(market, "_clear_shared_failure", _noop)
    monkeypatch.setattr(market.spot_service, "fetch_spot_frame", lambda: _frame(10))
    _reset_spot_state()

    rows = await market._get_spot(force=True)

    assert rows[0]["price"] == 10
    _reset_spot_state()


@pytest.mark.asyncio
async def test_failure_writes_shared_marker(monkeypatch):
    """失败时必须写共享标记，否则其他实例不会进入冷却。"""
    saved: list[bool] = []

    async def record() -> None:
        saved.append(True)

    def boom():
        raise RuntimeError("东财行情请求失败: RemoteDisconnected")

    monkeypatch.setattr(market, "_load_spot_db", _no_db)
    monkeypatch.setattr(market, "_load_shared_failure", _noop)
    monkeypatch.setattr(market, "_save_shared_failure", record)
    monkeypatch.setattr(market, "_fetch_live_spot_rows", boom)
    _reset_spot_state()

    with pytest.raises(RuntimeError):
        await market._get_spot(force=True)

    assert saved == [True]
    _reset_spot_state()


@pytest.mark.asyncio
async def test_success_clears_shared_marker(monkeypatch):
    """行情源恢复后必须清标记，否则旧标记会把后续请求误判为冷却中。"""
    cleared: list[bool] = []

    async def record() -> None:
        cleared.append(True)

    monkeypatch.setattr(market, "_load_spot_db", _no_db)
    monkeypatch.setattr(market, "_load_shared_failure", _noop)
    monkeypatch.setattr(market, "_save_shared_failure", _noop)
    monkeypatch.setattr(market, "_save_spot_db", _noop)
    monkeypatch.setattr(market, "_clear_shared_failure", record)
    monkeypatch.setattr(market.spot_service, "fetch_spot_frame", lambda: _frame(10))
    _reset_spot_state()

    await market._get_spot(force=True)

    assert cleared == [True]
    _reset_spot_state()


@pytest.mark.asyncio
async def test_shared_cooldown_degrades_when_table_missing(monkeypatch):
    """状态表未建 / Supabase 不可用时不得抛错，静默降级为纯进程内冷却。"""

    class _BoomTable:
        def table(self, *_args, **_kwargs):
            raise RuntimeError('relation "market_source_state" does not exist')

    async def boom_client():
        return _BoomTable()

    monkeypatch.setattr(market.supabase_store, "is_configured", lambda: True)
    monkeypatch.setattr(market.supabase_store, "get_service_client", boom_client)

    assert await market._load_shared_failure() is None
    await market._save_shared_failure()  # 不应抛出
    await market._clear_shared_failure()


@pytest.mark.asyncio
async def test_spot_status_exposes_countdown(monkeypatch):
    """前端靠这个接口在冷却期禁用「强制刷新」按钮并展示倒计时。"""

    async def old_failure():
        return time.time() - 10

    monkeypatch.setattr(market, "_load_shared_failure", old_failure)
    monkeypatch.setattr(market, "_load_spot_db", _no_db)
    _reset_spot_state()

    status = await market.spot_status_endpoint()

    assert status["in_cooldown"] is True
    assert 0 < status["cooldown_seconds"] <= market._SPOT_COOLDOWN
    assert status["snapshot_size"] == 0
    _reset_spot_state()
