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

from app.services import concurrency, data_service, tactic_evidence

# 技巧注册表：
# - source 决定取数方式（daily=日线，intraday=分钟线）
# - history_days：取数时预留的**日线**根数（含缓冲区），供接口按需拉取
# - warmup：判定该技巧真正需要的**日线**预热根数，回测 walk-forward 从这一根开始评估
# - extra_periods：除日线外还需要哪些周期（目前只有多周期共振）。
#   键名同时是 ctx 里的键名，也是 data_service.get_history 的 period 参数。
TACTICS: list[dict] = [
    {
        "key": "cycle_resonance",
        "name": "多周期共振买入",
        "category": "周期共振",
        "direction": "buy",
        "source": "daily",
        # 日线只需够算 MACD(12,26,9)；周线/月线走 extra_periods 单独取，不再从日线重采样
        "history_days": 120,
        "warmup": 60,
        "extra_periods": ("week", "month"),
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
    {
        "key": "macd_zone_cross",
        "name": "MACD 零轴金叉",
        "category": "均线与指标",
        "direction": "buy",
        "source": "daily",
        "history_days": 160,
        "warmup": 60,
        "desc": "零轴上方金叉为强势买点；零轴下方金叉需放量 30% 才轻仓试错。",
    },
    {
        "key": "ma10_break",
        "name": "MA10 三日失守",
        "category": "风控铁律",
        "direction": "sell",
        "source": "daily",
        "history_days": 120,
        "warmup": 25,
        "desc": "跌破 10 日均线后连续 3 日无力收回，趋势走弱离场信号。",
    },
    {
        "key": "chip_single_peak",
        "name": "单峰密集",
        "category": "筹码形态",
        "direction": "buy",
        "source": "daily",
        "history_days": 220,
        "warmup": 130,
        "desc": "90% 筹码集中度高（成本区间收窄）且股价贴近成本峰，筹码换手充分后的蓄势形态。",
    },
    {
        "key": "chip_low_profit",
        "name": "低位低获利盘",
        "category": "筹码形态",
        "direction": "buy",
        "source": "daily",
        "history_days": 220,
        "warmup": 130,
        "desc": "获利比例极低（深跌后套牢盘为主）且股价处 60 日低位区，抛压趋于枯竭。",
    },
    {
        "key": "chip_transfer_up",
        "name": "筹码转移向上",
        "category": "筹码形态",
        "direction": "buy",
        "source": "daily",
        "history_days": 220,
        "warmup": 130,
        "desc": "获利比例 10 日内持续抬升、成本重心上移，筹码由套牢盘向获利盘温和转移。",
    },
]

# 已下线技巧（2026-09-17）：不在 TACTICS 里 = 扫描/回测/面板都不再出现。
# ma20_slope 两轮回测（2026-09-13 / 09-16）收益与胜率超额均为负（−0.26/−0.35pt、−5.4/−5.0pt），
# 「黄金区间」口径跑不赢基准 —— 按证据闸门口径属 unsupported，直接下线而不是挂着「观察」。
# 历史结论保留在 tactic_evidence.EVIDENCE["ma20_slope"]（provenance 可追溯），
# detect_ma20_slope 函数保留（若日后重新校准区间可直接复用回测链路）。
RETIRED_TACTICS: list[str] = ["ma20_slope"]

TACTIC_MAP: dict[str, dict] = {t["key"]: t for t in TACTICS}

# 单市场（日线）技巧的兜底阈值，集中在此便于日后回测调参。
_BODY_SHADOW_RATIO = 2.0        # 影线长度至少为实体倍数
_SHADOW_RANGE_RATIO = 0.4       # 影线至少占全幅比例
_BODY_SIMILAR_TOL = 0.35        # 揉搓线两根实体差异容忍度
_MA_CONVERGE_TOL = 0.03         # 断头铡刀：MA5/10/20 粘合极差
_GUILLOTINE_DROP = -5.0         # 断头铡刀：单日跌幅阈值 %
# 地量：相对前期均量比例。原文写 20%，但 2026-09-13 在 42 只大中盘、16380 个时点上
# 实测为 0 次命中（地量条件仅成立 7 次）—— 大市值股票几乎不可能缩到 20%。
# 扫描 0.2/0.3/0.4/0.5 后取 0.3：开始出信号（9 次，胜率超额 +18pt，但样本不足以判定），
# 0.4/0.5 信号变多但超额迅速衰减。0.3 仍属「初步」，需样本外验证。
_FLOOR_VOLUME_RATIO = 0.30
_FLOOR_CONFIRM_RATIO = 2.0      # 地量后放量倍数
_FLOOR_LOOKBACK = 10            # 地量搜索窗口（交易日）
_PEAK_GAIN = 50.0               # 天量见天价：短期涨幅阈值 %
_PEAK_TURNOVER = 30.0           # 天量见天价：换手率阈值 %
_PEAK_VOLUME_RATIO = 0.98       # 天量：相对历史最大量的比例
_MACD_ZONE_VOL_RATIO = 1.3      # 零轴下方金叉要求的量能放大倍数（原文物 30%）
_SLOPE_MA = 20                  # 斜率用 20 日均线
_SLOPE_LOOKBACK = 20            # 斜率 = MA20 相对 20 日前的变化率（尺度无关）
# 原文用「15°–35°」描述斜率，但角度依赖 K 线图的纵横比（Y 轴压缩多少，角度就变多少），
# 不是尺度不变的量。这里改用「MA20 的 20 日变化率（%）」表达同一意图：
# 温和上行 = 主升浪布局区，过陡 = 鱼尾加速。两个阈值是初值，需回测校准。
_SLOPE_GOLDEN_LO = 5.0          # 黄金区间下限（% / 20 日）
_SLOPE_GOLDEN_HI = 20.0         # 黄金区间上限，超过视为鱼尾加速


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
    """把条件清单收敛为标准结果结构（与 StrategyAssessment 同形）。

    证据等级在这里统一挂上（`tactic_evidence` 是唯一来源），因此**所有**展示面
    —— 扫描 / 深度分析 / 盯盘 / 持仓 / 简报 —— 拿到的可信度标签必然一致，
    不会出现「同一个形态在 A 页面是买点、在 B 页面是观察」。
    """
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
    evidence = tactic_evidence.describe(tactic["key"])
    # executable：命中 **且** 证据支持动作。未达标的命中不进「买点/卖点」位置，
    # 只进观察池 —— 判定条件成立不等于这个形态被证明有效，这是两件事。
    executable = bool(matched and evidence["actionable"])
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
        "evidence": evidence,
        "executable": executable,
        "gate_note": "" if executable else tactic_evidence.gate_note(tactic["key"]),
    }


