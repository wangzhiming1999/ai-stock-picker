"""策略回测引擎：基于历史K线回测选股策略。

流程：拉取股票池历史K线 → 按调仓周期计算策略分 → 选 top N 持有 → 统计收益/回撤/夏普/胜率。
"""
from __future__ import annotations

import datetime as dt
import math
import time

# 注意：akshare 一律**函数内延迟导入**（见各使用点）。它的 __init__ 会 eager import 数百
# 子模块，顶层导入既拖慢冷启动，又会在依赖层异常时连带本模块（乃至 app.main）导入失败
# —— 2026-10-06 全站 500 事故的放大机制。
import pandas as pd

from app.services import akshare_guard, calibers
from app.services.cache_utils import put_bounded

# 策略回测默认股票池（18 只，各行业代表性标的，控制数量以适配 Serverless 超时）。
# ⚠️ 与 tactic_backtest_service.TACTIC_BACKTEST_POOL（42 只，形态回测用）不是同一个池，
#    两者历史上都叫 DEFAULT_POOL，改参数时极易混用 —— 重命名即为此。
STRATEGY_BACKTEST_POOL = [
    "600519", "000858", "300750", "601318", "600036", "000333",
    "601012", "002594", "600030", "000725", "601888", "600887",
    "300059", "603288", "600809", "002475", "601088", "600585",
]

# 基准指数（沪深300）
BENCHMARK = "sh000300"

# 历史K线内存缓存：key=(code,start,end) -> (timestamp, df, ttl, is_fetch_failure)。
#
# ⚠️ 「取数失败」与「这段区间真的没有数据」必须分开计时：失败只做 _HIST_TTL_FAIL 秒的
#    短负缓存。此前两者共用 30 分钟 TTL，一次瞬时 SSLError 会让该票在半小时内**恒为空
#    且不报错** —— 表现为回测池子悄悄变小（18 只跑出 16/15），同一参数复跑结果都不一样。
_history_cache: dict[tuple, tuple[float, pd.DataFrame, float, bool]] = {}
_HIST_TTL = 1800
_HIST_TTL_FAIL = 120
_HIST_CACHE_MAX = 128

# 逐只拉历史时，单只偶发失败（SSLError / 读超时）在实测里约每 18 只出现 2 只。
# 而 18 只池少 2 只足以让同一策略的总收益从 +28% 掉到 +14% —— 失败必须重试一次再说，
# 否则「池子缺了谁」直接决定结论方向。
_HIST_FETCH_ATTEMPTS = 2
_HIST_RETRY_BACKOFF = 0.3


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
        self.codes = codes or STRATEGY_BACKTEST_POOL
        self.start_date = start_date
        self.end_date = end_date or dt.date.today().isoformat()
        self.top_n = max(1, min(top_n, len(self.codes)))
        self.rebalance_days = max(1, rebalance_days)
        self.initial_capital = initial_capital


def _symbol(code: str) -> str:
    code = code.strip()
    return f"sh{code}" if code.startswith(("6", "9")) else f"sz{code}"


def _fetch_history(code: str, start: str, end: str, *, failed: list[str] | None = None) -> pd.DataFrame:
    """获取历史K线（带缓存 + 一次重试）。

    取数异常与「这段区间真的没有数据」是两件事，必须分开处理：异常先重试一次，
    仍失败才做 `_HIST_TTL_FAIL` 的短负缓存，并把代码登记进 ``failed`` 交给调用方报出来。
    两者共用长 TTL 的旧行为会把一次瞬时失败锁成半小时的空数据，且全程不报错。
    """
    import akshare as ak

    key = (code, start, end)
    now = time.monotonic()
    cached = _history_cache.get(key)
    if cached and now - cached[0] < cached[2]:
        if failed is not None and cached[3]:
            failed.append(code)
        return cached[1]

    df = None
    for attempt in range(_HIST_FETCH_ATTEMPTS):
        try:
            df = akshare_guard.call(
                ak.stock_zh_a_hist_tx,
                symbol=_symbol(code),
                start_date=start.replace("-", ""),
                end_date=end.replace("-", ""),
            )
        except Exception:
            df = None
        if df is not None:
            break
        if attempt + 1 < _HIST_FETCH_ATTEMPTS:
            time.sleep(_HIST_RETRY_BACKOFF)

    if df is None:
        # 取数失败：短负缓存 + 登记，绝不占用 30 分钟窗口
        put_bounded(
            _history_cache, key, (now, pd.DataFrame(), _HIST_TTL_FAIL, True), max_entries=_HIST_CACHE_MAX
        )
        if failed is not None:
            failed.append(code)
        return pd.DataFrame()

    if df.empty:
        # 真没有数据（新股 / 区间外）：按正常 TTL 缓存，且不算取数失败
        put_bounded(_history_cache, key, (now, pd.DataFrame(), _HIST_TTL, False), max_entries=_HIST_CACHE_MAX)
        return pd.DataFrame()

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    put_bounded(_history_cache, key, (now, df, _HIST_TTL, False), max_entries=_HIST_CACHE_MAX)
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
    if strategy == "quality_momentum":
        return _momentum_score(df) if _trend_score(df) >= 5 else -999
    return 0.0


def _fetch_failure_note(fetch_failed: list[str], loaded: int) -> str | None:
    """取数失败清单 → 一句人话。全成功则为 None。"""
    if not fetch_failed:
        return None
    return (
        f"{len(fetch_failed)} 只取数失败（{', '.join(fetch_failed)}），"
        f"本次按实际取到的 {loaded} 只计算；失败不等于没有数据，重跑会重新尝试"
    )


