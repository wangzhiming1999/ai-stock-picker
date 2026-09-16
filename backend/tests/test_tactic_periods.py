"""多周期共振的「按周期取数」链路的测试。

背景（2026-09-16 实测）：腾讯历史 K 线端点的日线硬上限是 640 根，从 640 根日线重采样
最多得到 ~33 根月线，而 MACD(12,26,9) 需要 slow+signal = 35 根才成形 ——
于是「多周期共振」在**任何股票、任何时点**都只能返回 insufficient_data，
既不会命中、也不会报错，属于最典型的「静默失效」。

本文件锁定三件事：
1. 只有声明了 extra_periods 的技巧才会产生额外周期请求（其余技巧零额外流量）；
2. 周线/月线会被真正塞进判定上下文，让该技巧能够命中；
3. 回测回放周期 K 线时按评估日切片，并替换进行中那根的收盘，不偷看未来。
"""
import datetime as dt

import pytest

from app.models import StockHistory, StockQuote
from app.services import data_service, pattern_service, tactic_backtest_service as bt


def _dates(n: int, start: dt.date = dt.date(2024, 1, 1)) -> list[str]:
    return [(start + dt.timedelta(days=i)).isoformat() for i in range(n)]


def _hist(closes, dates=None) -> StockHistory:
    n = len(closes)
    return StockHistory(
        dates=list(dates) if dates is not None else _dates(n),
        closes=list(closes),
        volumes=[1000.0] * n,
        opens=list(closes),
        highs=list(closes),
        lows=list(closes),
    )


def _v_shape(n: int, up: int = 3) -> list[float]:
    """浅跌 + 最后 3 根急拉的 V 形：MACD 金叉落在最后 3 根内，且价格全程为正。

    跌速取得很缓（0.05/根）是为了让 640 根的长序列也不会跌到 0 以下 ——
    负价格会让回测的前向收益直接判为无效样本。
    """
    vals = [100.0]
    for _ in range(n - up - 1):
        vals.append(vals[-1] - 0.05)
    for _ in range(up):
        vals.append(vals[-1] + 3.0)
    return vals


class _FetchSpy:
    """记录 (code, period) 调用，按周期返回预置 K 线。"""

    def __init__(self, by_period: dict[str, StockHistory]) -> None:
        self.by_period = by_period
        self.calls: list[tuple[str, str]] = []

    def __call__(self, code: str, days: int = 120, *, period: str = "day"):
        self.calls.append((code, period))
        if period == "intraday":
            return None
        return self.by_period.get(period)

    @property
    def periods(self) -> set[str]:
        return {p for _, p in self.calls}


@pytest.fixture
def patch_sources(monkeypatch):
    """把行情/K 线的取数全部换成可控桩函数，测试不触网。"""

    def _apply(by_period: dict[str, StockHistory], codes=("000001",)):
        spy = _FetchSpy(by_period)
        monkeypatch.setattr(data_service, "get_history", spy)
        monkeypatch.setattr(
            data_service,
            "get_spot_quote",
            lambda cs: [StockQuote(code=c, name=f"票{c}", price=10.0, change_pct=1.0, turnover=2.0) for c in cs],
        )
        monkeypatch.setattr(data_service, "get_intraday_history", lambda c, p="5m": None)
        return spy

    return _apply


@pytest.mark.asyncio
async def test_check_codes_skips_extra_periods_for_single_period_tactics(patch_sources):
    spy = patch_sources({"day": _hist([10.0] * 120)})

    rows = await pattern_service.check_codes(["000001"], ["guillotine"])

    assert spy.periods == {"day"}
    assert rows[0]["tactics"][0]["key"] == "guillotine"


@pytest.mark.asyncio
async def test_check_codes_fetches_week_and_month_for_cycle_resonance(patch_sources):
    spy = patch_sources(
        {
            "day": _hist(_v_shape(120)),
            "week": _hist(_v_shape(60)),
            "month": _hist(_v_shape(40)),
        }
    )

    rows = await pattern_service.check_codes(["000001"], ["cycle_resonance"])

    assert spy.periods == {"day", "week", "month"}
    result = rows[0]["tactics"][0]
    # 改造前这里恒为 insufficient_data（月线只能重采样出 ~33 根）
    assert result["matched"] is True
    assert result["status"] == "matched"


@pytest.mark.asyncio
async def test_load_tactic_periods_makes_no_request_without_declaration(patch_sources):
    spy = patch_sources({})

    assert await pattern_service.load_tactic_periods(["000001"], ["guillotine"]) == {}
    assert spy.calls == []