def _insufficient(tactic: dict, reason: str) -> dict:
    return _pack(tactic, [], matched=False, action=reason, status="insufficient_data")


def _cond(name: str, passed: bool, detail: str, available: bool = True) -> dict:
    return {"name": name, "passed": passed, "detail": detail, "available": available}


# ---------------- 技巧 1：多周期共振买入 ----------------

# 逐周期口径：(标签, ctx 键 / 周期名, 日线重采样键, 最少根数)
# 月线 MACD(12,26,9) 需要 slow+signal = 35 根才成形，故周线/月线同取 35 根门槛。
# 「日线重采样」只是拿不到真实周/月线时的降级口径：腾讯日线硬上限 640 根，
# 重采样最多得到 ~33 根月线，正好卡在 35 根门槛之下 —— 这就是本技巧历史上
# **在任何股票、任何时点都不可能命中**的原因（不是行情没出现共振，是数据口径算不出来）。
_RESONANCE_PERIODS: tuple[tuple[str, str, str | None, int], ...] = (
    ("日线", "day", None, 60),
    ("周线", "week", "W", 35),
    ("月线", "month", "M", 35),
)


def _resonance_series(
    ctx: dict,
    label: str,
    key: str,
    resample: str | None,
    daily,
    closes: list[float],
    need: int,
) -> tuple[list[float], str]:
    """取某周期的收盘序列，返回 (序列, 不足原因)。序列为空即该周期不可用。

    优先用调用方**按周期直接取到**的周线/月线（`data_service.get_history(period=...)`，
    与日线同一端点、同一台主机，不是新增数据源）；只有拿不到时才退化为从日线重采样，
    并如实报出重采样后的根数 —— 不用臆测填补缺失的 K 线。
    """
    if resample is None:
        if len(closes) >= need:
            return closes, ""
        return [], f"日线仅 {len(closes)} 根，不足 {need} 根"

    hist = ctx.get(key)
    series = list(hist.closes) if hist is not None and getattr(hist, "closes", None) else []
    if series:
        if len(series) >= need:
            return series, ""
        return [], f"{label}仅 {len(series)} 根，不足 {need} 根"

    dates = (daily.dates if daily is not None else None) or []
    series = _resample_closes(dates, closes, resample)
    if len(series) < need:
        return [], f"未取到{label}，由日线重采样仅得 {len(series)} 根，不足 {need} 根"
    return series, ""


