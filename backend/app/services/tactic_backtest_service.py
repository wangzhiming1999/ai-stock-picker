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
   - 天量见天价的「换手率 >30%」需要历史换手率，回测时按数据缺失处理；
   - 历史长度覆盖不了预热期的技巧，报 `insufficient_data` 并写明「未纳入评估」，
     而不是混在「0 次命中」里 —— 那会把「没信号」和「没评」显示成同一件事。

多周期共振取的是**真实周线/月线**（与日线同一端点，只是 period 参数不同），
回放时用 `_PeriodCursor` 按评估日切到「当时能看到的最后一根」，并把进行中那根的
收盘替换为当日收盘，避免用到该周期的最终收盘（look-ahead）。
"""
from __future__ import annotations

import asyncio
import bisect
import datetime as dt
import math
import statistics

from app.models import StockHistory
from app.services import calibers, concurrency, data_service, pattern_service

# 形态回测默认股票池（42 只）：覆盖大/中盘与主要行业，避免结论只来自少数几只票。
# 注意这是「今天的存活者」，天然有幸存者偏差，且大票波动小、形态信号偏弱，
# 因此回测结果只能当作下限参考。
# ⚠️ 与 backtest_service.STRATEGY_BACKTEST_POOL（18 只，策略回测用）不是同一个池，
#    两者历史上都叫 DEFAULT_POOL，改参数时极易混用 —— 重命名即为此。
TACTIC_BACKTEST_POOL = [
    # 消费 / 白酒 / 食品
    "600519", "000858", "600809", "603288", "000333", "600887", "002714",
    # 医药
    "600276", "300760", "603259", "000538",
    # 新能源 / 电子 / 科技
    "300750", "601012", "002594", "002475", "300059", "002415", "002230", "300124", "688981", "600703",
    # 金融
    "600036", "601318", "600030", "601166", "601398",
    # 周期 / 资源
    "601088", "600585", "601899", "600028", "601857", "000725",
    # 地产 / 建筑 / 汽车 / 家电 / 交运
    "000002", "601668", "600104", "000651", "601888", "000876", "600941", "002027", "600900", "601111",
]

DEFAULT_HORIZON = 10          # 前向持有期（交易日）
DEFAULT_EVAL_BARS = 250       # 每只票参与评估的最近交易日数
_MIN_EVAL_BARS = 60
_MAX_EVAL_BARS = 400
_MAX_POOL = 60

# 预热区间下限（日线根数）。评估窗口之外的这段历史是给「相对量」用的：
# volume_peak 要拿区间内最大量、volume_floor 要拿 60 日高点、ma20_slope 要算 MA20 斜率，
# 历史太短会让这些相对量被算在过小的样本上，前后两次回测结论不可比。
# 取值 390 = 改造前 `n - eval_bars`（日线硬上限 640 - 默认 250）的实际结果，
# 保留它可让其余技巧的评估区间与改造前逐点一致。
_PREFIX_LOOKBACK = 390

# 额外周期（周线/月线）的采样口径，与 pattern_service._bucket_key 一致
_PERIOD_BUCKET = {"week": "W", "month": "M"}

_MIN_SAMPLES = 10             # 低于此值只给数字、不给结论
_RELIABLE_SAMPLES = 30        # 低于此值时正态近似的显著性判定不可靠
_Z_CRITICAL = 1.96            # 双侧 95%

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


class _PeriodCursor:
    """把一个周期的 K 线按「周/月桶」切成可回放的点位序列。

    为什么不能直接用日期做二分：周线/月线的一根 K 线标记的是**该周期最后一个交易日**
    （月线记 2026-08-31），拿 08-14 去二分会把正在走的 8 月整根排除掉，
    而实盘在 08-14 那天恰恰看得到「8 月至今」这一根。
    因此按 `pattern_service._bucket_key` 的桶名对齐（月线取 YYYY-MM，周线取 ISO 年-周）。

    另外必须把切片里**最后一根（尚未走完的周期）的收盘换成当日收盘**：
    接口返回的这根带的是该周期最终收盘，回测走到月中时直接沿用就等于偷看未来
    （look-ahead）。替换后才等价于实盘当时真正看得到的序列。
    """

    def __init__(self, hist: StockHistory, period: str) -> None:
        self._bucket = _PERIOD_BUCKET[period]
        self._hist = hist
        self._buckets = [pattern_service._bucket_key(d, self._bucket) for d in (hist.dates or [])]
        self._cache: dict[int, StockHistory] = {}

    def as_of(self, day: str, live_close: float) -> StockHistory | None:
        """取「截至 day」的周期切片；day 所在的那根（进行中）也包含在内。"""
        if not self._buckets or not day:
            return None
        idx = bisect.bisect_right(self._buckets, pattern_service._bucket_key(day, self._bucket))
        return self._slice(idx, live_close)

    def _slice(self, idx: int, live_close: float) -> StockHistory | None:
        if idx <= 0:
            return None
        cached = self._cache.get(idx)
        if cached is None:
            h = self._hist
            closes = list(h.closes[:idx])
            cached = StockHistory(
                dates=list(h.dates[:idx]),
                closes=closes,
                volumes=list(h.volumes[:idx]) if h.volumes else None,
                opens=list(h.opens[:idx]) if h.opens else None,
                highs=list(h.highs[:idx]) if h.highs else None,
                lows=list(h.lows[:idx]) if h.lows else None,
            )
            self._cache[idx] = cached
        # 最后一根的收盘随评估日推进而变化，因此在缓存之外单独产出副本
        if live_close and cached.closes:
            closes = list(cached.closes)
            closes[-1] = live_close
            cached = StockHistory(
                dates=cached.dates,
                closes=closes,
                volumes=cached.volumes,
                opens=cached.opens,
                highs=cached.highs,
                lows=cached.lows,
            )
        return cached


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
        "z_score": None,
        "significant": None,
        "confidence": status,
        "verdict": note or "无结论",
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
        reason = note or "评估区间内未出现命中，样本不足以下结论"
        base["note"] = reason
        base["verdict"] = reason
        return base

    returns = [s[0] for s in signals]

    def _is_win(value: float) -> bool:
        return value > 0 if buy else value < 0

    n = len(returns)
    m = len(baseline)
    win_rate = sum(1 for r in returns if _is_win(r)) / n * 100
    baseline_win = sum(1 for r in baseline if _is_win(r)) / m * 100
    avg_return = statistics.fmean(returns)
    baseline_avg = statistics.fmean(baseline)
    # 卖出形态：价格跌得比基准更多才算「超额」，因此基准均值取反
    edge_return = (avg_return - baseline_avg) if buy else (baseline_avg - avg_return)

    # 两个比例之差的近似 z 检验：判断「形态胜率高出基准」能否与噪音区分开。
    # 关键在样本量 —— 没有这层判定，「3 次命中的 100% 胜率」会被当成可靠信号。
    p1, p2 = win_rate / 100, baseline_win / 100
    se = math.sqrt(p1 * (1 - p1) / n + p2 * (1 - p2) / m)
    z = (p1 - p2) / se if se > 0 else 0.0
    significant = n >= _RELIABLE_SAMPLES and abs(z) >= _Z_CRITICAL

    if n < _MIN_SAMPLES:
        confidence = "insufficient"
        verdict = f"仅 {n} 次命中，样本不足以下结论"
    elif n < _RELIABLE_SAMPLES:
        confidence = "preliminary"
        verdict = f"仅 {n} 次命中，初步胜率 {win_rate:.1f}%（基准 {baseline_win:.1f}%），样本不足以判定显著性"
    elif significant:
        confidence = "significant"
        verdict = f"{n} 次命中，胜率 {win_rate:.1f}% 显著高于基准 {baseline_win:.1f}%（z={z:.2f}）"
    else:
        confidence = "not_significant"
        verdict = f"{n} 次命中，胜率 {win_rate:.1f}% 与基准 {baseline_win:.1f}% 无显著差异（z={z:.2f}）"

    base.update(
        status="ok" if n >= _MIN_SAMPLES else "insufficient_data",
        win_rate=round(win_rate, 1),
        avg_return=round(avg_return, 2),
        median_return=round(statistics.median(returns), 2),
        avg_max_gain=round(statistics.fmean([s[1] for s in signals]), 2),
        avg_max_drawdown=round(statistics.fmean([s[2] for s in signals]), 2),
        baseline_win_rate=round(baseline_win, 1),
        baseline_avg_return=round(baseline_avg, 2),
        edge_win_rate=round(win_rate - baseline_win, 1),
        edge_return=round(edge_return, 2),
        z_score=round(z, 2),
        significant=significant,
        confidence=confidence,
        verdict=verdict,
        by_stock=[
            {"code": code, "signals": len(vals), "avg_return": round(statistics.fmean(vals), 2)}
            for code, vals in sorted(per_stock.items(), key=lambda kv: -len(kv[1]))[:8]
        ],
    )
    return base


def _evaluate_sync(
    hist_map: dict[str, StockHistory],
    keys: list[str],
    horizon: int,
    eval_bars: int,
    extra_map: dict[str, dict[str, StockHistory]] | None = None,
) -> list[dict]:
    """对每只票、每条技巧做 walk-forward 评估。

    前缀切片按「K 线位置」缓存，在同一条票的各技巧间复用 ——
    否则每条技巧都要自己切一遍历史，回测会慢数倍。
    extra_map 是按周期预先取到的周线/月线（{code: {"week": hist}}），
    只有声明了 extra_periods 的技巧才会用到。
    """
    selected = list(keys)
    resolved: dict[str, dict] = {}
    plan: list[str] = []
    for key in selected:
        tactic = pattern_service.TACTIC_MAP[key]
        if key in _NOT_BACKTESTABLE:
            resolved[key] = _blank(tactic, horizon, "not_backtestable", _NOT_BACKTESTABLE[key])
        else:
            plan.append(key)

    extra_keys = {k for k in plan if pattern_service.TACTIC_MAP[k].get("extra_periods")}
    accum = {k: {"signals": [], "baseline": [], "per_stock": {}, "stocks": 0} for k in plan}

    for code, hist in hist_map.items():
        closes = hist.closes
        n = len(closes)
        end = n - horizon
        if end <= 0:
            continue
        prefix_cache: dict[int, StockHistory] = {}
        cursors: dict[str, _PeriodCursor] = {}
        if extra_keys and extra_map:
            for period, ph in (extra_map.get(code) or {}).items():
                if period in _PERIOD_BUCKET and ph is not None and ph.closes:
                    cursors[period] = _PeriodCursor(ph, period)
        for key in plan:
            warmup = int(pattern_service.TACTIC_MAP[key]["warmup"])
            start = max(warmup, n - eval_bars)
            if start >= end:
                continue
            acc = accum[key]
            acc["stocks"] += 1
            detector = pattern_service.DETECTORS[key]
            wants_extra = key in extra_keys and bool(cursors)
            last_hit = -10 ** 9
            stock_returns: list[float] = []
            for i in range(start, end):
                fwd = _forward(closes, i, horizon)
                if fwd is None:
                    continue
                acc["baseline"].append(fwd[0])
                if i - last_hit < horizon:
                    continue  # 去重：同一波行情只计一次
                prefix = prefix_cache.get(i)
                if prefix is None:
                    prefix = _prefix(hist, i + 1)
                    prefix_cache[i] = prefix
                ctx = {
                    "daily": prefix,
                    "intraday": None,
                    "price": closes[i],
                    "turnover": None,  # 无历史换手率
                }
                if wants_extra:
                    day = prefix.dates[-1] if prefix.dates else None
                    for period, cursor in cursors.items():
                        sliced = cursor.as_of(day, closes[i]) if day else None
                        if sliced is not None:
                            ctx[period] = sliced
                try:
                    hit = detector(ctx)
                except Exception:
                    continue
                if not hit["matched"]:
                    continue
                acc["signals"].append((fwd[0], fwd[1], fwd[2], code))
                stock_returns.append(fwd[0])
                last_hit = i
            if stock_returns:
                acc["per_stock"][code] = stock_returns

    for key in selected:
        if key in resolved:
            continue
        acc = accum[key]
        if not acc["stocks"]:
            # 历史长度不够覆盖该技巧的预热期时必须明说 ——
            # 静默跳过会让「没有信号」和「压根没评」看起来完全一样。
            resolved[key] = _blank(
                pattern_service.TACTIC_MAP[key],
                horizon,
                "insufficient_data",
                "可用历史长度不足以覆盖该技巧的预热期，本次回测未纳入评估",
            )
            continue
        resolved[key] = _pack(
            pattern_service.TACTIC_MAP[key],
            horizon,
            acc["signals"],
            acc["baseline"],
            acc["stocks"],
            acc["per_stock"],
        )
    return [resolved[k] for k in selected]


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
    pool = [c.strip() for c in (codes or TACTIC_BACKTEST_POOL) if c and c.strip()][:_MAX_POOL]
    if not pool:
        return {"error": "股票池为空"}

    backtestable = [k for k in selected if k not in _NOT_BACKTESTABLE]
    warmup = max((int(pattern_service.TACTIC_MAP[k]["warmup"]) for k in backtestable), default=0)
    days = max(warmup, _PREFIX_LOOKBACK) + eval_bars + horizon + 5

    async def _fetch(code: str):
        async with concurrency.limited():
            return await asyncio.to_thread(data_service.get_history, code, days)

    hists = await asyncio.gather(*(_fetch(code) for code in pool), return_exceptions=True)
    hist_map: dict[str, StockHistory] = {}
    failed: list[str] = []
    for code, hist in zip(pool, hists):
        if isinstance(hist, BaseException) or not hist or not hist.closes:
            failed.append(code)
            continue
        if len(hist.closes) >= horizon + 30:
            hist_map[code] = hist
        else:
            failed.append(code)

    if not hist_map:
        return {"error": "未获取到足够的日线历史数据，请稍后重试"}

    # 周线/月线：只有多周期共振需要。按周期取真实 K 线（不再是日线重采样），
    # 回放时由 _PeriodCursor 按日期切到「截至评估日」，不会看到未来。
    extra_map: dict[str, dict[str, StockHistory]] = {}
    for period in pattern_service.needed_periods(backtestable):
        for code, ph in (await pattern_service.load_period_histories(list(hist_map), period)).items():
            extra_map.setdefault(code, {})[period] = ph

    items = await asyncio.to_thread(_evaluate_sync, hist_map, selected, horizon, eval_bars, extra_map)
    return {
        "horizon_days": horizon,
        "eval_bars": eval_bars,
        "pool": list(hist_map),
        "pool_size": len(hist_map),
        "failed": failed,
        "min_samples": _MIN_SAMPLES,
        "reliable_samples": _RELIABLE_SAMPLES,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "items": items,
        # 口径随数据一起下发，避免前端把它和「次日胜率」并列展示却不说明差异
        "caliber": calibers.describe("tactic_backtest"),
    }