def _close_on_or_before(df: pd.DataFrame | None, trade_date: dt.date) -> float | None:
    """取 trade_date 当日或之前最后一个收盘价；取不到返回 None（不猜价格）。"""
    if df is None or df.empty:
        return None
    rows = df[df["date"].dt.date <= trade_date]
    if rows.empty:
        return None
    return float(rows["close"].iloc[-1])


def _value_positions(
    portfolio: list[tuple[str, float]],
    histories: dict[str, pd.DataFrame],
    trade_date: dt.date,
    last_price: dict[str, float],
) -> float:
    """按 trade_date 给持仓估值。

    取不到当日价（数据缺口 / 停牌 / 该票不在 histories 里）时退回**最近一次已知价**。
    这里的返回值是组合市值的分子，按 0 计等于把该持仓凭空抹掉 —— 旧代码写的
    `shares * 0` 注释是「停牌按原值」，行为却是清零，注释与实现正好相反。
    """
    total = 0.0
    for code, shares in portfolio:
        price = _close_on_or_before(histories.get(code), trade_date)
        if price is None:
            price = last_price.get(code)
        if price is None:
            continue  # 从未有过已知价：跳过，不虚构价格
        last_price[code] = price
        total += shares * price
    return total


def run_backtest(params: BacktestParams) -> dict:
    """执行回测。"""
    start = params.start_date
    end = params.end_date

    # 1. 拉取全部股票历史（只拉一次，减少请求）
    histories: dict[str, pd.DataFrame] = {}
    fetch_failed: list[str] = []
    for code in params.codes:
        try:
            df = _fetch_history(code, start, end, failed=fetch_failed)
        except Exception:
            # 逐只隔离：单只异常不该拖垮整轮回测；但**必须登记**，
            # 否则「代码写错了」会伪装成「这只票没数据」，池子静默少一只。
            if code not in fetch_failed:
                fetch_failed.append(code)
            continue
        if not df.empty:
            histories[code] = df

    if not histories:
        return {"error": "未获取到历史数据", "fetch_failed": fetch_failed}

    # 取数失败必须让调用方看得见：池子静默变小只会被读成「策略变差」
    data_note = _fetch_failure_note(fetch_failed, len(histories))

    # 2. 构建统一交易日历（取所有股票的并集日期）
    all_dates = set()
    for df in histories.values():
        all_dates.update(df["date"].dt.date)
    all_dates = sorted(all_dates)

    # 3. 调仓
    capital = params.initial_capital
    cash_balance = params.initial_capital
    equity_curve: list[dict] = []
    portfolio: list[tuple[str, float]] = []  # (code, shares)
    last_price: dict[str, float] = {}  # 最近一次已知收盘价，供数据缺口时估值

    rebalance_dates = all_dates[:: params.rebalance_days]

    for i, trade_date in enumerate(rebalance_dates):
        # 先结算上一期持仓收益
        if i > 0 and portfolio:
            capital = _value_positions(portfolio, histories, trade_date, last_price) + cash_balance
            equity_curve.append(
                {
                    "date": str(trade_date),
                    "value": round(float(capital), 2),
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
            # Rank with information available before the execution date. Using
            # the same day's close here leaks the outcome into the signal.
            past = df[df["date"].dt.date < trade_date]
            if past.empty:
                continue
            scores.append((code, _score(past, params.strategy)))
        scores.sort(key=lambda x: x[1], reverse=True)
        picked = [c for c, _ in scores[: params.top_n] if _score(histories[c][histories[c]["date"].dt.date < trade_date], params.strategy) > -999]

        # 等权买入
        if picked and capital > 0:
            per_stock = capital / len(picked)
            portfolio = []
            cash_balance = capital
            for code in picked:
                price = _close_on_or_before(histories.get(code), trade_date)
                if price is None or price <= 0:
                    continue
                shares = int(per_stock // price)
                if shares > 0:
                    portfolio.append((code, shares))
                    last_price[code] = price
                    cash_balance -= shares * price

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
    benchmark_note = None
    try:
        import akshare as ak

        bdf = akshare_guard.call(ak.stock_zh_index_daily, symbol=BENCHMARK)
        bdf["date"] = pd.to_datetime(bdf["date"])
        bdf = bdf[bdf["date"].dt.date >= dt.date.fromisoformat(start)]
        bdf = bdf[bdf["date"].dt.date <= dt.date.fromisoformat(equity_curve[-1]["date"])]
        if len(bdf) > 1:
            benchmark_return = (float(bdf["close"].iloc[-1]) / float(bdf["close"].iloc[0]) - 1) * 100
        else:
            benchmark_note = "基准（沪深300）在回测区间内取不到足够数据，本次未计算基准收益"
    except Exception as e:
        # 取数失败原本是静默 pass → 前端只显示「—」，与「还没跑」无法区分。
        # 但基准恰恰是判断「这策略到底跑赢没有」的那一半，缺了必须说明原因。
        benchmark_note = f"基准（沪深300）取数失败（{type(e).__name__}），本次未计算基准收益"

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
        # 基准为空时说明原因（取数失败 / 区间数据不足），别让前端只能显示「—」
        "benchmark_note": benchmark_note,
        "equity_curve": equity_curve,
        "pool_size": len(histories),
        # 取数失败清单 + 说明：池子缺了谁必须能看见，否则只会被读成「策略不行」
        "fetch_failed": fetch_failed,
        "data_note": data_note,
        # 口径随数据一起下发：这里的「胜率」是**调仓期**口径，样本单位是期不是票
        "caliber": calibers.describe("strategy_backtest"),
    }
