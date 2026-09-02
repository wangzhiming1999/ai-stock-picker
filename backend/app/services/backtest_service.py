"""策略回测引擎：基于历史K线回测选股策略。

流程：拉取股票池历史K线 → 按调仓周期计算策略分 → 选 top N 持有 → 统计收益/回撤/夏普/胜率。
"""
from __future__ import annotations

import datetime as dt
import math
import time

import akshare as ak
import pandas as pd

# 默认股票池（各行业代表性标的，控制数量以适配 Serverless 超时）
DEFAULT_POOL = [
    "600519", "000858", "300750", "601318", "600036", "000333",
    "601012", "002594", "600030", "000725", "601888", "600887",
    "300059", "603288", "600809", "002475", "601088", "600585",
]

# 基准指数（沪深300）
BENCHMARK = "sh000300"

# 历史K线内存缓存：key=(code,start,end) -> (timestamp, df)，缓存 30 分钟
_history_cache: dict[tuple, tuple[float, pd.DataFrame]] = {}
_HIST_TTL = 1800


class BacktestParams:
    def __init__(
        self,
        strategy: str = "momentum",
        codes: list[str] | None = None,
        start_date: str = "2025-01-01",
        end_date: str = "",
        top_n: int = 5,
        rebalance_days: int = 5,
        initial_capital: float = 100000,
    ):
        self.strategy = strategy
        self.codes = codes or DEFAULT_POOL
        self.start_date = start_date
        self.end_date = end_date or dt.date.today().isoformat()
        self.top_n = max(1, min(top_n, len(self.codes)))
        self.rebalance_days = max(1, rebalance_days)
        self.initial_capital = initial_capital


def _symbol(code: str) -> str:
    code = code.strip()
    return f"sh{code}" if code.startswith(("6", "9")) else f"sz{code}"


def _fetch_history(code: str, start: str, end: str) -> pd.DataFrame:
    """获取历史K线（带缓存）。"""
    key = (code, start, end)
    now = time.monotonic()
    if key in _history_cache and now - _history_cache[key][0] < _HIST_TTL:
        return _history_cache[key][1]
    try:
        df = ak.stock_zh_a_hist_tx(
            symbol=_symbol(code),
            start_date=start.replace("-", ""),
            end_date=end.replace("-", ""),
        )
    except Exception:
        df = None
    if df is None or df.empty:
        empty = pd.DataFrame()
        _history_cache[key] = (now, empty)
        return empty
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    _history_cache[key] = (now, df)
    return df


def _momentum_score(df: pd.DataFrame, lookback: int = 20) -> float:
    if len(df) < lookback + 1:
        return 0.0
    return (df["close"].iloc[-1] / df["close"].iloc[-1 - lookback] - 1) * 100


def _trend_score(df: pd.DataFrame) -> float:
    if len(df) < 60:
        return 0.0
    closes = df["close"].values
    price = closes[-1]
    ma5 = closes[-5:].mean()
    ma20 = closes[-20:].mean()
    ma60 = closes[-60:].mean()
    score = 0.0
    if price > ma5:
        score += 2
    if ma5 > ma20:
        score += 3
    if ma20 > ma60:
        score += 3
    if price > ma60:
        score += 2
    return score


def _value_score(df: pd.DataFrame) -> float:
    """用价格位置近似估值（区间低位 = 相对便宜）。"""
    if len(df) < 60:
        return 0.0
    closes = df["close"].values
    low60 = closes[-60:].min()
    high60 = closes[-60:].max()
    price = closes[-1]
    if high60 <= low60:
        return 0.0
    pos = (price - low60) / (high60 - low60)
    return (1 - pos) * 10  # 越接近区间低位分数越高


def _volume_score(df: pd.DataFrame) -> float:
    if len(df) < 20:
        return 0.0
    amounts = df["amount"].values
    recent = amounts[-5:].mean()
    base = amounts[-20:-5].mean()
    if base <= 0:
        return 0.0
    ratio = recent / base
    # 放量（1.2~3倍）最健康
    if 1.2 <= ratio <= 3:
        return 5 + min(5, (ratio - 1.2) * 3)
    if ratio > 3:
        return 3
    return 1


def _score(df: pd.DataFrame, strategy: str) -> float:
    if df.empty:
        return -999
    if strategy == "momentum":
        return _momentum_score(df)
    if strategy == "trend":
        return _trend_score(df)
    if strategy == "value":
        return _value_score(df)
    if strategy == "volume":
        return _volume_score(df)
    if strategy == "all":
        return _momentum_score(df) / 5 + _trend_score(df) + _value_score(df) * 0.5 + _volume_score(df)
    return 0.0