def detect_cycle_resonance(ctx: dict) -> dict:
    """日线 / 周线 / 月线 MACD 同时金叉。

    三个周期各自用**该周期的真实 K 线**判定：周线/月线由调用方通过
    `data_service.get_history(period="week"/"month")` 直接取得后放进 ctx。
    从 640 根日线重采样月线只能得到 ~33 根 < MACD 所需的 35 根，历史上因此从未命中；
    改为按周期取数后，本技巧才真正能对「实际出现过共振」的标的给出命中。
    """
    tactic = TACTIC_MAP["cycle_resonance"]
    daily = ctx.get("daily")
    closes = (daily.closes if daily else None) or []
    if len(closes) < 60:
        return _insufficient(tactic, "日线历史不足 60 根，无法计算日线 MACD")

    conditions: list[dict] = []
    metrics: dict = {}
    for label, key, resample, need in _RESONANCE_PERIODS:
        series, why = _resonance_series(ctx, label, key, resample, daily, closes, need)
        if not series:
            conditions.append(_cond(f"{label} MACD 金叉", False, why, available=False))
            continue
        macd = macd_series(series)
        if macd is None:
            conditions.append(
                _cond(f"{label} MACD 金叉", False, f"{label}仅 {len(series)} 根，不足以计算 MACD", available=False)
            )
            continue
        # 更高级别允许稍宽的交叉窗口，避免月线金叉当根错过
        lookback = 3 if resample is None else 4
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
        metrics[f"{key}_bars"] = len(series)
        metrics[f"{key}_dif"] = round(macd["dif"][-1], 3)
        metrics[f"{key}_dea"] = round(macd["dea"][-1], 3)

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
        "断头铡刀成立，趋势转坏信号；建议收紧止损并评估减仓（回测未显示显著超额，勿机械清仓）"
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
        action = "天量后 2 日未创新高，高位风险信号，建议分批减仓"
    elif matched:
        action = "天量见天价，高位风险信号，建议分批减仓并收紧止损"
    else:
        action = "未出现天量见天价结构"
    metrics = {"gain_pct": round(gain, 1), "volume_ratio": round(peak_ratio, 3) if peak_ratio is not None else None}
    return _pack(tactic, conditions, matched=matched, action=action, metrics=metrics)


# ---------------- 技巧 7：MACD 零轴金叉 ----------------

def detect_macd_zone_cross(ctx: dict) -> dict:
    """零轴上方金叉 = 强势买点；零轴下方金叉必须放量（原文物 30%）才轻仓试错。"""
    tactic = TACTIC_MAP["macd_zone_cross"]
    daily = ctx.get("daily")
    closes = (daily.closes if daily else None) or []
    if len(closes) < 60:
        return _insufficient(tactic, "日线不足 60 根，无法计算 MACD")
    volumes = daily.volumes or []
    macd = macd_series(closes)
    if macd is None:
        return _insufficient(tactic, "日线长度不足，无法计算 MACD")
    dif, dea = macd["dif"], macd["dea"]

    crossed = _cross_recently(dif, dea, 3)
    above = dif[-1] > 0
    conditions = [
        _cond("MACD 近 3 根内金叉", crossed, f"DIF {dif[-1]:.3f} / DEA {dea[-1]:.3f}"),
    ]

    if above:
        conditions.append(
            _cond("零轴上方金叉（强势区）", True, f"DIF {dif[-1]:.3f} 位于零轴上方，属中长期走强")
        )
        matched = crossed
        action = "零轴上方金叉，强势区买点，可按计划分批参与" if matched else "未出现零轴上方金叉"
    else:
        base = [v for v in volumes[-6:-1] if v and v > 0]
        base_avg = _mean(base)
        vol_ok = bool(volumes[-1]) and base_avg > 0 and volumes[-1] >= _MACD_ZONE_VOL_RATIO * base_avg
        ratio = volumes[-1] / base_avg if base_avg else 0.0
        conditions.append(
            _cond(
                "零轴下方金叉需放量 ≥30%",
                vol_ok,
                f"最新量 {volumes[-1]:.0f} 为前 5 日均量 {base_avg:.0f} 的 {ratio:.2f} 倍"
                if base_avg
                else "无量能数据",
                available=bool(base_avg) and bool(volumes[-1]),
            )
        )
        matched = crossed and vol_ok
        action = (
            "零轴下方金叉且放量，仅反弹性质，轻仓试错"
            if matched
            else ("零轴下方金叉但未放量，反弹成色不足，不参与" if crossed else "未出现金叉")
        )

    metrics = {"dif": round(dif[-1], 3), "dea": round(dea[-1], 3), "zone": "above" if above else "below"}
    return _pack(tactic, conditions, matched=matched, action=action, metrics=metrics)


