"""实战形态历史回测：用历史 K 线检验技巧是否有统计意义。

方法：**walk-forward** —— 只用「截至当日」的 K 线跑形态判定，命中后按当日收盘价入场，
统计其后 horizon 个交易日的前向收益。（形态由收盘决定，这些技巧本身也是收盘决策，
因此以当日收盘为入场价是忠于规则的口径。）

四个必须讲清楚的度量口径，否则「胜率 70%」就是自欺欺人：
1. **胜率按方向定义**：买入形态要「之后上涨」才算对，卖出形态要「之后下跌」才算对；
2. **必须对比基准**：同一区间、同一持有期、不挑时点的无条件表现。
   形态只有明显高于基准才有意义 —— 牛市里任何买入信号胜率都高；
3. **命中去重**：命中后 horizon 个交易日内不再重复计数，避免同一波行情被反复计入
   （否则一次持续下跌会被拆成几十次「成功逃顶」）；
4. **不可回测 / 不可得的项要明说**，不能静默当成通过：
   - 分时背离需要分钟级历史 K 线，当前数据源只有日线历史；
   - 天量见天价的「换手率 >30%」需要历史换手率，回测时按数据缺失处理。
"""
from __future__ import annotations

import asyncio
import datetime as dt
import statistics

from app.models import StockHistory
from app.services import data_service, pattern_service

# 默认回测股票池（控制在 10 只，避免单次回测过慢）
DEFAULT_POOL = [
    "600519", "000858", "300750", "601318", "600036",
    "000333", "601012", "002594", "600030", "600887",
]

DEFAULT_HORIZON = 10          # 前向持有期（交易日）
DEFAULT_EVAL_BARS = 250       # 每只票参与评估的最近交易日数
_MIN_EVAL_BARS = 60
_MAX_EVAL_BARS = 400
_MAX_POOL = 15
_MIN_SAMPLES = 8              # 命中次数低于此值不给出结论

# 需要分钟级历史、当前数据源无法回测的技巧
_NOT_BACKTESTABLE = {
    "intraday_divergence": "需要分钟级历史 K 线，当前数据源只提供日线历史，无法回测",
}

# 回测中拿不到的历史字段（按数据缺失处理，不参与判定）
_HISTORY_FIELD_NOTES = {
    "volume_peak": "「换手率 >30%」需历史换手率，回测中按数据缺失处理（仅按涨幅 + 天量判定）",
}


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def _prefix(hist: StockHistory, end: int) -> StockHistory:
    """取 [0, end) 切片：walk-forward 只允许用到「截至当日」的 K 线。"""
    return StockHistory(
        dates=hist.dates[:end],
        closes=hist.closes[:end],
        volumes=hist.volumes[:end] if hist.volumes else None,
        opens=hist.opens[:end] if hist.opens else None,
        highs=hist.highs[:end] if hist.highs else None,
        lows=hist.lows[:end] if hist.lows else None,
    )


def _forward(closes: list[float], i: int, horizon: int) -> tuple[float, float, float] | None:
    """从 closes[i] 入场、持有 horizon 个交易日的表现。

    返回 (持有收益 %, 期间最大浮盈 %, 期间最大浮亏 %)，均为相对入场价。
    """
    entry = closes[i]
    if entry <= 0 or i + horizon >= len(closes):
        return None
    path = closes[i + 1: i + horizon + 1]
    if not path:
        return None
    return (
        (closes[i + horizon] / entry - 1) * 100,
        (max(path) / entry - 1) * 100,
        (min(path) / entry - 1) * 100,
    )


def _blank(tactic: dict, horizon: int, status: str, note: str | None) -> dict:
    return {
        "key": tactic["key"],
        "name": tactic["name"],
        "category": tactic["category"],
        "direction": tactic["direction"],
        "desc": tactic["desc"],
        "status": status,
        "note": note,
        "horizon_days": horizon,
        "signals": 0,
        "eval_points": 0,
        "stocks_evaluated": 0,
        "win_definition": None,
        "win_rate": None,
        "avg_return": None,
        "median_return": None,
        "avg_max_gain": None,
        "avg_max_drawdown": None,
        "baseline_win_rate": None,
        "baseline_avg_return": None,
        "edge_win_rate": None,
        "edge_return": None,
        "by_stock": [],
    }


