"""三度交易理论 · 选股打分（纯函数，确定性、可单测）。

基于成都三度教育（蒋文辉 / 笔名「一路奔行」）《股是股非》系列的「三度理论」：
以主力资金为核心，追踪其「建仓 → 洗盘 → 拉升」的节点，在最佳交易区精准介入。

三度（来自日线 K 的 closes / volumes / turnover）：
  - 厚度（Thickness）：主力介入能量的饱满度 → 量形态，核心是「三阳控三阴」
    （阳线比阴线多、阳线放量阴线缩量、阳线集中阴线分散）。
  - 力度（Strength）：主力对筹码的固守度 → 均线系统，均线从发散走向粘合、穿越、
    翘头向上（「均线归位」/ 金叉），形成 a 区（低位启动）或 b 区（回踩均线健康区）。
  - 速度（Velocity）：主力拉升股价的意志强度 → 关键位置的量价异动
    （放量 + 突破近期高点 / 箱体），是介入的临门一脚。

综合分 = 0.3·厚度 + 0.4·力度 + 0.3·速度（力度权重最高：它决定「是不是最佳交易区」）。

⚠️ 这是**候选筛选**，不是买卖信号。所有分数都是盘面结构读数，没有回测收益口径支撑，
前端必须如实展示、不得渲染成买点指令（与项目既有 pattern/tactic 闸门同一纪律）。
"""

from math import isfinite
from typing import Optional


def _sma(values: list[float], window: int) -> Optional[float]:
    """返回最后 `window` 根的简单移动平均；数据不足返回 None。"""
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _clean(closes: list[float]) -> list[float]:
    return [float(v) for v in closes if isfinite(float(v)) and float(v) > 0]


def _clean_vol(volumes: Optional[list[float]]) -> list[float]:
    if not volumes:
        return []
    return [float(v) for v in volumes if isfinite(float(v)) and float(v) > 0]


# ---------------------------------------------------------------------------
# 厚度：量形态 · 三阳控三阴
# ---------------------------------------------------------------------------

def score_thickness(closes: list[float], volumes: Optional[list[float]], window: int = 20) -> dict:
    """量形态打分 0-10。看最近 `window` 根日线的涨跌分布与量能分布。

    三阳控三阴三要素各占 ~3.33 分：
      1. 阳多阴少：上涨日数 > 下跌日数
      2. 阳放阴缩：上涨日总成交量 > 下跌日总成交量
      3. 阳聚阴散：阳线集中在近期（建仓尾声），阴线散在早期
    """
    price = _clean(closes)
    if len(price) < window:
        # 数据不足：用全部可用数据，但标记；窗口太小不足以判断量形态
        pass
    seg = price[-window:] if len(price) >= window else price
    vol = _clean_vol(volumes)[-len(seg):] if volumes else []

    if len(seg) < 10:
        return {
            "name": "厚度 · 量形态",
            "score": 0.0,
            "status": "insufficient_data",
            "conditions": [],
        }

    up_days = 0
    down_days = 0
    up_vol = 0.0
    down_vol = 0.0
    up_idx: list[int] = []
    for i in range(1, len(seg)):
        rising = seg[i] > seg[i - 1]
        v = vol[i] if i < len(vol) else 0.0
        if rising:
            up_days += 1
            up_vol += v
            up_idx.append(i)
        elif seg[i] < seg[i - 1]:
            down_days += 1
            down_vol += v

    total_days = up_days + down_days

    # 1) 阳多阴少
    day_ratio = up_days / total_days if total_days else 0.5
    day_pts = _clamp((day_ratio - 0.4) / (0.6 - 0.4), 0, 1) * 3.33

    # 2) 阳放阴缩
    vol_ratio = up_vol / (up_vol + down_vol) if (up_vol + down_vol) else 0.5
    vol_pts = _clamp((vol_ratio - 0.4) / (0.2), 0, 1) * 3.33

    # 3) 阳聚阴散：阳线在窗口后半段占比（建仓尾声集中放量）
    half = len(seg) // 2
    up_in_recent = sum(1 for i in up_idx if i >= half)
    recent_share = up_in_recent / up_days if up_days else 0.5
    cluster_pts = _clamp((recent_share - 0.5) / 0.5, 0, 1) * 3.34

    score = round(day_pts + vol_pts + cluster_pts, 1)

    conditions = [
        {
            "label": "阳多阴少",
            "passed": up_days > down_days,
            "detail": f"近 {len(seg)} 日上涨 {up_days} 天 / 下跌 {down_days} 天",
        },
        {
            "label": "阳放阴缩",
            "passed": up_vol > down_vol,
            "detail": f"上涨日量 {up_vol:.0f} vs 下跌日量 {down_vol:.0f}",
        },
        {
            "label": "阳聚阴散",
            "passed": recent_share >= 0.5,
            "detail": f"阳线落在后半段的占比 {recent_share * 100:.0f}%",
        },
    ]
    return {
        "name": "厚度 · 量形态",
        "score": score,
        "status": "passed" if score >= 6 else ("watch" if score >= 4 else "failed"),
        "conditions": conditions,
    }


