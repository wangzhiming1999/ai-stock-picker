"""四维榜全市场快照接入 _get_spot 三层回退的守卫测试。

背景：generate_quad_rankings 曾直连 _full_spot（fetch_spot_frame），是全项目唯一
绕过「内存 → Supabase 热快照 → 真拉+跨实例冷却」的全市场消费者 —— 源一抖就 502，
而 Supabase 里明明有热快照。这组测试锁定：
1. quad 取数必须走 market_routes._get_spot（冷却/缓存层）；
2. _get_spot 抛的冷却异常必须向上传播（不得绕过冷却去撞行情源）；
3. 旧 5 字段缓存行与富字段缓存行都能被归一化初筛消费；
4. _rows_from_spot_frame 必须保留富字段（pe/pb/turnover 等）供初筛直接使用。
"""
from __future__ import annotations

import asyncio

import pandas as pd
import pytest

from app.routes import market
from app.services import quad_service, regime_service


def _rich_frame(size: int = 120) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "代码": f"600{i:03d}",
                "名称": "测试股",
                "最新价": 10.0 + i * 0.1,
                "涨跌幅": 1.2,
                "成交额": 5e8,
                "换手率": 4.0,
                "市盈率-动态": 20.0,
                "市净率": 2.0,
                "量比": 1.5,
                "总市值": 8e9,
                "5分钟涨跌": 0.2,
            }
            for i in range(size)
        ]
    )


def _legacy_rows(size: int = 120) -> list[dict]:
    """market_spot_cache 里 2026-09-18 之前的旧 5 字段行。"""
    return [
        {"code": f"600{i:03d}", "name": "测试股", "price": 10.0, "change": 1.2, "amount": 5e8}
        for i in range(size)
    ]


def _reset_quad_cache() -> None:
    quad_service._full_spot_cache = None


def test_rich_frame_rows_keep_fundamental_fields():
    """_rows_from_spot_frame 必须保留富字段 —— 否则缓存行初筛退化为纯量价。"""
    rows = market._rows_from_spot_frame(_rich_frame())
    row = rows[0]
    assert row["pe"] == 20.0
    assert row["pb"] == 2.0
    assert row["turnover"] == 4.0
    assert row["volume_ratio"] == 1.5
    assert row["market_cap"] == 8e9
    assert row["change_5min"] == 0.2
    # 基础 5 字段契约不变
    assert row["code"] == "600000"
    assert row["price"] == 10.0
    assert row["change"] == 1.2


def test_rows_from_frame_tolerates_missing_rich_columns():
    """新浪等缺列数据源：富字段为 None，不抛 KeyError。"""
    df = pd.DataFrame(
        [{"代码": "600000", "名称": "测试", "最新价": 10.0, "涨跌幅": 1.0, "成交额": 1e8}]
    )
    row = market._rows_from_spot_frame(df)[0]
    assert row["pe"] is None
    assert row["volume_ratio"] is None
    assert row["turnover"] is None


@pytest.mark.asyncio
async def test_quad_uses_shared_get_spot(monkeypatch):
    """quad 取数必须走 _get_spot（三层回退），不得直连行情源。"""
    called = {"get_spot": 0, "direct": 0}

    async def fake_get_spot(force=False):
        called["get_spot"] += 1
        return _legacy_rows()

    def fail_direct(force=False):
        called["direct"] += 1
        raise AssertionError("quad 不得绕过 _get_spot 直连行情源")

    monkeypatch.setattr(market, "_get_spot", fake_get_spot)
    monkeypatch.setattr(quad_service, "_full_spot", fail_direct)
    _reset_quad_cache()

    rows = await quad_service.get_full_spot()

    assert called["get_spot"] == 1
    assert called["direct"] == 0
    assert len(rows) == 120
    row = rows[0]
    # 旧 5 字段行被归一化：amount(元)→amount_yi，change→change_pct
    assert row["amount_yi"] == pytest.approx(5.0)
    assert row["change_pct"] == pytest.approx(1.2)
    assert row["pe"] is None  # 旧行缺富字段 → 初筛走腾讯补全


