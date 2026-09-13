"""实战形态规则引擎：把交易经验沉淀为可复核的确定性条件检查。

与既有服务的分工：
- `signal_service`（日线）：这只票处在什么位置（支撑 / 压力 / 买卖点）
- `intraday_service`（分钟）：就今天这一笔该不该动手
- `pattern_service`（形态）：这套「实战技巧」是否成立 —— 每条技巧是一组必须逐条
  核对的硬条件，返回 passed/total/conditions，前端按清单展示，不做黑箱打分。

三条设计原则：
1. 只回答「形态条件是否成立」，不预测涨跌、不承诺胜率（原文中的胜率表述不进入代码）；
2. 数据不足时明确标 `insufficient_data`，绝不用臆测填补缺失的 K 线；
3. 判定全部基于 K 线自身（OHLCV）与实时快照，可复现、可回测。
"""
from __future__ import annotations

import asyncio
import datetime as dt

from app.services import data_service

# 技巧注册表：
# - source 决定取数方式（daily=日线，intraday=分钟线）
# - history_days：取数时预留的日线根数（含缓冲区），供接口按需拉取
# - warmup：判定该技巧真正需要的预热根数，回测 walk-forward 从这一根开始评估
TACTICS: list[dict] = [
    {
        "key": "cycle_resonance",
        "name": "多周期共振买入",
        "category": "周期共振",
        "direction": "buy",
        "source": "daily",
        "history_days": 900,
        "warmup": 750,
        "desc": "日线、周线、月线 MACD 同时金叉，大级别共振买点。",
    },
    {
        "key": "intraday_divergence",
        "name": "分时背离逃顶",
        "category": "周期共振",
        "direction": "sell",
        "source": "intraday",
        "history_days": 0,
        "warmup": 0,
        "desc": "分时价格创新高但 MACD 未同步创新高，顶背离分批止盈。",
    },
    {
        "key": "wash_scrub",
        "name": "揉搓线洗盘",
        "category": "K线组合",
        "direction": "buy",
        "source": "daily",
        "history_days": 120,
        "warmup": 25,
        "desc": "长上影＋长下影、两根实体接近，突破上影高点即为加仓点。",
    },
    {
        "key": "guillotine",
        "name": "断头铡刀",
        "category": "K线组合",
        "direction": "sell",
        "source": "daily",
        "history_days": 120,
        "warmup": 21,
        "desc": "均线粘合后一根大阴线跌破 MA5/10/20 且跌幅超 5%，趋势走坏。",
    },
    {
        "key": "volume_floor",
        "name": "地量见地价",
        "category": "量价关系",
        "direction": "buy",
        "source": "daily",
        "history_days": 160,
        "warmup": 70,
        "desc": "长期下跌后缩量至前期均量 20% 以下，再温和放量 2 倍为左侧买点。",
    },
    {
        "key": "volume_peak",
        "name": "天量见天价",
        "category": "量价关系",
        "direction": "sell",
        "source": "daily",
        "history_days": 320,
        "warmup": 70,
        "desc": "短期涨幅超 50% 后放出历史天量、换手超 30%，高位减仓信号。",
    },
]
TACTIC_MAP: dict[str, dict] = {t["key"]: t for t in TACTICS}

# 单市场（日线）技巧的兜底阈值，集中在此便于日后回测调参。
_BODY_SHADOW_RATIO = 2.0        # 影线长度至少为实体倍数
_SHADOW_RANGE_RATIO = 0.4       # 影线至少占全幅比例
_BODY_SIMILAR_TOL = 0.35        # 揉搓线两根实体差异容忍度
_MA_CONVERGE_TOL = 0.03         # 断头铡刀：MA5/10/20 粘合极差
_GUILLOTINE_DROP = -5.0         # 断头铡刀：单日跌幅阈值 %
_FLOOR_VOLUME_RATIO = 0.20      # 地量：相对前期均量比例
_FLOOR_CONFIRM_RATIO = 2.0      # 地量后放量倍数
_FLOOR_LOOKBACK = 10            # 地量搜索窗口（交易日）
_PEAK_GAIN = 50.0               # 天量见天价：短期涨幅阈值 %
_PEAK_TURNOVER = 30.0           # 天量见天价：换手率阈值 %
_PEAK_VOLUME_RATIO = 0.98       # 天量：相对历史最大量的比例


