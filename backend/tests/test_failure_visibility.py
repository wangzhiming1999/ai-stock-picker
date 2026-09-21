"""「失败必须可见」的守卫。

本项目反复踩同一个坑：功能坏掉时不报错，只是**变成空**。
界面上一块空白既可能是「今天没事发生」，也可能是「取数炸了」，两者长得一模一样，
于是用户只能等到某个数字明显不对才发现 —— 而那时已经过了好几轮。

本文件锁定两类刚补上的可见性：

1. 简报复盘块：持仓盈亏与今日预警**都**取数失败时，过去会 `except: pass`，
   而前端在 `summary` 与 `alerts_today` 都为空时会把整块隐藏 —— 失败等于彻底消失。
   现在失败说明并进 `summary`，走既有的渲染路径显示出来。
2. 策略回测基准：沪深300 取数失败原本静默 `None`，前端只显示「—」，
   与「还没算」无法区分；而基准正是判断「这套策略跑赢没有」的那一半。
   现在附 `benchmark_note` 说明原因。
"""
import datetime as dt

import pandas as pd
import pytest

from app.services import backtest_service as bts
from app.services import briefing_service as bs


def _fake_frame(n: int = 60) -> pd.DataFrame:
    dates = [dt.date(2025, 1, 1) + dt.timedelta(days=i) for i in range(n)]
    return pd.DataFrame({"date": pd.to_datetime(dates), "close": [10.0 + i * 0.1 for i in range(n)]})


class ReviewFailureVisibilityTests:
    @pytest.mark.asyncio
    async def test_review_states_failures_instead_of_vanishing(self, monkeypatch):
        async def _boom(*args, **kwargs):
            raise RuntimeError("supabase down")

        monkeypatch.setattr(bs.portfolio_service, "list_holdings", _boom)
        from app.services import alert_service

        monkeypatch.setattr(alert_service, "list_events", _boom)

        review = await bs._build_review("user-1")

        assert review is not None
        # 两个数据源都挂了，但必须留下可见的说明 —— 前端靠 summary 决定这一块要不要渲染
        assert review["summary"], "复盘块失败时不能返回空 summary（前端会整块隐藏）"
        assert review["summary"].count("取数失败") == 2
        assert review["holdings_pnl"] is None

    @pytest.mark.asyncio
    async def test_review_without_user_needs_no_data(self):
        assert await bs._build_review(None) is None


class BenchmarkFailureVisibilityTests:
    def test_missing_benchmark_is_explained_not_silent(self, monkeypatch):
        monkeypatch.setattr(bts, "_fetch_history", lambda code, start, end: _fake_frame())

        def _boom(*args, **kwargs):
            raise RuntimeError("sina down")

        monkeypatch.setattr(bts.akshare_guard, "call", _boom)

        result = bts.run_backtest(bts.BacktestParams(codes=["600519"], rebalance_days=5))

        assert "error" not in result, result
        assert result["benchmark_return"] is None
        assert "取数失败" in result["benchmark_note"]

    def test_present_benchmark_carries_no_note(self, monkeypatch):
        monkeypatch.setattr(bts, "_fetch_history", lambda code, start, end: _fake_frame())

        bench = pd.DataFrame(
            {
                "date": pd.to_datetime([dt.date(2025, 1, 1) + dt.timedelta(days=i) for i in range(60)]),
                "close": [4000.0 + i * 5 for i in range(60)],
            }
        )
        monkeypatch.setattr(bts.akshare_guard, "call", lambda *a, **kw: bench)

        result = bts.run_backtest(bts.BacktestParams(codes=["600519"], rebalance_days=5))

        assert result["benchmark_return"] is not None
        assert result["benchmark_note"] is None