# ---------------------------------------------------------------------------
# 力度：均线系统 · 均线归位（金叉 + 多头排列 + 站上 MA20）→ a区/b区
# ---------------------------------------------------------------------------

def _detect_golden_cross(closes: list[float], fast: int, slow: int, lookback: int = 12) -> bool:
    """最近 `lookback` 根内，fast MA 由下向上穿越 slow MA（金叉）。"""
    if len(closes) < slow + lookback:
        return False
    for j in range(lookback, 0, -1):
        prev_fast = _sma(closes[: len(closes) - j + 1], fast)
        prev_slow = _sma(closes[: len(closes) - j + 1], slow)
        cur_fast = _sma(closes[: len(closes) - j + 2], fast)
        cur_slow = _sma(closes[: len(closes) - j + 2], slow)
        if prev_fast is None or prev_slow is None or cur_fast is None or cur_slow is None:
            continue
        if prev_fast <= prev_slow and cur_fast > cur_slow:
            return True
    return False


def score_strength(closes: list[float]) -> dict:
    """均线系统打分 0-10，并识别 a区/b区。

    三要素各占 ~3.33 分：
      1. 多头排列：ma5 > ma10 > ma20 > ma60
      2. 均线归位：近期出现 ma5 上穿 ma20 的金叉
      3. 均线抬头 + 站上：ma20 上行且现价 > ma20
    zone：a区 = 低位启动（现价处 60 日低位但均线已转多）；b区 = 回踩均线健康区。
    """
    price = _clean(closes)
    if len(price) < 60:
        return {
            "name": "力度 · 均线归位",
            "score": 0.0,
            "status": "insufficient_data",
            "zone": None,
            "conditions": [],
        }

    ma5 = _sma(price, 5)
    ma10 = _sma(price, 10)
    ma20 = _sma(price, 20)
    ma60 = _sma(price, 60)
    ma20_prev = _sma(price[:-5], 20) if len(price) > 25 else None
    cur = price[-1]

    # 1) 多头排列
    order_pairs = [(ma5, ma10), (ma10, ma20), (ma20, ma60)]
    order_ok = sum(1 for a, b in order_pairs if a is not None and b is not None and a > b)
    order_pts = order_ok / len(order_pairs) * 3.33

    # 2) 金叉（均线归位）
    golden = _detect_golden_cross(price, 5, 20, lookback=12)
    golden_pts = 3.34 if golden else 0.0

    # 3) 均线抬头 + 站上 ma20
    ma20_rising = ma20 is not None and ma20_prev is not None and ma20 > ma20_prev
    above_ma20 = ma20 is not None and cur > ma20
    trend_pts = (1 if ma20_rising else 0) * 1.665 + (1 if above_ma20 else 0) * 1.665

    score = round(order_pts + golden_pts + trend_pts, 1)

    # 区识别
    low60 = min(price[-60:])
    high60 = max(price[-60:])
    pct_from_low = (cur - low60) / (high60 - low60) if high60 > low60 else 0.5
    bullish = order_ok >= 2 and (golden or above_ma20)
    zone = None
    if bullish and pct_from_low <= 0.30:
        zone = "a区"  # 低位启动，风险相对小
    elif bullish and pct_from_low <= 0.75:
        zone = "b区"  # 已脱离低位、回踩均线健康区

    conditions = [
        {
            "label": "多头排列",
            "passed": order_ok == 3,
            "detail": f"ma5>{ma5:.2f} ma10>{ma10:.2f} ma20>{ma20:.2f} ma60>{ma60:.2f}（{order_ok}/3 成立）",
        },
        {
            "label": "均线归位(金叉)",
            "passed": golden,
            "detail": "近 12 日 ma5 上穿 ma20" if golden else "近 12 日未出现金叉",
        },
        {
            "label": "均线抬头且站上",
            "passed": ma20_rising and above_ma20,
            "detail": f"ma20{'上行' if ma20_rising else '走平/下行'}，现价{'站上' if above_ma20 else '未站上'} ma20",
        },
    ]
    return {
        "name": "力度 · 均线归位",
        "score": score,
        "status": "passed" if score >= 6 else ("watch" if score >= 4 else "failed"),
        "zone": zone,
        "conditions": conditions,
    }


# ---------------------------------------------------------------------------
# 速度：量价异动 · 关键位置放量突破
# ---------------------------------------------------------------------------