def _pack(
    tactic: dict,
    horizon: int,
    signals: list[tuple[float, float, float, str]],
    baseline: list[float],
    stocks: int,
    per_stock: dict[str, list[float]],
) -> dict:
    buy = tactic["direction"] == "buy"
    note = _HISTORY_FIELD_NOTES.get(tactic["key"])
    base = _blank(tactic, horizon, "insufficient_data", note)
    base["stocks_evaluated"] = stocks
    base["eval_points"] = len(baseline)
    base["signals"] = len(signals)
    base["win_definition"] = "之后上涨记为胜（买入形态）" if buy else "之后下跌记为胜（卖出形态）"

    if not signals or not baseline:
        base["note"] = note or "评估区间内未出现命中，样本不足以下结论"
        return base

    returns = [s[0] for s in signals]

    def _is_win(value: float) -> bool:
        return value > 0 if buy else value < 0

    win_rate = sum(1 for r in returns if _is_win(r)) / len(returns) * 100
    baseline_win = sum(1 for r in baseline if _is_win(r)) / len(baseline) * 100
    avg_return = statistics.fmean(returns)
    baseline_avg = statistics.fmean(baseline)
    # 卖出形态：价格跌得比基准更多才算「超额」，因此基准均值取反
    edge_return = (avg_return - baseline_avg) if buy else (baseline_avg - avg_return)

    base.update(
        status="ok" if len(returns) >= _MIN_SAMPLES else "insufficient_data",
        win_rate=round(win_rate, 1),
        avg_return=round(avg_return, 2),
        median_return=round(statistics.median(returns), 2),
        avg_max_gain=round(statistics.fmean([s[1] for s in signals]), 2),
        avg_max_drawdown=round(statistics.fmean([s[2] for s in signals]), 2),
        baseline_win_rate=round(baseline_win, 1),
        baseline_avg_return=round(baseline_avg, 2),
        edge_win_rate=round(win_rate - baseline_win, 1),
        edge_return=round(edge_return, 2),
        by_stock=[
            {"code": code, "signals": len(vals), "avg_return": round(statistics.fmean(vals), 2)}
            for code, vals in sorted(per_stock.items(), key=lambda kv: -len(kv[1]))[:8]
        ],
    )
    if base["status"] == "insufficient_data" and not base["note"]:
        base["note"] = f"仅 {len(returns)} 次命中（少于 {_MIN_SAMPLES} 次），样本不足以下结论"
    return base


def _evaluate_sync(
    hist_map: dict[str, StockHistory],
    keys: list[str],
    horizon: int,
    eval_bars: int,
) -> list[dict]:
    """对每只票、每条技巧做 walk-forward 评估。"""
    results: list[dict] = []
    for key in keys:
        tactic = pattern_service.TACTIC_MAP[key]
        if key in _NOT_BACKTESTABLE:
            results.append(_blank(tactic, horizon, "not_backtestable", _NOT_BACKTESTABLE[key]))
            continue

        detector = pattern_service.DETECTORS[key]
        warmup = int(tactic["warmup"])
        signals: list[tuple[float, float, float, str]] = []
        baseline: list[float] = []
        per_stock: dict[str, list[float]] = {}
        stocks = 0

        for code, hist in hist_map.items():
            closes = hist.closes
            n = len(closes)
            start = max(warmup, n - eval_bars)
            end = n - horizon
            if start >= end:
                continue
            stocks += 1
            last_hit = -10 ** 9
            stock_returns: list[float] = []
            for i in range(start, end):
                fwd = _forward(closes, i, horizon)
                if fwd is None:
                    continue
                baseline.append(fwd[0])
                if i - last_hit < horizon:
                    continue  # 去重：同一波行情只计一次
                try:
                    hit = detector(
                        {
                            "daily": _prefix(hist, i + 1),
                            "intraday": None,
                            "price": closes[i],
                            "turnover": None,  # 无历史换手率
                        }
                    )
                except Exception:
                    continue
                if not hit["matched"]:
                    continue
                signals.append((fwd[0], fwd[1], fwd[2], code))
                stock_returns.append(fwd[0])
                last_hit = i
            if stock_returns:
                per_stock[code] = stock_returns

        results.append(_pack(tactic, horizon, signals, baseline, stocks, per_stock))
    return results


async def evaluate(
    codes: list[str] | None = None,
    keys: list[str] | None = None,
    horizon: int = DEFAULT_HORIZON,
    eval_bars: int = DEFAULT_EVAL_BARS,
) -> dict:
    """回测入口：并发取日线后在线程池里跑 walk-forward。"""
    selected = [k for k in (keys or list(pattern_service.DETECTORS)) if k in pattern_service.DETECTORS]
    if not selected:
        return {"error": "没有可回测的技巧"}

    horizon = _clamp(int(horizon), 1, 30)
    eval_bars = _clamp(int(eval_bars), _MIN_EVAL_BARS, _MAX_EVAL_BARS)
    pool = [c.strip() for c in (codes or DEFAULT_POOL) if c and c.strip()][:_MAX_POOL]
    if not pool:
        return {"error": "股票池为空"}

    backtestable = [k for k in selected if k not in _NOT_BACKTESTABLE]
    warmup = max((int(pattern_service.TACTIC_MAP[k]["warmup"]) for k in backtestable), default=0)
    days = warmup + eval_bars + horizon + 5

    hists = await asyncio.gather(
        *(asyncio.to_thread(data_service.get_history, code, days) for code in pool),
        return_exceptions=True,
    )
    hist_map: dict[str, StockHistory] = {}
    for code, hist in zip(pool, hists):
        if isinstance(hist, BaseException) or not hist or not hist.closes:
            continue
        if len(hist.closes) >= horizon + 30:
            hist_map[code] = hist

    if not hist_map:
        return {"error": "未获取到足够的日线历史数据，请稍后重试"}

    items = await asyncio.to_thread(_evaluate_sync, hist_map, selected, horizon, eval_bars)
    return {
        "horizon_days": horizon,
        "eval_bars": eval_bars,
        "pool": list(hist_map),
        "pool_size": len(hist_map),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "items": items,
    }