@pytest.mark.asyncio
async def test_load_period_histories_drops_missing_results(patch_sources):
    patch_sources({"month": _hist(_v_shape(40))})

    loaded = await pattern_service.load_period_histories(["000001", "600519"], "month")
    assert set(loaded) == {"000001", "600519"}

    # 该周期没有数据（桩函数返回 None）→ 不放进 ctx，让 detector 走 insufficient_data
    assert await pattern_service.load_period_histories(["000001"], "week") == {}


@pytest.mark.asyncio
async def test_load_period_histories_survives_source_failure(monkeypatch):
    def _boom(code, days=120, *, period="day"):
        raise RuntimeError("行情源被风控")

    monkeypatch.setattr(data_service, "get_history", _boom)

    # 单只票报错不能把整批周期数据打掉（否则一个异常会让形态判定整体 502）
    assert await pattern_service.load_period_histories(["000001", "600519"], "month") == {}


class TestPeriodCursor:
    """回测回放：周期 K 线必须按评估日切片，不能看到未来。"""

    def test_monthly_slice_includes_in_progress_bar(self):
        hist = _hist(
            [10.0, 11.0, 12.0, 13.0, 14.0],
            dates=["2026-01-30", "2026-02-27", "2026-03-31", "2026-04-30", "2026-05-29"],
        )
        cursor = bt._PeriodCursor(hist, "month")

        sliced = cursor.as_of("2026-03-15", live_close=11.5)

        # 3 月的月线在 3-15 当天还没走完，但实盘当天看得到「3 月至今」这一根
        assert len(sliced.closes) == 3
        # 进行中那根的收盘必须换成当日收盘，否则就是用月末收盘偷看未来
        assert sliced.closes[-1] == 11.5
        assert sliced.closes[1] == 11.0

    def test_slice_excludes_later_bars(self):
        hist = _hist(
            [10.0, 11.0, 12.0, 13.0],
            dates=["2026-01-30", "2026-02-27", "2026-03-31", "2026-04-30"],
        )
        cursor = bt._PeriodCursor(hist, "month")

        sliced = cursor.as_of("2026-02-10", live_close=10.5)

        assert len(sliced.closes) == 2
        assert max(sliced.dates) <= "2026-02-28"

    def test_returns_none_before_first_bar(self):
        hist = _hist([10.0, 11.0], dates=["2026-01-30", "2026-02-27"])
        cursor = bt._PeriodCursor(hist, "month")

        assert cursor.as_of("2025-12-20", live_close=10.0) is None

    def test_weekly_slice_aligns_by_iso_week(self):
        # 2026-01-09 / 16 / 23 / 30 均为周五
        hist = _hist([10.0, 11.0, 12.0, 13.0], dates=["2026-01-09", "2026-01-16", "2026-01-23", "2026-01-30"])
        cursor = bt._PeriodCursor(hist, "week")

        # 01-20（周二）与 01-23（周五）同属一个 ISO 周 → 进行中的那根要算进来
        assert len(cursor.as_of("2026-01-20", 12.5).closes) == 3
        # 01-10（周六）与 01-09 同周
        assert len(cursor.as_of("2026-01-10", 10.5).closes) == 1
        # 01-04 属于上一周 → 还没有任何周线
        assert cursor.as_of("2026-01-04", 10.0) is None


class TestEvaluateSyncPeriods:
    def test_reports_not_evaluated_instead_of_silently_skipping(self):
        """历史长度覆盖不了预热期时必须明说，不能混进「0 次命中」。"""
        items = bt._evaluate_sync({"000001": _hist([10.0] * 20)}, ["guillotine"], 10, 250)

        item = items[0]
        assert item["stocks_evaluated"] == 0
        assert item["status"] == "insufficient_data"
        assert "未纳入评估" in item["verdict"]

    def test_cycle_resonance_enters_evaluation_with_period_data(self):
        daily = _hist(_v_shape(640))
        extra = {"000001": {"week": _hist(_v_shape(60)), "month": _hist(_v_shape(40))}}

        item = bt._evaluate_sync({"000001": daily}, ["cycle_resonance"], 10, 250, extra)[0]

        # 改造前 warmup=750 > 日线 640 根 → 该技巧每只票都不进评估（stocks_evaluated=0）
        assert item["stocks_evaluated"] == 1
        assert item["eval_points"] > 0

    def test_cycle_resonance_degrades_without_period_data(self):
        daily = _hist(_v_shape(640))

        item = bt._evaluate_sync({"000001": daily}, ["cycle_resonance"], 10, 250)[0]

        # 仍会被评估（日线够长），但月线缺失时不可能命中 —— 不能因此当成「通过」
        assert item["stocks_evaluated"] == 1
        assert item["signals"] == 0