def score_velocity(closes: list[float], volumes: Optional[list[float]], window: int = 20) -> dict:
    """量价异动打分 0-10。看最近一根（或近 5 日）的放量与突破。

    三要素各占 ~3.33 分：
      1. 量能异动：当日量 / 前 5 日均量 的比值（放量但不极端）
      2. 价格突破：收盘价逼近/创近期 `window` 日新高
      3. 拉升强度：近 5 日涨幅（主力拉升意志）
    """
    price = _clean(closes)
    vol = _clean_vol(volumes)
    if len(price) < window + 1 or not vol or len(vol) < window + 1:
        return {
            "name": "速度 · 量价异动",
            "score": 0.0,
            "status": "insufficient_data",
            "conditions": [],
        }

    cur = price[-1]
    prev5_vol = vol[-6:-1]
    avg_prev5 = sum(prev5_vol) / len(prev5_vol) if prev5_vol else 0.0
    vol_ratio = (vol[-1] / avg_prev5) if avg_prev5 > 0 else 1.0

    high_window = max(price[-window - 1: -1]) if len(price) > window else max(price[:-1])
    pct_to_high = (cur - high_window) / high_window if high_window > 0 else 0.0

    ret5 = (cur / price[-6] - 1) if price[-6] > 0 else 0.0

    # 1) 量能异动：1.2 倍起评，2.5 倍封顶
    spike_pts = _clamp((vol_ratio - 1.2) / (2.5 - 1.2), 0, 1) * 3.33

    # 2) 价格突破：>= 近期高点的 99% 起评
    breakout_pts = _clamp((cur / high_window - 0.90) / 0.10, 0, 1) * 3.34 if high_window > 0 else 0.0

    # 3) 拉升强度：5 日涨 15% 封顶（再高视为已拉完、追涨风险大）
    strength_pts = _clamp(ret5 / 0.15, 0, 1) * 3.33
    # 已在极端高位（>= 近期高 99%）时不额外加分，避免追涨：用突破分替代
    if pct_to_high >= -0.01:
        strength_pts = min(strength_pts, 1.5)

    score = round(spike_pts + breakout_pts + strength_pts, 1)

    conditions = [
        {
            "label": "量能异动",
            "passed": vol_ratio >= 1.2,
            "detail": f"当日量 / 前 5 日均量 = {vol_ratio:.2f} 倍",
        },
        {
            "label": "价格突破",
            "passed": pct_to_high >= -0.01,
            "detail": f"现价距近 {window} 日高点 {pct_to_high * 100:+.1f}%",
        },
        {
            "label": "拉升强度",
            "passed": ret5 >= 0.05,
            "detail": f"近 5 日涨幅 {ret5 * 100:+.1f}%",
        },
    ]
    return {
        "name": "速度 · 量价异动",
        "score": score,
        "status": "passed" if score >= 6 else ("watch" if score >= 4 else "failed"),
        "conditions": conditions,
    }


# ---------------------------------------------------------------------------
# 综合
# ---------------------------------------------------------------------------

WEIGHTS = {"thickness": 0.3, "strength": 0.4, "velocity": 0.3}


def score_sandu(history) -> dict:
    """对单只票的日线 K 做三度综合打分。

    入参 `history` 为 `StockHistory`（有 closes / volumes / turnover）。
    返回结构化结果：三度分、综合分、status、zone、action、reasons、dimensions。
    """
    closes = list(history.closes) if getattr(history, "closes", None) else []
    volumes = list(history.volumes) if getattr(history, "volumes", None) else None

    if len(_clean(closes)) < 30:
        return {
            "thickness": 0.0,
            "strength": 0.0,
            "velocity": 0.0,
            "overall": 0.0,
            "status": "insufficient_data",
            "zone": None,
            "action": "历史数据不足 30 根日线，无法判断三度",
            "reasons": ["日线不足 30 根，三度理论依赖量价结构，样本太少不可信"],
            "dimensions": [],
        }

    thick = score_thickness(closes, volumes)
    strong = score_strength(closes)
    vel = score_velocity(closes, volumes)

    overall = round(
        WEIGHTS["thickness"] * thick["score"]
        + WEIGHTS["strength"] * strong["score"]
        + WEIGHTS["velocity"] * vel["score"],
        1,
    )

    # 三度齐备才算 passed；否则按综合分降级
    if thick["score"] >= 6 and strong["score"] >= 6 and vel["score"] >= 5:
        status = "passed"
    elif overall >= 5:
        status = "watch"
    else:
        status = "failed"

    zone = strong.get("zone")

    if status == "passed":
        if zone == "a区":
            action = "三度齐备·低位启动区（a区）：可小仓试错，放量突破时加"
        elif zone == "b区":
            action = "三度齐备·回踩健康区（b区）：回踩均线不破可介入"
        else:
            action = "三度齐备：等待放量突破或缩量回踩均线的确认信号"
    elif status == "watch":
        action = "观察：三度尚未齐备，继续跟踪量能与均线归位"
    else:
        action = "暂不参与：量/线/速至少一项偏弱，等待结构重新转强"

    reasons = []
    if thick["score"] < 6:
        reasons.append(f"厚度偏弱({thick['score']})：量形态未满足三阳控三阴")
    if strong["score"] < 6:
        reasons.append(f"力度偏弱({strong['score']})：均线未归位或多头排列不完整")
    if vel["score"] < 5:
        reasons.append(f"速度偏弱({vel['score']})：未见关键位置放量突破")
    if not reasons:
        reasons.append(f"三度齐备（厚{thick['score']}/力{strong['score']}/速{vel['score']}），强势启动候选")

    return {
        "thickness": thick["score"],
        "strength": strong["score"],
        "velocity": vel["score"],
        "overall": overall,
        "status": status,
        "zone": zone,
        "action": action,
        "reasons": reasons,
        "dimensions": [
            {k: v for k, v in thick.items() if k != "zone"},
            strong,
            vel,
        ],
    }