def run_backtest(params: BacktestParams) -> dict:
    """执行回测。"""
    start = params.start_date
    end = params.end_date

    # 1. 拉取全部股票历史（只拉一次，减少请求）
    histories: dict[str, pd.DataFrame] = {}
    for code in params.codes:
        try:
            df = _fetch_history(code, start, end)
            if not df.empty:
                histories[code] = df
        except Exception:
            continue

    if not histories:
        return {"error": "未获取到历史数据"}

    # 2. 构建统一交易日历（取所有股票的并集日期）
    all_dates = set()
    for df in histories.values():
        all_dates.update(df["date"].dt.date)
    all_dates = sorted(all_dates)

    # 3. 调仓
    capital = params.initial_capital
    equity_curve: list[dict] = []
    portfolio: list[tuple[str, float]] = []  # (code, shares)
    holdings_value = capital

    rebalance_dates = all_dates[:: params.rebalance_days]

    for i, trade_date in enumerate(rebalance_dates):
        # 先结算上一期持仓收益
        if i > 0 and portfolio:
            prev_date = rebalance_dates[i - 1]
            period_value = 0.0
            for code, shares in portfolio:
                df = histories.get(code)
                if df is None:
                    continue
                rows = df[df["date"].dt.date <= trade_date]
                if rows.empty:
                    period_value += shares * 0  # 停牌按原值
                    continue
                price = rows["close"].iloc[-1]
                period_value += shares * price
            capital = period_value
            holdings_value = period_value
            equity_curve.append(
                {
                    "date": str(trade_date),
                    "value": round(float(period_value), 2),
                    "holdings": [c for c, _ in portfolio],
                }
            )
        else:
            equity_curve.append(
                {
                    "date": str(trade_date),
                    "value": round(float(capital), 2),
                    "holdings": [],
                }
            )

        # 换仓：计算策略分，选 top N
        scores: list[tuple[str, float]] = []
        for code, df in histories.items():
            past = df[df["date"].dt.date <= trade_date]
            if past.empty:
                continue
            scores.append((code, _score(past, params.strategy)))
        scores.sort(key=lambda x: x[1], reverse=True)
        picked = [c for c, _ in scores[: params.top_n] if _score(histories[c][histories[c]["date"].dt.date <= trade_date], params.strategy) > -999]

        # 等权买入
        if picked and capital > 0:
            per_stock = capital / len(picked)
            portfolio = []
            for code in picked:
                df = histories.get(code)
                rows = df[df["date"].dt.date <= trade_date]
                if rows.empty:
                    continue
                price = rows["close"].iloc[-1]
                if price <= 0:
                    continue
                shares = int(per_stock // price)
                if shares > 0:
                    portfolio.append((code, shares))

    # 4. 统计指标
    if len(equity_curve) < 2:
        return {"error": "回测区间过短"}

    values = [p["value"] for p in equity_curve]
    final_value = values[-1]
    total_return = (final_value / params.initial_capital - 1) * 100

    # 年化（按交易日年化）
    days = max((pd.Timestamp(equity_curve[-1]["date"]) - pd.Timestamp(equity_curve[0]["date"])).days, 1)
    years = days / 365
    annual_return = ((final_value / params.initial_capital) ** (1 / years) - 1) * 100 if years > 0 else 0

    # 最大回撤
    peak = values[0]
    max_drawdown = 0.0
    for v in values:
        peak = max(peak, v)
        dd = (peak - v) / peak * 100 if peak > 0 else 0
        max_drawdown = max(max_drawdown, dd)

    # 夏普（用各期收益率）
    returns = []
    for i in range(1, len(values)):
        if values[i - 1] > 0:
            returns.append(values[i] / values[i - 1] - 1)
    mean_r = sum(returns) / len(returns) if returns else 0
    std_r = math.sqrt(sum((r - mean_r) ** 2 for r in returns) / len(returns)) if len(returns) > 1 else 0
    sharpe = (mean_r / std_r * math.sqrt(252 / params.rebalance_days)) if std_r > 0 else 0

    # 胜率（正收益期占比）
    positive = sum(1 for r in returns if r > 0)
    win_rate = positive / len(returns) * 100 if returns else 0

    # 基准收益（沪深300，用新浪指数接口兜底）
    benchmark_return = None
    try:
        bdf = ak.stock_zh_index_daily(symbol=BENCHMARK)
        bdf["date"] = pd.to_datetime(bdf["date"])
        bdf = bdf[bdf["date"].dt.date >= dt.date.fromisoformat(start)]
        bdf = bdf[bdf["date"].dt.date <= dt.date.fromisoformat(equity_curve[-1]["date"])]
        if len(bdf) > 1:
            benchmark_return = (float(bdf["close"].iloc[-1]) / float(bdf["close"].iloc[0]) - 1) * 100
    except Exception:
        pass

    return {
        "strategy": params.strategy,
        "start": str(equity_curve[0]["date"]),
        "end": str(equity_curve[-1]["date"]),
        "initial_capital": float(params.initial_capital),
        "final_value": round(float(final_value), 2),
        "total_return": round(float(total_return), 2),
        "annual_return": round(float(annual_return), 2),
        "max_drawdown": round(float(max_drawdown), 2),
        "sharpe": round(float(sharpe), 2),
        "win_rate": round(float(win_rate), 1),
        "periods": len(returns),
        "benchmark_return": round(float(benchmark_return), 2) if benchmark_return is not None else None,
        "equity_curve": equity_curve,
        "pool_size": len(histories),
    }