@pytest.mark.asyncio
async def test_quad_normalizes_rich_cache_rows(monkeypatch):
    """富字段缓存行直接透传进初筛结构，不丢 pe/pb/量比。"""
    raw = market._rows_from_spot_frame(_rich_frame(size=60))

    async def fake_get_spot(force=False):
        return raw

    monkeypatch.setattr(market, "_get_spot", fake_get_spot)
    _reset_quad_cache()

    rows = await quad_service.get_full_spot()
    assert rows[0]["pe"] == 20.0
    assert rows[0]["turnover"] == 4.0
    assert rows[0]["amount_yi"] == pytest.approx(5.0)  # 成交额 5e8 元 = 5 亿
    assert rows[0]["market_cap_yi"] == pytest.approx(80.0)  # 8e9 元 = 80 亿


@pytest.mark.asyncio
async def test_quad_respects_cooldown(monkeypatch):
    """冷却期 _get_spot 抛 RuntimeError，必须向上传播 —— 不得绕过冷却撞行情源。"""

    async def cooling(force=False):
        raise RuntimeError("行情源被风控，冷却中（120s 后重试）")

    def fail_direct(force=False):
        raise AssertionError("冷却期内 quad 不得直连行情源")

    monkeypatch.setattr(market, "_get_spot", cooling)
    monkeypatch.setattr(quad_service, "_full_spot", fail_direct)
    _reset_quad_cache()

    with pytest.raises(RuntimeError, match="冷却"):
        await quad_service.get_full_spot()


@pytest.mark.asyncio
async def test_generate_quad_rankings_propagates_cooldown(monkeypatch):
    """榜单生成路径同样传播冷却异常（不再伪装成「候选池为空」）。"""

    async def cooling(force=False):
        raise RuntimeError("行情源被风控，冷却中（120s 后重试）")

    async def fake_calendar():
        return __import__("datetime").date(2026, 9, 18)

    monkeypatch.setattr(quad_service, "get_full_spot", cooling)
    monkeypatch.setattr(quad_service.trade_calendar_service, "last_trading_day", fake_calendar)
    quad_service._quad_cache.clear()

    with pytest.raises(RuntimeError, match="冷却"):
        await quad_service.generate_quad_rankings()


@pytest.mark.asyncio
async def test_preselect_works_on_legacy_rows_with_tencent_fill(monkeypatch):
    """旧 5 字段行：>半数缺 pe → 触发腾讯批量补全（每 60 只一请求）。"""
    from app.models import StockQuote

    legacy = _legacy_rows(size=120)

    def fake_get_spot_quote(codes):
        return [
            StockQuote(
                code=c,
                name="测试股",
                price=10.0,
                change_pct=1.2,
                turnover=4.0,
                volume=None,
                pe=20.0,
                pb=2.0,
                market_cap=8e9,
            )
            for c in codes
        ]

    monkeypatch.setattr(quad_service.data_service, "get_spot_quote", fake_get_spot_quote)
    normalized = [quad_service._normalize_shared_row(r) for r in legacy]
    pool = quad_service._preselect(normalized, top_n=40)
    assert pool, "旧缓存行 + 腾讯补全必须能产出候选池"
    assert all(p.get("pe") is not None for p in pool)


@pytest.mark.asyncio
async def test_regime_breadth_uses_shared_spot(monkeypatch):
    """市场宽度与四维榜同源：走 get_full_spot，冷却失败返回 None 不拖垮方向预测。"""
    calls = []

    async def fake_full_spot(force=False):
        calls.append("spot")
        return [
            {"code": "600000", "change_pct": 2.0, "amount_yi": 10.0},
            {"code": "000001", "change_pct": -2.0, "amount_yi": 10.0},
        ]

    monkeypatch.setattr(quad_service, "get_full_spot", fake_full_spot)
    breadth = await regime_service.fetch_breadth()
    assert calls == ["spot"]
    assert breadth is not None
    assert breadth["up_count"] == 1
    assert breadth["down_count"] == 1


@pytest.mark.asyncio
async def test_regime_breadth_swallows_cooldown(monkeypatch):
    """宽度只是附加证据：冷却失败必须返回 None，绝不能抛异常拖垮方向预测。"""

    async def cooling(force=False):
        raise RuntimeError("行情源被风控，冷却中（120s 后重试）")

    monkeypatch.setattr(quad_service, "get_full_spot", cooling)
    breadth = await regime_service.fetch_breadth()
    assert breadth is None