# ---------------- 技巧 8：MA10 三日失守 ----------------

def detect_ma10_break(ctx: dict) -> dict:
    """跌破 10 日均线后连续 3 日无力收回。"""
    tactic = TACTIC_MAP["ma10_break"]
    daily = ctx.get("daily")
    c = (daily.closes if daily else None) or []
    if len(c) < 25:
        return _insufficient(tactic, "日线不足 25 根，无法计算 MA10")
    n = len(c)
    prev = n - 4
    ma_prev = _ma_at(c, prev, 10)
    if ma_prev is None:
        return _insufficient(tactic, "日线不足 13 根，无法计算 MA10")

    was_above = c[prev] >= ma_prev
    below_days = sum(
        1
        for j in (n - 3, n - 2, n - 1)
        if (ma := _ma_at(c, j, 10)) is not None and c[j] < ma
    )
    below = below_days == 3
    latest_ma = _ma_at(c, n - 1, 10)
    no_recover = latest_ma is not None and max(c[-3:]) < latest_ma

    conditions = [
        _cond("跌破前一日仍站上 MA10", was_above, f"前一日收盘 {c[prev]:.2f} / MA10 {ma_prev:.2f}"),
        _cond("连续 3 日收盘低于各自 MA10", below, f"三日中 {below_days}/3 日失守"),
        _cond(
            "反弹未收复 MA10",
            no_recover,
            f"三日最高收盘 {max(c[-3:]):.2f} / 最新 MA10 {latest_ma:.2f}" if latest_ma else "无 MA10 数据",
        ),
    ]

    matched = was_above and below and no_recover
    action = "MA10 三日失守，趋势走弱，建议减仓或收紧止损" if matched else "未出现 MA10 三日失守"
    metrics = {"ma10": round(latest_ma, 2) if latest_ma else None, "below_days": below_days}
    return _pack(tactic, conditions, matched=matched, action=action, metrics=metrics)


# ---------------- 技巧 9（已下线）：均线斜率主升 ----------------

# 下线后 TACTIC_MAP 里没有这个 key，detect 函数保留供回测链路复用 ——
# 回测器按 DETECTORS 逐个调用，这里给它一份独立的元数据（不进 TACTICS = 不进扫描/UI）。
_RETIRED_MA20_SLOPE_META = {
    "key": "ma20_slope",
    "name": "均线斜率主升（已下线）",
    "category": "均线与指标",
    "direction": "buy",
    "source": "daily",
    "history_days": 160,
    "warmup": 60,
    "desc": "2026-09-17 下线：两轮回测收益/胜率超额均为负，黄金区间口径跑不赢基准。",
}