# ---------------- 通用工具 ----------------

def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _pct(a: float, b: float) -> float:
    return (a / b - 1) * 100 if b else 0.0


def _ema(values: list[float], span: int) -> list[float]:
    """指数移动平均（首值作为种子）。"""
    if not values:
        return []
    k = 2.0 / (span + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(out[-1] + (v - out[-1]) * k)
    return out


def macd_series(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> dict | None:
    """标准 MACD：DIF=EMA(fast)-EMA(slow)，DEA=EMA(DIF, signal)，柱=(DIF-DEA)*2。

    注意：与 `market._compute_indicators` 的简化版（DEA 取 DIF 末 9 根均值）不同，
    这里用标准 EMA(9)，因为形态判定依赖 DIF/DEA 的交叉时点，必须口径正确。
    """
    if len(closes) < slow + signal:
        return None
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    dif = [f - s for f, s in zip(ema_fast, ema_slow)]
    dea = _ema(dif, signal)
    hist = [(d - e) * 2 for d, e in zip(dif, dea)]
    return {"dif": dif, "dea": dea, "hist": hist}


def _cross_recently(dif: list[float], dea: list[float], lookback: int = 3) -> bool:
    """最近 lookback 根内是否发生金叉，且当前仍维持在金叉状态。"""
    n = len(dif)
    if n < 2:
        return False
    crossed = False
    for i in range(max(1, n - lookback), n):
        if dif[i - 1] <= dea[i - 1] and dif[i] > dea[i]:
            crossed = True
    return crossed and dif[-1] > dea[-1]


def _bucket_key(date_str, period: str) -> str:
    d = str(date_str)
    if period == "M":
        return d[:7]
    try:
        iso = dt.date.fromisoformat(d[:10]).isocalendar()
        return f"{iso[0]}-{iso[1]:02d}"
    except ValueError:
        return d[:10]


def _resample_closes(dates: list[str], closes: list[float], period: str) -> list[float]:
    """日线收盘序列按周（W）/月（M）聚合，取每个周期的最后一根收盘。"""
    if not dates or len(dates) != len(closes):
        return []
    out: list[float] = []
    last_key = None
    for d, c in zip(dates, closes):
        key = _bucket_key(d, period)
        if key != last_key:
            out.append(c)
            last_key = key
        else:
            out[-1] = c
    return out


def _pack(tactic: dict, conditions: list[dict], *, matched: bool, action: str,
          metrics: dict | None = None, status: str | None = None) -> dict:
    """把条件清单收敛为标准结果结构（与 StrategyAssessment 同形）。"""
    total = len(conditions)
    passed = sum(1 for c in conditions if c.get("passed"))
    unavailable = sum(1 for c in conditions if c.get("available", True) is False)
    if status is None:
        if matched:
            status = "matched"
        elif total and passed == 0 and unavailable:
            status = "insufficient_data"
        elif total and passed >= total - 1:
            status = "watch"
        else:
            status = "failed"
    return {
        "key": tactic["key"],
        "name": tactic["name"],
        "category": tactic["category"],
        "direction": tactic["direction"],
        "desc": tactic["desc"],
        "matched": matched,
        "status": status,
        "score": round(10.0 * passed / total, 1) if total else 0.0,
        "passed": passed,
        "total": total,
        "action": action,
        "conditions": conditions,
        "metrics": metrics or {},
    }


def _insufficient(tactic: dict, reason: str) -> dict:
    return _pack(tactic, [], matched=False, action=reason, status="insufficient_data")


def _cond(name: str, passed: bool, detail: str, available: bool = True) -> dict:
    return {"name": name, "passed": passed, "detail": detail, "available": available}


# ---------------- 技巧 1：多周期共振买入 ----------------

def detect_cycle_resonance(ctx: dict) -> dict:
    tactic = TACTIC_MAP["cycle_resonance"]
    daily = ctx.get("daily")
    closes = (daily.closes if daily else None) or []
    if len(closes) < 250:
        return _insufficient(tactic, "日线历史不足 250 根，无法判定周/月线共振")

    conditions = []
    metrics: dict = {}
    for label, period, need in (("日线", None, 60), ("周线", "W", 35), ("月线", "M", 35)):
        series = closes if period is None else _resample_closes(daily.dates, closes, period)
        if len(series) < need:
            conditions.append(
                _cond(f"{label} MACD 金叉", False, f"{label} K线仅 {len(series)} 根，不足 {need} 根", available=False)
            )
            continue
        macd = macd_series(series)
        if macd is None:
            conditions.append(_cond(f"{label} MACD 金叉", False, f"{label} 数据不足，无法计算 MACD", available=False))
            continue
        # 更高级别允许稍宽的交叉窗口，避免月线金叉当根错过
        lookback = 3 if period is None else 4
        crossed = _cross_recently(macd["dif"], macd["dea"], lookback)
        conditions.append(
            _cond(
                f"{label} MACD 金叉",
                crossed,
                (
                    f"近 {lookback} 根内金叉且仍在上方（DIF {macd['dif'][-1]:.3f} / DEA {macd['dea'][-1]:.3f}）"
                    if crossed
                    else f"未金叉（DIF {macd['dif'][-1]:.3f} / DEA {macd['dea'][-1]:.3f}）"
                ),
            )
        )
        metrics[f"{period or 'D'}_dif"] = round(macd["dif"][-1], 3)

    matched = all(c["passed"] for c in conditions)
    passed = sum(1 for c in conditions if c["passed"])
    if matched:
        action = "三周期 MACD 共振金叉，大级别买点，可按计划分批建仓"
    elif passed:
        action = f"已 {passed}/3 周期金叉，尚未共振，等待剩余周期确认"
    else:
        action = "三周期均未金叉，共振不成立"
    return _pack(tactic, conditions, matched=matched, action=action, metrics=metrics)


# ---------------- 技巧 2：分时背离逃顶 ----------------

def detect_intraday_divergence(ctx: dict) -> dict:
    tactic = TACTIC_MAP["intraday_divergence"]
    hist = ctx.get("intraday")
    closes = (hist.closes if hist else None) or []
    dates = (hist.dates if hist else None) or []
    if len(closes) < 40:
        return _insufficient(tactic, "分时 K 线不足 40 根，无法判定顶背离")

    session = str(dates[-1])[:8]
    idx = [i for i, d in enumerate(dates) if str(d)[:8] == session]
    if len(idx) < 20:
        return _insufficient(tactic, f"当日分时仅 {len(idx)} 根，不足 20 根")

    macd = macd_series(closes)
    if macd is None:
        return _insufficient(tactic, "分时长度不足，无法计算 MACD")
    dif, dea = macd["dif"], macd["dea"]

    day_idx = idx[-30:]
    day_closes = [closes[i] for i in day_idx]
    day_dif = [dif[i] for i in day_idx]
    price = ctx.get("price") or day_closes[-1]

    hi_pos = max(range(len(day_closes)), key=lambda k: day_closes[k])
    price_high = day_closes[hi_pos]
    new_high = hi_pos >= len(day_closes) - 4 and price >= price_high * 0.998

    if hi_pos > 0:
        prior_pos = max(range(hi_pos), key=lambda k: day_closes[k])
        price_higher_high = day_closes[prior_pos] < price_high
        dif_lower_high = day_dif[hi_pos] < day_dif[prior_pos]
    else:
        prior_pos, price_higher_high, dif_lower_high = None, False, False

    divergence = price_higher_high and dif_lower_high
    weaken = dif[-1] < dea[-1]

    prior_text = (
        f"前高 {day_closes[prior_pos]:.2f} 对应 DIF {day_dif[prior_pos]:.3f}，"
        f"新高 {price_high:.2f} 对应 DIF {day_dif[hi_pos]:.3f}"
        if prior_pos is not None
        else "当日尚未形成第二个价格高点"
    )
    conditions = [
        _cond("分时价格创阶段新高", new_high, f"当日高点 {price_high:.2f}，现价 {price:.2f}"),
        _cond("MACD 未同步创新高（顶背离）", divergence, prior_text),
        _cond("指标已转弱（DIF 下穿 DEA）", weaken, f"DIF {dif[-1]:.3f} / DEA {dea[-1]:.3f}"),
    ]

    matched = new_high and divergence
    if matched:
        action = "分时顶背离成立，分批止盈，可先减一半仓位"
    elif new_high:
        action = "创阶段新高但未背离，持有观察，跌破分时均线再减"
    else:
        action = "未出现分时顶背离"

    metrics = {
        "price_high": round(price_high, 2),
        "dif_at_high": round(day_dif[hi_pos], 3),
        "dif_prior_high": round(day_dif[prior_pos], 3) if prior_pos is not None else None,
    }
    return _pack(tactic, conditions, matched=matched, action=action, metrics=metrics)


# ---------------- 技巧 3：揉搓线洗盘 ----------------

def _long_upper_shadow(o, h, l, c, i: int) -> bool:
    """长上影 + 冲高回落。"""
    rng = h[i] - l[i]
    if rng <= 0:
        return False
    body = abs(c[i] - o[i])
    upper = h[i] - max(o[i], c[i])
    if upper < max(_BODY_SHADOW_RATIO * body, _SHADOW_RANGE_RATIO * rng):
        return False
    return c[i] < h[i] - 0.5 * upper


def _long_lower_shadow(o, h, l, c, i: int) -> bool:
    """长下影 + 探底回升。"""
    rng = h[i] - l[i]
    if rng <= 0:
        return False
    body = abs(c[i] - o[i])
    lower = min(o[i], c[i]) - l[i]
    if lower < max(_BODY_SHADOW_RATIO * body, _SHADOW_RANGE_RATIO * rng):
        return False
    return c[i] > l[i] + 0.5 * lower


def _bodies_similar(o, c, i: int, j: int) -> bool:
    bi, bj = abs(c[i] - o[i]), abs(c[j] - o[j])
    ref = max(bi, bj)
    if ref <= 0:
        return True
    return abs(bi - bj) <= _BODY_SIMILAR_TOL * ref


def detect_wash_scrub(ctx: dict) -> dict:
    tactic = TACTIC_MAP["wash_scrub"]
    daily = ctx.get("daily")
    if not daily or not (daily.opens and daily.highs and daily.lows and daily.closes):
        return _insufficient(tactic, "缺少日线 OHLC，无法识别 K 线组合")
    o, h, l, c = daily.opens, daily.highs, daily.lows, daily.closes
    n = len(c)
    if n < 25 or not (len(o) == len(h) == len(l) == n):
        return _insufficient(tactic, "日线不足 25 根或 OHLC 长度不一致")

    price = ctx.get("price") or c[-1]
    ma5, ma20 = _mean(c[-5:]), _mean(c[-20:])
    uptrend = price > ma20 and ma5 >= ma20

    pair = None
    for i in range(n - 1, max(n - 16, 1), -1):
        if _long_upper_shadow(o, h, l, c, i - 1) and _long_lower_shadow(o, h, l, c, i):
            pair = (i - 1, i)
            break

    if pair is None:
        conditions = [
            _cond("上升中途（站上 MA20）", uptrend, f"现价 {price:.2f}，MA20 {ma20:.2f}，MA5 {ma5:.2f}"),
            _cond("第 1 根长上影冲高回落", False, "近 15 根内未找到长上影 K 线"),
            _cond("第 2 根长下影探底回升", False, "近 15 根内未找到长下影 K 线"),
            _cond("两根实体接近", False, "未形成揉搓线组合"),
            _cond("3 日内突破上影高点", False, "组合未成立"),
        ]
        return _pack(tactic, conditions, matched=False, action="未出现揉搓线形态")

    d1, d2 = pair
    similar = _bodies_similar(o, c, d1, d2)
    breakout_idx = None
    for j in range(d2 + 1, min(n, d2 + 4)):
        if h[j] > h[d1]:
            breakout_idx = j
            break
    breakout = breakout_idx is not None
    pending = d2 == n - 1 or (d2 >= n - 3 and not breakout)

    conditions = [
        _cond("上升中途（站上 MA20）", uptrend, f"现价 {price:.2f}，MA20 {ma20:.2f}，MA5 {ma5:.2f}"),
        _cond("第 1 根长上影冲高回落", True, f"第 {n - 1 - d1} 根前：高 {h[d1]:.2f} / 收 {c[d1]:.2f}"),
        _cond("第 2 根长下影探底回升", True, f"第 {n - 1 - d2} 根前：低 {l[d2]:.2f} / 收 {c[d2]:.2f}"),
        _cond("两根实体接近", similar, f"实体 {abs(c[d1] - o[d1]):.2f} vs {abs(c[d2] - o[d2]):.2f}"),
        _cond("3 日内突破上影高点", breakout, f"上影高点 {h[d1]:.2f}" + ("，已突破" if breakout else "，尚未突破")),
    ]

    matched = uptrend and similar and breakout
    if matched:
        action = f"揉搓线成立且已突破 {h[d1]:.2f}，回踩不破可加仓"
    elif uptrend and similar and pending:
        action = f"揉搓线形态成立，突破 {h[d1]:.2f} 即为加仓点"
    else:
        action = "揉搓线条件不完整，暂不参与"

    metrics = {"scrub_high": round(h[d1], 2), "breakout_days": (breakout_idx - d2) if breakout else None}
    return _pack(tactic, conditions, matched=matched, action=action, metrics=metrics)


# ---------------- 技巧 4：断头铡刀止损 ----------------

def _ma_at(values: list[float], idx: int, window: int) -> float | None:
    if idx + 1 < window:
        return None
    return _mean(values[idx - window + 1: idx + 1])


def detect_guillotine(ctx: dict) -> dict:
    tactic = TACTIC_MAP["guillotine"]
    daily = ctx.get("daily")
    c = (daily.closes if daily else None) or []
    if len(c) < 21:
        return _insufficient(tactic, "日线不足 21 根，无法计算 MA20")
    o = daily.opens or []
    n = len(c)
    last, prev = n - 1, n - 2

    pma5 = _ma_at(c, prev, 5)
    pma10 = _ma_at(c, prev, 10)
    pma20 = _ma_at(c, prev, 20)
    if pma5 is None or pma10 is None or pma20 is None:
        return _insufficient(tactic, "日线不足 21 根，无法计算 MA20")

    mas = [pma5, pma10, pma20]
    converge = (max(mas) - min(mas)) / min(mas) <= _MA_CONVERGE_TOL if min(mas) > 0 else False
    near_above = c[prev] >= min(mas) * 0.995
    drop = _pct(c[last], c[prev])
    break_all = c[last] < pma5 and c[last] < pma10 and c[last] < pma20
    has_open = len(o) == n and o[last] > 0
    bearish = (c[last] < o[last]) if has_open else True

    conditions = [
        _cond(
            "前一日 MA5/10/20 粘合",
            converge,
            f"MA5 {pma5:.2f} / MA10 {pma10:.2f} / MA20 {pma20:.2f}，极差 {(max(mas) - min(mas)) / min(mas) * 100:.2f}%",
        ),
        _cond(
            "大阴线跌破三根均线",
            break_all and bearish and near_above,
            f"收盘 {c[last]:.2f}，三线 {pma5:.2f}/{pma10:.2f}/{pma20:.2f}"
            + ("" if has_open else "（无开盘价，仅按收盘判定）"),
            available=has_open,
        ),
        _cond("单日跌幅超过 5%", drop <= _GUILLOTINE_DROP, f"当日 {drop:+.2f}%"),
    ]

    matched = converge and break_all and bearish and near_above and drop <= _GUILLOTINE_DROP
    action = (
        "断头铡刀成立，收盘前无条件减仓 70% 以上"
        if matched
        else ("跌破三线但条件未全部满足，收紧止损并减仓观察" if break_all else "未出现断头铡刀")
    )
    metrics = {"ma5": round(pma5, 2), "ma10": round(pma10, 2), "ma20": round(pma20, 2), "change_pct": round(drop, 2)}
    return _pack(tactic, conditions, matched=matched, action=action, metrics=metrics)


# ---------------- 技巧 5：地量见地价 ----------------

def detect_volume_floor(ctx: dict) -> dict:
    tactic = TACTIC_MAP["volume_floor"]
    daily = ctx.get("daily")
    if not daily or not daily.volumes or not daily.closes:
        return _insufficient(tactic, "缺少日线量价数据")
    v, c = daily.volumes, daily.closes
    n = len(c)
    if n < 70 or len(v) != n:
        return _insufficient(tactic, "日线不足 70 根，无法判定地量")

    window = c[-60:]
    hi = max(window)
    hi_pos = window.index(hi)
    drawdown = _pct(c[-1], hi)
    long_down = hi_pos <= 20 and drawdown <= -15.0

    base = [x for x in v[n - 70:n - _FLOOR_LOOKBACK] if x and x > 0]
    base_avg = _mean(base)
    low_idx, low_ratio = None, None
    for i in range(n - _FLOOR_LOOKBACK, n):
        if v[i] and base_avg > 0:
            r = v[i] / base_avg
            if low_ratio is None or r < low_ratio:
                low_idx, low_ratio = i, r
    floor_vol = low_idx is not None and low_ratio is not None and low_ratio <= _FLOOR_VOLUME_RATIO

    confirm_idx = None
    if low_idx is not None:
        for j in range(low_idx + 1, min(n, low_idx + 4)):
            if v[j] and v[j] >= _FLOOR_CONFIRM_RATIO * v[low_idx] and c[j] >= c[low_idx]:
                confirm_idx = j
                break
    confirmed = confirm_idx is not None

    conditions = [
        _cond(
            "长期下跌（60 日高点在前段且回撤 ≥15%）",
            long_down,
            f"60 日高点 {hi:.2f}（第 {hi_pos + 1} 根），现价 {c[-1]:.2f}，回撤 {drawdown:.1f}%",
        ),
        _cond(
            "出现地量（≤ 前期均量 20%）",
            floor_vol,
            (
                f"最近地量 {v[low_idx]:.0f} 手，为前期均量 {base_avg:.0f} 手的 {low_ratio * 100:.1f}%"
                if floor_vol and low_idx is not None
                else f"近 {_FLOOR_LOOKBACK} 日最低量能 {low_ratio * 100:.1f}% 前期均量，未达地量"
                if low_ratio is not None
                else "无有效量能数据"
            ),
        ),
        _cond(
            "3 日内温和放量 ≥ 地量 2 倍",
            confirmed,
            (
                f"地量后第 {confirm_idx - low_idx} 日放量至 {v[confirm_idx]:.0f} 手"
                if confirmed
                else "尚未出现 2 倍量确认"
            ),
        ),
    ]

    matched = long_down and floor_vol and confirmed
    if matched:
        action = "地量后放量确认，左侧抄底买点成立，可分批建仓"
    elif long_down and floor_vol:
        action = "地量已现，等待 3 日内放量 2 倍确认再动手"
    else:
        action = "未出现地量见地价结构"
    metrics = {"drawdown_pct": round(drawdown, 1), "floor_ratio": round(low_ratio, 3) if low_ratio is not None else None}
    return _pack(tactic, conditions, matched=matched, action=action, metrics=metrics)


# ---------------- 技巧 6：天量见天价 ----------------

def detect_volume_peak(ctx: dict) -> dict:
    tactic = TACTIC_MAP["volume_peak"]
    daily = ctx.get("daily")
    if not daily or not daily.volumes or not daily.closes:
        return _insufficient(tactic, "缺少日线量价数据")
    v, c = daily.volumes, daily.closes
    n = len(c)
    if n < 70 or len(v) != n:
        return _insufficient(tactic, "日线不足 70 根，无法判定天量")

    hist_max = max(v[-250:]) if v else 0.0
    peak_idx, peak_ratio = None, None
    for i in range(max(0, n - 3), n):
        r = v[i] / hist_max if hist_max else 0.0
        if peak_ratio is None or r > peak_ratio:
            peak_idx, peak_ratio = i, r
    is_peak_volume = peak_ratio is not None and peak_ratio >= _PEAK_VOLUME_RATIO

    lo60 = min(c[-60:])
    gain = _pct(c[-1], lo60)
    surge = gain >= _PEAK_GAIN

    turnover = ctx.get("turnover")
    if turnover is None:
        turnover_cond = _cond("换手率超过 30%", False, "无实时换手率数据，仅按量价判定", available=False)
    else:
        turnover_cond = _cond("换手率超过 30%", turnover > _PEAK_TURNOVER, f"当前换手率 {turnover:.2f}%")

    highs = daily.highs or c
    if peak_idx is not None and peak_idx < n - 1:
        after = highs[peak_idx + 1: min(n, peak_idx + 3)]
        peak_high = highs[peak_idx]
        no_new_high = bool(after) and max(after) <= peak_high
        high_cond = _cond(
            "天量后 2 日未创新高（清仓确认）",
            no_new_high,
            f"天量日高点 {peak_high:.2f}，其后最高 {max(after):.2f}" if after else "天量后尚无完整 2 日数据",
            available=bool(after),
        )
    else:
        high_cond = _cond("天量后 2 日未创新高（清仓确认）", False, "天量出现在最近一根，等待后续验证", available=False)

    conditions = [
        _cond("短期涨幅 ≥50%", surge, f"60 日低点 {lo60:.2f} → 现价 {c[-1]:.2f}，涨幅 {gain:.1f}%"),
        _cond(
            "放出历史天量",
            is_peak_volume,
            f"最新量 {v[-1]:.0f} 手为历史最大量 {hist_max:.0f} 手的 {peak_ratio * 100:.1f}%"
            if peak_ratio is not None
            else "无量能数据",
        ),
        turnover_cond,
        high_cond,
    ]

    matched = surge and is_peak_volume and (turnover_cond["passed"] or not turnover_cond["available"])
    if matched and high_cond["passed"]:
        action = "天量后 2 日未创新高，按纪律清仓离场"
    elif matched:
        action = "天量见天价，收盘前至少减半仓，2 日不创新高则清仓"
    else:
        action = "未出现天量见天价结构"
    metrics = {"gain_pct": round(gain, 1), "volume_ratio": round(peak_ratio, 3) if peak_ratio is not None else None}
    return _pack(tactic, conditions, matched=matched, action=action, metrics=metrics)


DETECTORS = {
    "cycle_resonance": detect_cycle_resonance,
    "intraday_divergence": detect_intraday_divergence,
    "wash_scrub": detect_wash_scrub,
    "guillotine": detect_guillotine,
    "volume_floor": detect_volume_floor,
    "volume_peak": detect_volume_peak,
}


# ---------------- 对外入口 ----------------

def list_tactics() -> list[dict]:
    """技巧元数据清单（前端据此渲染按钮与分组）。"""
    return [
        {
            "key": t["key"],
            "name": t["name"],
            "category": t["category"],
            "direction": t["direction"],
            "desc": t["desc"],
            "source": t["source"],
            "history_days": t["history_days"],
            "warmup": t["warmup"],
        }
        for t in TACTICS
    ]


def check_one(ctx: dict, keys: list[str] | None = None) -> list[dict]:
    """对单个上下文跑指定技巧（默认全部）。单个技巧异常不拖垮其余技巧。"""
    selected = keys or [t["key"] for t in TACTICS]
    out: list[dict] = []
    for key in selected:
        fn = DETECTORS.get(key)
        if fn is None:
            continue
        try:
            out.append(fn(ctx))
        except Exception as e:  # 形态计算失败不应让整批扫描 502
            out.append(_insufficient(TACTIC_MAP[key], f"计算异常：{type(e).__name__}"))
    return out


def matched_tactics(ctx: dict, keys: list[str] | None = None) -> list[dict]:
    """只返回命中的技巧（全部条件成立）。

    深度分析卡 / 盯盘等紧凑展示场景只关心「命中了什么」，
    未命中与数据不足的结果不必回传，避免前端被噪音刷屏。
    """
    return [r for r in check_one(ctx, keys) if r["matched"]]


async def check_codes(codes: list[str], keys: list[str] | None = None, intraday_period: str = "5m") -> list[dict]:
    """批量检查：按技巧所需数据一次性取行情/日线/分钟线，再逐股跑判定。

    日线只按「选中技巧里最长的 history_days」拉一次，避免同一只票重复请求。
    """
    codes = [c.strip() for c in codes if c and c.strip()]
    selected = [k for k in (keys or list(DETECTORS)) if k in DETECTORS]
    if not codes or not selected:
        return []

    need_daily = any(TACTIC_MAP[k]["source"] == "daily" for k in selected)
    need_intraday = any(TACTIC_MAP[k]["source"] == "intraday" for k in selected)
    days = max((TACTIC_MAP[k]["history_days"] for k in selected if TACTIC_MAP[k]["source"] == "daily"), default=0)

    quotes = await asyncio.to_thread(data_service.get_spot_quote, codes)
    quote_map = {q.code: q for q in quotes}

    daily_map: dict[str, object] = {}
    if need_daily and days > 0:
        hist = await asyncio.gather(*(asyncio.to_thread(data_service.get_history, c, days) for c in codes))
        daily_map = dict(zip(codes, hist))

    intraday_map: dict[str, object] = {}
    if need_intraday:
        mins = await asyncio.gather(
            *(asyncio.to_thread(data_service.get_intraday_history, c, intraday_period) for c in codes)
        )
        intraday_map = dict(zip(codes, mins))

    out: list[dict] = []
    for code in codes:
        q = quote_map.get(code)
        daily = daily_map.get(code)
        price = (q.price if q else None) or (daily.closes[-1] if daily and getattr(daily, "closes", None) else None)
        ctx = {
            "daily": daily,
            "intraday": intraday_map.get(code),
            "price": price,
            "turnover": q.turnover if q else None,
        }
        out.append(
            {
                "code": code,
                "name": (q.name if q else "") or "",
                "price": round(price, 2) if price else None,
                "change_pct": round(q.change_pct, 2) if q else None,
                "turnover": round(q.turnover, 2) if q and q.turnover is not None else None,
                "tactics": check_one(ctx, selected),
            }
        )
    return out