def detect_ma20_slope(ctx: dict) -> dict:
    """MA20 温和上行 = 主升布局区；过陡 = 鱼尾加速。

    口径说明：原文用 15°–35° 角度，但角度依赖图表纵横比，不是尺度不变的量。
    这里改用「MA20 的 20 日变化率（%）」，阈值 5%~20% 为初值，需回测校准。
    """
    tactic = _RETIRED_MA20_SLOPE_META
    daily = ctx.get("daily")
    c = (daily.closes if daily else None) or []
    need = _SLOPE_MA + _SLOPE_LOOKBACK + 1
    if len(c) < need:
        return _insufficient(tactic, f"日线不足 {need} 根，无法计算斜率")
    n = len(c)
    ma_now = _ma_at(c, n - 1, _SLOPE_MA)
    ma_prev = _ma_at(c, n - 1 - _SLOPE_LOOKBACK, _SLOPE_MA)
    if ma_now is None or ma_prev is None or ma_prev <= 0:
        return _insufficient(tactic, "均线数据不足，无法计算斜率")

    slope = (ma_now / ma_prev - 1) * 100
    rising = slope > 0
    golden = _SLOPE_GOLDEN_LO <= slope <= _SLOPE_GOLDEN_HI
    too_steep = slope > _SLOPE_GOLDEN_HI
    price_above = c[-1] > ma_now

    conditions = [
        _cond("20 日均线向上", rising, f"MA20 斜率 {slope:+.1f}% / 20 日"),
        _cond(
            f"斜率处于黄金区间（{_SLOPE_GOLDEN_LO:.0f}%~{_SLOPE_GOLDEN_HI:.0f}%）",
            golden,
            f"当前 {slope:+.1f}%" + ("，过陡属鱼尾加速" if too_steep else ""),
        ),
        _cond("现价站上 MA20", price_above, f"现价 {c[-1]:.2f} / MA20 {ma_now:.2f}"),
    ]

    matched = rising and golden and price_above
    if matched:
        action = "MA20 温和上行，主升布局区，可分批参与"
    elif too_steep:
        action = "MA20 过陡（鱼尾加速），只宜小仓博弈，斜率放缓即离场"
    else:
        action = "斜率不在黄金区间，暂不参与"
    metrics = {"slope": round(slope, 2), "ma20": round(ma_now, 2)}
    return _pack(tactic, conditions, matched=matched, action=action, metrics=metrics)


# ---------------- 筹码形态（CYQ 复刻，数据来自 chip_service） ----------------

# 单峰密集：90 成本集中度阈值。东财口径集中度 = (90高-90低)/(90高+90低)，
# 越小越密集。初值 0.07（约 ±3.5% 成本带），需回测校准。
_CHIP_CONC_SINGLE_PEAK = 0.07
# 单峰密集：现价与平均成本（中位成本）的偏离上限，超出说明峰已脱离现价
_CHIP_PEAK_PRICE_TOL = 0.04
# 低位低获利：获利比例上限（获利盘 <10% = 深度套牢结构）
_CHIP_PROFIT_LOW = 0.10
# 低位：现价距 60 日最低收盘的抬升幅度上限（仍在底部区域）
_CHIP_LOW_ZONE_PCT = 10.0
# 筹码转移向上：获利比例 10 日抬升下限（百分点）
_CHIP_TRANSFER_GAIN = 5.0
# 筹码转移向上：成本重心（中位成本）抬升下限（%）
_CHIP_COST_SHIFT = 1.0
# 筹码转移方向约束：10 日内不能出现过深回撤（转移应温和，非 V 型抢筹）
_CHIP_TRANSFER_MAX_DROP = -6.0


def _chip_from_ctx(ctx: dict) -> dict | None:
    """从 ctx 取筹码序列（由调用方注入 chip_service 结果）。"""
    chip = ctx.get("chip")
    if not chip or not chip.get("dates"):
        return None
    return chip


def detect_chip_single_peak(ctx: dict) -> dict:
    """单峰密集：换手充分后 90% 筹码收窄在一个窄成本带，且现价贴着峰。

    条件（确定性清单，非黑箱）：
    1. 90 集中度 ≤ 阈值（成本区间收窄）
    2. 集中度在收敛（10 日前更大）—— 排除「发散后刚好路过」
    3. 现价贴近中位成本（峰没有脱离现价）
    """
    tactic = TACTIC_MAP["chip_single_peak"]
    chip = _chip_from_ctx(ctx)
    if chip is None or len(chip["dates"]) < 20:
        return _insufficient(tactic, "缺少筹码分布数据（东财源失败或冷却中）")

    conc = chip["concentration_90"]
    avg_cost = chip["avg_cost"]
    price = ctx.get("price") or chip.get("close")
    if price is None:
        return _insufficient(tactic, "缺少现价")

    conc_now = conc[-1]
    conc_prev = conc[-10] if len(conc) >= 11 else conc[0]
    narrowing = conc_now <= conc_prev
    cost_now = avg_cost[-1]
    near_peak = abs(price / cost_now - 1) <= _CHIP_PEAK_PRICE_TOL if cost_now > 0 else False

    conditions = [
        _cond(
            f"90 集中度 ≤ {_CHIP_CONC_SINGLE_PEAK:.2f}",
            conc_now <= _CHIP_CONC_SINGLE_PEAK,
            f"当前 {conc_now:.4f}（90 成本 {chip['cost_90_low'][-1]:.2f}~{chip['cost_90_high'][-1]:.2f}）",
        ),
        _cond("集中度仍在收敛", narrowing, f"10 日前 {conc_prev:.4f} → 现在 {conc_now:.4f}"),
        _cond(
            f"现价贴近成本峰（|偏离| ≤ {_CHIP_PEAK_PRICE_TOL:.0%}）",
            near_peak,
            f"现价 {price:.2f} / 中位成本 {cost_now:.2f}，偏离 {abs(price / cost_now - 1) * 100:.1f}%" if cost_now > 0 else "成本数据异常",
        ),
    ]
    matched = all(c["passed"] for c in conditions)
    if matched:
        action = "单峰密集，换手充分蓄势中，突破成本峰可关注"
    else:
        action = "筹码未形成单峰密集结构"
    metrics = {
        "concentration_90": conc_now,
        "concentration_90_10d_ago": conc_prev,
        "avg_cost": cost_now,
    }
    return _pack(tactic, conditions, matched=matched, action=action, metrics=metrics)


def detect_chip_low_profit(ctx: dict) -> dict:
    """低位低获利盘：深跌后获利盘枯竭 + 价格仍在底部区，抛压趋于枯竭。

    条件：
    1. 获利比例 ≤ 10%（套牢盘为主）
    2. 现价距 60 日最低收盘 ≤ 10%（仍在底部区，不是半山腰）
    3. 近 5 日获利比例未继续恶化（跌势趋缓的旁证）
    """
    tactic = TACTIC_MAP["chip_low_profit"]
    chip = _chip_from_ctx(ctx)
    if chip is None or len(chip["dates"]) < 10:
        return _insufficient(tactic, "缺少筹码分布数据（东财源失败或冷却中）")

    profit = chip["profit_ratio"]
    daily = ctx.get("daily")
    closes = (daily.closes if daily else None) or []
    price = ctx.get("price") or chip.get("close")
    if price is None or len(closes) < 60:
        return _insufficient(tactic, "缺少现价或 60 日收盘数据")

    pr_now = profit[-1]
    lo60 = min(closes[-60:])
    off_low = (price / lo60 - 1) * 100 if lo60 > 0 else 0.0
    in_low_zone = off_low <= _CHIP_LOW_ZONE_PCT
    pr_5d = profit[-6] if len(profit) >= 6 else profit[0]
    not_worsening = pr_now >= pr_5d - 0.02

    conditions = [
        _cond(
            f"获利比例 ≤ {_CHIP_PROFIT_LOW:.0%}",
            pr_now <= _CHIP_PROFIT_LOW,
            f"当前 {pr_now:.1%}（获利盘占比）",
        ),
        _cond(
            f"股价处 60 日低位区（距最低收盘 ≤ {_CHIP_LOW_ZONE_PCT:.0f}%）",
            in_low_zone,
            f"现价 {price:.2f}，60 日最低收盘 {lo60:.2f}，抬升 {off_low:.1f}%",
        ),
        _cond("获利比例未继续恶化", not_worsening, f"5 日前 {pr_5d:.1%} → 现在 {pr_now:.1%}"),
    ]
    matched = all(c["passed"] for c in conditions)
    if matched:
        action = "深跌后获利盘枯竭，抛压减轻，企稳信号需右侧确认"
    else:
        action = "获利盘结构未到低位特征"
    metrics = {"profit_ratio": pr_now, "off_low_pct": round(off_low, 1)}
    return _pack(tactic, conditions, matched=matched, action=action, metrics=metrics)


def detect_chip_transfer_up(ctx: dict) -> dict:
    """筹码转移向上：获利比例温和抬升 + 成本重心上移，筹码由套牢转获利。

    条件：
    1. 获利比例 10 日抬升 ≥ 5 个百分点
    2. 中位成本 10 日抬升 ≥ 1%（重心上移）
    3. 期间无深回撤（现价 ≥ 10 日前收盘 × 0.94，排除 V 型抢筹）
    """
    tactic = TACTIC_MAP["chip_transfer_up"]
    chip = _chip_from_ctx(ctx)
    if chip is None or len(chip["dates"]) < 11:
        return _insufficient(tactic, "缺少筹码分布数据（东财源失败或冷却中）")

    profit = chip["profit_ratio"]
    avg_cost = chip["avg_cost"]
    daily = ctx.get("daily")
    closes = (daily.closes if daily else None) or []
    if len(closes) < 11:
        return _insufficient(tactic, "日线不足 11 根，无法核对回撤")

    gain = (profit[-1] - profit[-11]) * 100
    cost_now = avg_cost[-1]
    cost_prev = avg_cost[-11]
    cost_up = (cost_now / cost_prev - 1) * 100 if cost_prev > 0 else 0.0
    price_drop = (closes[-1] / closes[-11] - 1) * 100
    gentle = price_drop >= _CHIP_TRANSFER_MAX_DROP

    conditions = [
        _cond(
            f"获利比例 10 日抬升 ≥ {_CHIP_TRANSFER_GAIN:.0f}pt",
            gain >= _CHIP_TRANSFER_GAIN,
            f"{profit[-11]:.1%} → {profit[-1]:.1%}（{gain:+.1f}pt）",
        ),
        _cond(
            f"成本重心抬升 ≥ {_CHIP_COST_SHIFT:.0f}%",
            cost_up >= _CHIP_COST_SHIFT,
            f"中位成本 {cost_prev:.2f} → {cost_now:.2f}（{cost_up:+.1f}%）",
        ),
        _cond(
            "转移过程温和（无 V 型抢筹）",
            gentle,
            f"10 日价格变动 {price_drop:+.1f}%（要求 ≥ {_CHIP_TRANSFER_MAX_DROP:.0f}%）",
        ),
    ]
    matched = all(c["passed"] for c in conditions)
    if matched:
        action = "筹码温和转移向上，套牢盘消化中，可观察回踩成本峰"
    else:
        action = "筹码未形成向上转移结构"
    metrics = {
        "profit_gain_pt": round(gain, 1),
        "cost_shift_pct": round(cost_up, 2),
        "price_change_pct": round(price_drop, 1),
    }
    return _pack(tactic, conditions, matched=matched, action=action, metrics=metrics)


# 允许把「持有观察」升级为「建议减仓」的卖出形态。
# 原则：只有回测达到显著（`tactic_evidence` 里 tier == "verified"）的技巧才有资格触发仓位动作。
# 这张集合由证据登记表**推导**而不是手写 —— 手写会出现「表里写了已验证、代码里还是空集」这类
# 静默不一致；首次回测（2026-09-13）与复跑（2026-09-16）都没有形态达到显著，故当前为空。
ESCALATE_SELL_KEYS: set[str] = {
    t["key"]
    for t in TACTICS
    if t["direction"] == "sell" and tactic_evidence.is_escalatable(t["key"])
}


DETECTORS = {
    "cycle_resonance": detect_cycle_resonance,
    "intraday_divergence": detect_intraday_divergence,
    "wash_scrub": detect_wash_scrub,
    "guillotine": detect_guillotine,
    "volume_floor": detect_volume_floor,
    "volume_peak": detect_volume_peak,
    "macd_zone_cross": detect_macd_zone_cross,
    "ma10_break": detect_ma10_break,
    "ma20_slope": detect_ma20_slope,
    "chip_single_peak": detect_chip_single_peak,
    "chip_low_profit": detect_chip_low_profit,
    "chip_transfer_up": detect_chip_transfer_up,
}


# ---------------- 对外入口 ----------------

def list_tactics() -> list[dict]:
    """技巧元数据清单（前端据此渲染按钮与分组 + 证据等级角标）。"""
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
            "extra_periods": list(t.get("extra_periods", ())),
            "evidence": tactic_evidence.describe(t["key"]),
            "actionable": tactic_evidence.is_actionable(t["key"]),
        }
        for t in TACTICS
    ]


# 额外周期的取数根数：直接用各周期可返回的上限（周线 300 / 月线 120），
# 因为周期 K 线在 data_service 里是 6h / 24h 长缓存，一次取满可以长期复用。
_EXTRA_PERIOD_DAYS = {"week": 300, "month": 120}


def needed_periods(keys: list[str] | None = None) -> tuple[str, ...]:
    """选中技巧里需要额外拉取的周期（去重、保持稳定顺序）。

    目前只有「多周期共振」声明了 extra_periods；其余技巧一律只看日线/分钟线，
    因此绝大多数调用点不会产生任何额外请求。
    """
    out: list[str] = []
    for key in keys or list(DETECTORS):
        for period in TACTIC_MAP.get(key, {}).get("extra_periods", ()):
            if period not in out:
                out.append(period)
    return tuple(out)


async def load_period_histories(codes: list[str], period: str, *, cache_only: bool = False) -> dict[str, object]:
    """批量拉取某周期的历史 K 线（走并发闸门），返回 {code: StockHistory}。

    与日线是同一个端点、同一台主机，只是 period 参数不同；
    周线/月线在 `data_service` 里用 6h / 24h 长缓存，因此额外请求不会
    随盯盘/扫描的轮询频率被放大。

    `cache_only=True` 时**只读进程内缓存、不发请求**（供盯盘这类每 20s 一轮的高频路径）：
    命中就参与形态判定，未命中就跳过该周期。调用方据此区分「未加载」与「未命中」——
    两者含义完全不同，混起来会把「没拉到数据」读成「该形态不成立」。
    """
    codes = [c for c in codes if c]
    if not codes:
        return {}
    days = _EXTRA_PERIOD_DAYS.get(period, 120)
    if cache_only:
        return {
            code: hist
            for code in codes
            if (hist := data_service.peek_history(code, days, period=period)) is not None
        }
    hists = await concurrency.gather_limited(
        (asyncio.to_thread(data_service.get_history, c, days, period=period) for c in codes),
        return_exceptions=True,
    )
    out: dict[str, object] = {}
    for code, hist in zip(codes, hists):
        if isinstance(hist, BaseException) or hist is None:
            continue
        out[code] = hist
    return out


async def load_tactic_periods(
    codes: list[str], keys: list[str] | None = None, *, cache_only: bool = False
) -> dict[str, dict]:
    """按选中技巧的需要，批量取周线/月线，返回 {code: {"week": hist, "month": hist}}。

    没有技巧需要额外周期时返回空 dict，调用方可以无脑 `**extra.get(code, {})` 合并进 ctx。
    `cache_only=True` 透传给 `load_period_histories`，用于高频轮询路径（只读缓存不拉取）。
    """
    periods = needed_periods(keys)
    if not periods:
        return {}
    codes = [c for c in codes if c]
    if not codes:
        return {}
    loaded = await asyncio.gather(
        *(load_period_histories(codes, p, cache_only=cache_only) for p in periods)
    )
    out: dict[str, dict] = {}
    for period, mapping in zip(periods, loaded):
        for code, hist in mapping.items():
            out.setdefault(code, {})[period] = hist
    return out


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

    日线只按「选中技巧里最长的 history_days」拉一次，避免同一只票重复请求；
    需要周线/月线的技巧（多周期共振）另外按周期取一次，各自独立缓存。
    """
    codes = [c.strip() for c in codes if c and c.strip()]
    selected = [k for k in (keys or list(DETECTORS)) if k in DETECTORS]
    if not codes or not selected:
        return []

    need_daily = any(TACTIC_MAP[k]["source"] == "daily" for k in selected)
    need_intraday = any(TACTIC_MAP[k]["source"] == "intraday" for k in selected)
    days = max((TACTIC_MAP[k]["history_days"] for k in selected if TACTIC_MAP[k]["source"] == "daily"), default=0)

    # 筹码形态需要 chip_service 的 CYQ 序列（自复刻东财，每日缓存）
    need_chip = any(k.startswith("chip_") for k in selected)

    quotes = await asyncio.to_thread(data_service.get_spot_quote, codes)
    quote_map = {q.code: q for q in quotes}

    daily_map: dict[str, object] = {}
    if need_daily and days > 0:
        hist = await concurrency.gather_limited(
            asyncio.to_thread(data_service.get_history, c, days) for c in codes
        )
        daily_map = dict(zip(codes, hist))

    intraday_map: dict[str, object] = {}
    if need_intraday:
        mins = await concurrency.gather_limited(
            asyncio.to_thread(data_service.get_intraday_history, c, intraday_period) for c in codes
        )
        intraday_map = dict(zip(codes, mins))

    # 额外周期（周线/月线）：只有多周期共振需要，其余技巧下这一步不产生任何请求
    period_map = await load_tactic_periods(codes, selected)

    chip_map: dict[str, object] = {}
    if need_chip:
        from app.services import chip_service

        chip_map = await chip_service.get_chip_batch_async(codes)

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
            **(period_map.get(code) or {}),
        }
        if need_chip:
            ctx["chip"] = chip_map.get(code)
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
