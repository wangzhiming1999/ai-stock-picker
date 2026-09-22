"""决策先锋：从 暗盘资金 · 趋势 · 活跃度 三维选股，并给出诊股 / 板块强度 / 主力抱团 / 潜力龙头。

## 这个服务解决什么

`quad_service` 的四维榜（基本面 / 技术面 / 资金面 / 消息面）回答的是「这票好不好」——
偏**静态质地**。决策先锋回答的是另一个问题：**「今天资金在往哪去、谁跟着走」**——
偏**当日行为**。两者维度不同、候选池不同、口径不可比，因此是两张独立的榜
（各自一张快照表，不共用），前端放在同一个子页里并列展示。

## 三条硬约束（改这个文件前先读）

1. **资金维必须走批量端点，永远不要逐股请求。**
   `spot_service.fetch_fund_flow_rows()` 复用的是全市场快照那套东财 clist 传输层，
   换一个 `fid` 就按主力净流入排序返回整页个股 —— 一次请求覆盖数百只。
   逐股打 `stock_individual_fund_flow` 是 memory 里点名的风控主因，这里刻意绕开。

2. **`refresh=True` 现在会穿透底层行情源（`force=True`）。**
   这是用户显式选择的行为（「刷新按钮穿透到底层」）：refresh 不再只穿透本服务自己的三层缓存
   （内存 → DB 快照 → 重算），还会一路 force 到全市场快照（跳过内存 5min 与 Supabase 6h 持久化快照）。
   之所以敢放开，是因为底层 `_get_spot` 自带**跨实例冷却（180s）+ 最小间隔（60s）+ 共享失败标记**三重守卫，
   且前端 refresh 走 `spotGuard` 的**二次确认 + 冷却倒计时**，连点不会拖长封禁。
   非 forced 的每日路径（定时任务 / 冷启动）仍 `force=False`，只命中既有缓存与冷却。

3. **诊断型输出不得带动作话术。**
   三维分是「今天的读数」，不是「买入信号」。买卖时机直接复用
   `signal_service.compute_signals` 的结构位，其证据等级见 `tactic_evidence.monitor_levels`
   （**买入侧实测为负**）—— 只能作价位参考，且必须把证据档一起下发。

## 「暗盘资金」的口径说明（不要含糊过去）

A 股**没有**公开的暗盘成交数据。本维用的是东财 **主力净流入 = 超大单 + 大单** 净额，
是「大单口径」。产品名沿用用户的说法，但 UI 与接口里一律标注为
「主力资金（大单口径）」，避免让读者以为拿到了真实暗盘数据。
"""
from __future__ import annotations

import asyncio
import time

from app.routes import market as market_routes
from app.services import (
    concurrency,
    data_service,
    limitup_service,
    quad_service,
    regime_service,
    signal_service,
    spot_service,
    supabase_store,
    tactic_evidence,
    trade_calendar_service,
)
from app.services.cache_utils import put_bounded

# ---------------- 常量 ----------------

DIM_KEYS = ["dark_money", "trend", "activity"]
DIM_NAMES = {"dark_money": "暗盘资金", "trend": "趋势", "activity": "活跃度"}

# 综合分权重。资金维放在最前、权重最高 —— 这是「今天钱在往哪去」这条主线。
# 资金维不可用时**重新归一化到可用维度**，而不是拿 0 分当缺失（0 分会被误读成「资金很差」）。
DIM_WEIGHTS = {"dark_money": 0.40, "trend": 0.35, "activity": 0.25}

KLINE_DAYS = 250          # 趋势维需要 250 日高点，腾讯日 K 上限 640
POOL_TOP_N = 40           # 进入 K 线精算的候选数（与四维榜同量级，逐只请求受此上限约束）
BOARD_SIZE = 20           # 榜单展示条数
LEADER_SIZE = 8           # 潜力龙头条数
# 龙头门槛提成具名常量，让「门槛是否够得着」可以被测试断言 —— 实测教训：
# 资金维漏配 f184 → 资金分被压在 5.0~5.6 → 这里写死的 7 让整块**永久为空**，
# 而界面上没有任何报错，看上去只是「今天没有龙头」。
LEADER_MIN_DARK_MONEY = 7.0
LEADER_MIN_TREND = 6.0
LEADER_MAX_CHANGE_PCT = 9.0   # 涨幅≥9% 大概率一字/秒板，列出来只会导向买不进的价格
LEADER_MIN_PCT_FROM_HIGH = -30.0
SECTOR_SIZE = 12          # 板块强度展示条数
WIDE_POOL_TOP_N = 150      # 宽池：廉价预筛（无 K 线）候选上限，仅供浏览/筛选，不进精算

# 选股排序（selection_score）并入的「已有信号」加成 —— 用命名常量便于测试断言。
# 这些信号都来自已经加载/已算好的数据（资金批次、涨停池、全市场快照），
# 不再打任何逐股请求，因此并入排序不会放大风控风险。
SECTOR_SEL_WEIGHT = 1.0    # 板块强度分（0-10）对 selection_score 的最大加成
MAINLINE_BONUS = 0.4       # 属当日强势/主线板块的加成
BREADTH_BEARISH = 5.0      # 市场宽度分低于此值视为偏弱市
MOMENTUM_PENALTY = 1.0     # 偏弱市下对高活跃度（高 beta 动量）标的的最大降权

# 资金流批次（东财 clist）缓存
_FUND_TTL = 600           # 10 分钟内存缓存
_FUND_FAIL_COOLDOWN = 180 # 失败后本实例冷却，期间不再打资金流端点
_FUND_FORCE_MIN_INTERVAL = 60  # refresh 穿透资金流缓存的最小间隔（防连点）
_fund_cache: tuple[float, list[dict]] | None = None   # (monotonic, rows)
_fund_failed_at: float | None = None
_fund_last_live: float | None = None

# 榜单内存缓存：key=交易日
_board_cache: dict[str, tuple[str, dict]] = {}
_BOARD_CACHE_MAX = 7

# 资金快照映射持久化上限：把最极端的两侧各留一部分，避免整份 jsonb 过大
_FUND_MAP_MAX = 400


def clear_caches() -> None:
    """清空进程内缓存（测试与诊断用；跨实例的 DB 快照不受影响）。"""
    global _fund_cache, _fund_failed_at, _fund_last_live
    _fund_cache = None
    _fund_failed_at = None
    _fund_last_live = None
    _board_cache.clear()


def _clamp(v: float, lo: float = 0.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, v))


def _is_clean_name(name: str) -> bool:
    """风险标识过滤（与 `quad_service._is_clean` 同规则，仅按前缀匹配，避免误杀 TCL 等）。"""
    n = (name or "").strip().upper()
    return not (n.startswith(("ST", "*ST", "N", "C")) or "退" in n)


def _pct_rank(values: list[float], v: float) -> float:
    """v 在 values 中的分位（0~1，越大越高）。

    板块强度刻意用**当日横截面分位**而不是绝对阈值：资金净流入的绝对量级随大盘
    情绪整体漂移（冰点日与亢奋日差一个数量级），写死阈值等于每过几周就悄悄失效。
    代价是分位换日即换基准，**不可跨日比较** —— 这一点必须写在接口与 UI 上。
    """
    if not values:
        return 0.5
    below = sum(1 for x in values if x < v)
    equal = sum(1 for x in values if x == v)
    return (below + equal / 2) / len(values)


# ---------------- 资金流批次（东财 clist，批量） ----------------


async def _load_fund_flow(force: bool = False) -> dict:
    """取全市场资金流批次（吸筹侧 + 出货侧各一次请求），返回
    ``{status, rows, inflow_n, outflow_n, fetched_at}``。

    status 取值（**必须原样下发给前端**，否则「资金维全是中性分」会被误读成
    「今天没有股票被资金青睐」）：
      - ``ok``         两侧都取到了
      - ``cooldown``   行情源处于风控冷却期，本次跳过（不视为失败，也不延长冷却）
      - ``unavailable`` 拉取失败（本实例已进入冷却）
      - ``cached``     命中内存缓存
    """
    global _fund_cache, _fund_failed_at, _fund_last_live
    now = time.monotonic()

    if not force and _fund_cache and now - _fund_cache[0] < _FUND_TTL:
        return {
            "status": "cached",
            "rows": _fund_cache[1],
            "fetched_at": None,
        }

    if _fund_failed_at is not None and now - _fund_failed_at < _FUND_FAIL_COOLDOWN:
        remaining = int(_FUND_FAIL_COOLDOWN - (now - _fund_failed_at))
        return {"status": "unavailable", "rows": [], "note": f"资金流端点冷却中（{remaining}s）"}

    # 与全市场快照同源（同一批东财 push2 域名），快照在被风控时资金流必然也拿不到。
    # 这里**先看共享冷却**再决定要不要打 —— 冷却期内撞端点正是把封禁拖长的动作。
    cooling = await market_routes.spot_cooldown_seconds()
    if cooling > 0:
        return {"status": "cooldown", "rows": [], "note": f"行情源被风控，冷却中（{cooling}s）"}

    if (
        force
        and _fund_last_live is not None
        and now - _fund_last_live < _FUND_FORCE_MIN_INTERVAL
    ):
        # force 节流：连点 refresh 不能变成连打端点
        rows = _fund_cache[1] if _fund_cache else []
        return {"status": "cached", "rows": rows, "note": "刷新间隔过短，返回上次结果"}

    inflow, outflow = await asyncio.gather(
        asyncio.to_thread(spot_service.fetch_fund_flow_rows, "f62", False),
        asyncio.to_thread(spot_service.fetch_fund_flow_rows, "f62", True),
        return_exceptions=True,
    )

    merged: dict[str, dict] = {}
    ok_sides = 0
    for side in (inflow, outflow):
        if isinstance(side, BaseException) or not isinstance(side, list):
            continue
        ok_sides += 1
        for row in side:
            code = row.get("code")
            if code and code not in merged:
                merged[code] = row

    if not merged:
        _fund_failed_at = now
        return {
            "status": "unavailable",
            "rows": [],
            "note": f"资金流端点不可用（吸筹侧 {type(inflow).__name__} / 出货侧 {type(outflow).__name__}）",
        }

    rows = list(merged.values())
    _fund_cache = (now, rows)
    _fund_last_live = now
    _fund_failed_at = None
    return {"status": "ok", "rows": rows, "sides_ok": ok_sides, "fetched_at": now}


def _fund_map(rows: list[dict], limit: int = _FUND_MAP_MAX) -> dict[str, list]:
    """资金批次 → 可持久化的紧凑映射 ``{code: [主力净额元, 净占比%, 超大单净额元, 行业]}``。

    按 |主力净额| 取前 limit 只：金额最大的那批才是「暗盘资金」真正有信息量的部分，
    全量落库会让 jsonb 膨胀到几百 KB 而增量信息很少。
    """
    ordered = sorted(rows, key=lambda r: abs(r.get("main_net") or 0), reverse=True)[:limit]
    out: dict[str, list] = {}
    for r in ordered:
        code = r.get("code")
        if not code:
            continue
        out[code] = [
            round(r["main_net"] / 1e8, 4) if r.get("main_net") is not None else None,
            round(r["main_pct"], 2) if r.get("main_pct") is not None else None,
            round(r["super_net"] / 1e8, 4) if r.get("super_net") is not None else None,
            r.get("sector"),
        ]
    return out


# ---------------- 三维打分 ----------------


def _score_dark_money(fund: dict | None, rich: dict, available: bool) -> tuple[float | None, str]:
    """暗盘资金（大单口径）：主力净占比为主，超大单与量价配合为辅。

    fund 为 None 有两种情况，**必须区分**：
      - available=False → 资金维整体不可用，返回 None（调用方重新归一化权重）
      - available=True 但不在批次内 → 该股主力净流入不在当日两端，给中偏低分
        （不能给 0：批次只覆盖两端，中间段的票没有被观测，不是「资金很差」）
    """
    if not available:
        return None, "资金流端点不可用，本维不参与综合分"
    if fund is None:
        base = 4.0
        return base, "未入当日主力净流入两端榜，资金维按中性偏弱处理"

    base = 5.0
    parts: list[str] = []
    net = fund.get("main_net")
    pct = fund.get("main_pct")
    super_net = fund.get("super_net")

    if pct is not None:
        if pct >= 8:
            base += 2.5
            parts.append(f"主力净占比 {pct:.1f}% 强吸筹")
        elif pct >= 4:
            base += 1.8
            parts.append(f"主力净占比 {pct:.1f}%")
        elif pct >= 1.5:
            base += 1.0
            parts.append(f"主力净占比 {pct:.1f}%")
        elif pct >= 0:
            base += 0.3
            parts.append("主力小幅净流入")
        elif pct >= -2:
            base -= 0.8
            parts.append(f"主力净流出 {pct:.1f}%")
        else:
            base -= 2.0
            parts.append(f"主力净流出 {pct:.1f}% 明显")

    if net is not None and net > 0:
        net_yi = net / 1e8
        if net_yi >= 3:
            base += 1.0
            parts.append(f"净流入 {net_yi:.1f}亿")
        elif net_yi >= 1:
            base += 0.6
        elif net_yi >= 0.3:
            base += 0.3
    if super_net is not None and super_net > 0 and (pct or 0) >= 3:
        base += 1.2
        parts.append("超大单同步净流入")

    # 量价配合：放量上涨且主力净流入 → 吸筹；上涨但主力净流出 → 拉高出货嫌疑
    change = rich.get("change_pct") or 0
    vr = rich.get("volume_ratio")
    if change > 0 and (vr or 0) >= 1.2 and (pct or 0) > 0:
        base += 0.5
        parts.append("量价齐升")
    if change > 3 and (pct or 0) < 0:
        base -= 1.0
        parts.append("上涨但主力净流出（拉高出货嫌疑）")

    return round(_clamp(base), 1), "；".join(parts) or "资金面中性"


def _trend_metrics(closes: list[float], highs: list[float], lows: list[float], price: float) -> dict | None:
    """趋势维所需的原始指标（纯函数，便于单测）。"""
    if not closes or len(closes) < 60 or price <= 0:
        return None

    def _ma(n: int) -> float:
        w = closes[-n:] if len(closes) >= n else closes
        return sum(w) / len(w)

    ma5, ma20, ma60 = _ma(5), _ma(20), _ma(60)
    # MA20 斜率：用「5 根之前"到现在」的 MA20 变化，避免只看单点
    ma20_prev = sum(closes[-25:-5]) / 20 if len(closes) >= 25 else ma20
    ma20_slope = (ma20 - ma20_prev) / ma20_prev * 100 if ma20_prev else 0.0

    highs_s = highs if highs and len(highs) == len(closes) else closes
    lows_s = lows if lows and len(lows) == len(closes) else closes
    high_all = max(highs_s)
    low_all = min(lows_s)
    pct_from_high = (price / high_all - 1) * 100 if high_all else 0.0

    # 底部抬升：近 60 日低点是否高于前 60 日低点
    if len(lows_s) >= 120:
        low_recent = min(lows_s[-60:])
        low_prev = min(lows_s[-120:-60])
        bottom_rising = low_recent > low_prev
    else:
        bottom_rising = False

    # MACD(12,26,9)
    ema12, ema26 = closes[0], closes[0]
    difs: list[float] = []
    for c in closes:
        ema12 += (c - ema12) * 2 / 13
        ema26 += (c - ema26) * 2 / 27
        difs.append(ema12 - ema26)
    dea = sum(difs[-9:]) / 9

    r20 = (closes[-1] / closes[-21] - 1) * 100 if len(closes) >= 21 and closes[-21] else 0.0

    # 近 5 日振幅（用真实高低价，缺则退化为收盘价近似）
    amp5 = 0.0
    if len(highs_s) >= 5 and len(lows_s) >= 5:
        hi5, lo5 = max(highs_s[-5:]), min(lows_s[-5:])
        if lo5:
            amp5 = (hi5 - lo5) / lo5 * 100

    return {
        "ma5": ma5,
        "ma20": ma20,
        "ma60": ma60,
        "ma20_slope": ma20_slope,
        "pct_from_high": pct_from_high,
        "bottom_rising": bottom_rising,
        "macd_above": difs[-1] > dea,
        "r20": r20,
        "amp5": amp5,
    }


def _score_trend(m: dict | None, price: float) -> tuple[float | None, str]:
    """趋势维：均线排列 / MA20 斜率 / 距高点 / MACD / 20 日涨幅 / 底部抬升。"""
    if m is None:
        return None, "K 线不足 60 根，趋势维不参与综合分"

    base = 5.0
    parts: list[str] = []
    ma5, ma20, ma60 = m["ma5"], m["ma20"], m["ma60"]

    if ma5 > ma20 > ma60 and price > ma5:
        base += 2.5
        parts.append("均线多头排列")
    elif ma5 > ma20 and price > ma5:
        base += 1.5
        parts.append("短期均线多头")
    elif price < ma60:
        base -= 2.0
        parts.append("跌破 MA60")
    elif price < ma20:
        base -= 1.2
        parts.append("跌破 MA20")

    if m["ma20_slope"] > 0.5:
        base += 0.8
        parts.append("MA20 上行")
    elif m["ma20_slope"] < -0.5:
        base -= 0.8
        parts.append("MA20 下行")

    pfh = m["pct_from_high"]
    if pfh > -5:
        base += 1.2
        parts.append("贴近 250 日高点")
    elif pfh > -15:
        base += 0.6
        parts.append("处于上行趋势")
    elif pfh < -35:
        base -= 1.5
        parts.append("距高点较远")

    if m["macd_above"]:
        base += 1.0
        parts.append("MACD 金叉运行")
    else:
        base -= 0.8

    if 0 <= m["r20"] <= 25:
        base += 0.5
        parts.append(f"近 20 日 {m['r20']:.1f}% 稳健")
    elif m["r20"] > 45:
        base -= 1.0
        parts.append(f"近 20 日 +{m['r20']:.1f}% 短期过热")
    elif m["r20"] < -20:
        base -= 1.0

    if m["bottom_rising"]:
        base += 0.5
        parts.append("底部抬升")

    return round(_clamp(base), 1), "；".join(parts) or "趋势中性"


def _score_activity(rich: dict, m: dict | None) -> tuple[float, str]:
    """活跃度：按市值分层的换手率 / 量比 / 成交额 / 近 5 日振幅 / 盘中 5 分钟涨跌。

    分层是必须的：大盘蓝筹天然低换手，「换手 1%」在 3000 亿市值上是活跃、
    在 50 亿市值上是不活跃。不分层会让榜单整体偏向小盘。
    """
    base = 5.0
    parts: list[str] = []

    mc = rich.get("market_cap_yi") or 0
    is_mega = mc >= 800
    turnover = rich.get("turnover")

    if turnover is not None:
        if is_mega:
            if 0.4 <= turnover <= 2:
                base += 1.6
                parts.append(f"换手 {turnover:.2f}% 蓝筹活跃")
            elif turnover < 0.25:
                base -= 1.5
                parts.append(f"换手 {turnover:.2f}% 清淡")
            elif turnover > 6:
                base -= 0.5
        else:
            if 3 <= turnover <= 8:
                base += 2.0
                parts.append(f"换手 {turnover:.1f}% 活跃健康")
            elif 1.5 <= turnover < 3:
                base += 1.5
                parts.append(f"换手 {turnover:.1f}% 温和活跃")
            elif 1 <= turnover < 1.5:
                base += 0.5
                parts.append(f"换手 {turnover:.1f}% 正常")
            elif 8 < turnover <= 15:
                base -= 0.3
                parts.append(f"换手 {turnover:.1f}% 偏高")
            elif turnover > 15:
                base -= 1.5
                parts.append(f"换手 {turnover:.1f}% 异常放量")
            elif turnover < 0.5:
                base -= 1.5
                parts.append(f"换手 {turnover:.1f}% 冷清")

    vr = rich.get("volume_ratio")
    if vr is not None:
        if 1.0 <= vr <= 2.5:
            base += 1.5
            parts.append(f"量比 {vr:.2f} 温和放量")
        elif 2.5 < vr <= 5:
            base += 0.6
            parts.append(f"量比 {vr:.2f}")
        elif 0.5 <= vr < 1.0:
            base -= 0.5
        elif vr > 6:
            base -= 1.2
            parts.append(f"量比 {vr:.2f} 爆量")

    # 成交额：⚠️ 只在**取到值**时打分。amount 缺失（None）与「成交额很低」是两件事，
    # 前者是没观测到，后者才是读数 —— 把 None 当 0 处理会凭空扣 1.5 分，
    # 让数据缺失伪装成「个股交投冷清」（本项目已踩过同类坑：缺 PE 曾把候选池清空）。
    amount = rich.get("amount_yi")
    if amount is not None and amount > 0:
        if amount >= 20:
            base += 1.2
            parts.append(f"成交 {amount:.0f}亿")
        elif amount >= 8:
            base += 0.8
        elif amount >= 3:
            base += 0.4
        elif amount < 0.8:
            base -= 1.5
            parts.append(f"成交仅 {amount:.2f}亿 冷清")

    if m is not None:
        amp = m["amp5"]
        if 2 <= amp <= 6:
            base += 0.8
            parts.append(f"近 5 日振幅 {amp:.1f}% 适中")
        elif amp > 9:
            base -= 0.3
            parts.append(f"近 5 日振幅 {amp:.1f}% 波动偏大")

    c5 = rich.get("change_5min")
    if c5 is not None and c5 >= 0.3:
        base += 0.5
        parts.append("盘口走强")

    return round(_clamp(base), 1), "；".join(parts) or "交投数据有限"


def _composite(scores: dict[str, float | None]) -> tuple[float, dict[str, float]]:
    """可用维度加权平均（权重在同一组可用维度内重新归一化）。

    缺失维**不计 0 分**：0 分是「这一维很差」的读数，不是「这一维没观测到」。
    把两者混为一谈会让数据源故障伪装成「个股质地差」——本项目已经踩过一次同类坑
    （行情源缺 PE 时曾把候选池清空）。
    """
    avail = {k: v for k, v in scores.items() if v is not None}
    if not avail:
        return 0.0, {}
    total_w = sum(DIM_WEIGHTS[k] for k in avail)
    used = {k: round(DIM_WEIGHTS[k] / total_w, 4) for k in avail}
    overall = sum(avail[k] * used[k] for k in avail)
    return round(overall, 2), used


def _selection_score(
    item: dict,
    sector_strength: float | None,
    is_mainline: bool,
    breadth_score: float | None,
) -> float:
    """选股排序分 = 三维综合分 + 板块强度加成 + 主线加成 − 弱市动量降权。

    只用于排名，**不改写** ``overall_score``（那是面向用户的「三维分」读数，含义恒定）。
    任一信号缺失时优雅退化到三维综合分本身，不会把「没观测到」算成惩罚。
    """
    base = float(item.get("overall_score") or 0)
    s_boost = (sector_strength / 10.0) * SECTOR_SEL_WEIGHT if sector_strength is not None else 0.0
    m_boost = MAINLINE_BONUS if is_mainline else 0.0
    r_pen = 0.0
    if breadth_score is not None and breadth_score < BREADTH_BEARISH:
        activity = (item.get("scores") or {}).get("activity") or 0
        if activity >= 7:  # 只对明显高活跃度（高 beta 动量）标的降权，弱市追高更危险
            r_pen = (BREADTH_BEARISH - breadth_score) / BREADTH_BEARISH * MOMENTUM_PENALTY
    return round(base + s_boost + m_boost - r_pen, 3)


def _breadth_score_from_spot(spot: list[dict]) -> float | None:
    """从全市场快照免费算市场宽度分（0-10），无新增请求。失败降级为 None。"""
    try:
        b = regime_service.compute_breadth(spot)
        return (b or {}).get("breadth_score")
    except Exception as e:
        print(f"[vanguard] 市场宽度计算失败，状态门控降级: {e}")
        return None


# ---------------- 候选池与精算 ----------------


def _preselect(spot: list[dict], fund_by_code: dict[str, dict], top_n: int = POOL_TOP_N) -> list[dict]:
    """硬过滤 + 初筛打分（只用快照与资金批次，不拉 K 线），取 Top N 进入精算。

    初筛必须在 K 线之前：逐只拉 K 线是这套链路里最贵的一步（40 只 × 1 请求），
    先按「不用 K 线就能算的东西」收窄，才不会为了 5500 只票做出 5500 次请求。
    """
    pool: list[dict] = []
    for r in spot:
        name = r.get("name") or ""
        price = r.get("price") or 0
        code = r.get("code") or ""
        if not code or not _is_clean_name(name):
            continue
        if code.startswith(("4", "8", "920")):  # 排除北交所
            continue
        if not (2 <= price <= 300):
            continue
        if (r.get("amount_yi") or 0) < 3:
            continue
        change = r.get("change_pct") or 0
        if not (-6 <= change <= 9.6):
            continue

        s = 0.0
        fund = fund_by_code.get(code)
        if fund:
            pct = fund.get("main_pct") or 0
            if pct >= 8:
                s += 4.0
            elif pct >= 4:
                s += 2.8
            elif pct >= 1.5:
                s += 1.6
            elif pct >= 0:
                s += 0.6
            elif pct < -4:
                s -= 1.5
        turnover = r.get("turnover")
        if turnover is not None:
            if 3 <= turnover <= 8:
                s += 2.0
            elif 1.5 <= turnover < 3:
                s += 1.4
            elif 8 < turnover <= 15:
                s += 0.4
        vr = r.get("volume_ratio")
        if vr is not None:
            if 1.0 <= vr <= 2.5:
                s += 1.2
            elif 2.5 < vr <= 5:
                s += 0.5
        amount = r.get("amount_yi") or 0
        if 5 <= amount <= 120:
            s += 0.8
        elif amount > 120:
            s += 0.3
        if 0 <= change <= 6:
            s += 0.6
        r["_pre_score"] = s
        pool.append(r)

    # 同分时成交额更大者优先，避免原数据分组顺序造成偏交易所
    pool.sort(key=lambda x: (x["_pre_score"], x.get("amount_yi") or 0), reverse=True)
    return pool[:top_n]


async def _score_one(rich: dict, fund: dict | None, fund_available: bool) -> dict | None:
    """单只票三维精算。需要 K 线 → 并发受限。"""
    code = rich["code"]
    try:
        hist = await asyncio.to_thread(data_service.get_history, code, KLINE_DAYS)
    except Exception:
        hist = None

    closes = list(hist.closes) if hist and hist.closes else []
    highs = list(hist.highs) if hist and hist.highs else []
    lows = list(hist.lows) if hist and hist.lows else []
    price = rich.get("price") or (closes[-1] if closes else 0)
    # ⚠️ 不要用快照现价去覆盖 closes[-1]：日 K 的最后一根若是进行中的那根，
    # 其收盘价本来就等于现价（实测差异 0.000%）；而覆盖会破坏 OHLC 内部一致性
    # （high/low 仍是原值，可能不夹住新的 close）。compute_signals 的设计就是
    # 「price 只参与判断、basis=closes[:-1] 定档」，两者分开传即可。

    metrics = _trend_metrics(closes, highs, lows, price)
    if metrics is None:
        return None

    dm_score, dm_comment = _score_dark_money(fund, rich, fund_available)
    tr_score, tr_comment = _score_trend(metrics, price)
    ac_score, ac_comment = _score_activity(rich, metrics)

    scores: dict[str, float | None] = {
        "dark_money": dm_score,
        "trend": tr_score,
        "activity": ac_score,
    }
    overall, weights_used = _composite(scores)

    # 买卖时机：复用盯盘那条结构位链路（买卖点=主支撑/主压力，不随现价漂移）
    levels = signal_service.compute_signals(closes, price, highs, lows)
    # 预期价格（执行锚点）：这里是「选股榜」，没有现成的形态判定，用 auto 档 ——
    # 现价贴着主压力就按突破位给价、否则按回踩位给价，规则固定可复算。
    # 它是**锚点**不是预测，也不参与任何收益口径。
    expected = signal_service.expected_price_from_levels(price, levels, "auto")

    tags: list[str] = []
    avail = [v for v in scores.values() if v is not None]
    if avail and all(v >= 8 for v in avail) and len(avail) == 3:
        tags.append("三维共振")
    elif avail and all(v >= 7 for v in avail):
        tags.append("全维强势")
    if dm_score is not None and dm_score >= 8:
        tags.append("资金主导")
    if tr_score is not None and tr_score >= 8:
        tags.append("趋势明确")
    if ac_score is not None and ac_score >= 8:
        tags.append("量能活跃")
    if levels and (levels.get("rr_ratio") or 0) >= 2:
        tags.append("风报比达标")

    return {
        "code": code,
        "name": rich.get("name") or "",
        "price": round(price, 2),
        "change_pct": round(rich.get("change_pct") or 0, 2),
        "turnover": round(rich["turnover"], 2) if rich.get("turnover") is not None else None,
        "volume_ratio": round(rich["volume_ratio"], 2) if rich.get("volume_ratio") is not None else None,
        "amount_yi": round(rich.get("amount_yi") or 0, 2),
        "market_cap_yi": round(rich["market_cap_yi"], 1) if rich.get("market_cap_yi") else None,
        "sector": (fund or {}).get("sector") or None,
        "overall_score": overall,
        "weights_used": weights_used,
        "scores": scores,
        "comments": {
            "dark_money": dm_comment,
            "trend": tr_comment,
            "activity": ac_comment,
        },
        "fund": (
            {
                "main_net_yi": round((fund.get("main_net") or 0) / 1e8, 3),
                "main_pct": round(fund["main_pct"], 2) if fund.get("main_pct") is not None else None,
                "super_net_yi": round((fund.get("super_net") or 0) / 1e8, 3)
                if fund.get("super_net") is not None
                else None,
                "rank": fund.get("rank"),
            }
            if fund
            else None
        ),
        "metrics": {
            "pct_from_high": round(metrics["pct_from_high"], 2),
            "ma5": round(metrics["ma5"], 2),
            "ma20": round(metrics["ma20"], 2),
            "ma60": round(metrics["ma60"], 2),
            "ma20_slope": round(metrics["ma20_slope"], 2),
            "r20": round(metrics["r20"], 2),
        },
        "levels": levels,
        "expected_price": expected,
        "tags": tags,
    }


# ---------------- 板块强度 / 主力抱团 / 潜力龙头 ----------------


def _sector_strength(fund_rows: list[dict], limitup_snapshot: dict | None) -> tuple[list[dict], bool]:
    """板块强度（多维）：资金 + 动量 + 广度，情绪层叠加涨停池聚集度。

    全部用**当日横截面分位**合成，理由见 `_pct_rank`。
    返回 (板块列表, 行业字段是否可用)。
    """
    groups: dict[str, list[dict]] = {}
    with_sector = 0
    for r in fund_rows:
        sec = r.get("sector")
        if not sec:
            continue
        with_sector += 1
        groups.setdefault(sec, []).append(r)
    available = bool(fund_rows) and with_sector / len(fund_rows) >= 0.5

    # 涨停池板块统计（情绪层）：hybk 与 f100 同属东财行业口径
    lu_by_sector: dict[str, dict] = {}
    if limitup_snapshot:
        for s in limitup_snapshot.get("sectors") or []:
            lu_by_sector[s.get("sector")] = s

    rows: list[dict] = []
    for sec, members in groups.items():
        if len(members) < 2:      # 单只样本不构成"板块"
            continue
        net = sum((m.get("main_net") or 0) for m in members) / 1e8
        changes = [m.get("change_pct") for m in members if m.get("change_pct") is not None]
        up = sum(1 for c in changes if c > 0)
        lu = lu_by_sector.get(sec) or {}
        rows.append(
            {
                "sector": sec,
                "member_count": len(members),
                "up_count": up,
                "avg_change_pct": round(sum(changes) / len(changes), 2) if changes else None,
                "net_inflow_yi": round(net, 2),
                "limitup_count": int(lu.get("count") or 0),
                "max_boards": int(lu.get("max_boards") or 0),
                "seal_fund_yi": lu.get("seal_fund_yi"),
            }
        )

    if not rows:
        return [], available

    inflow_vals = [r["net_inflow_yi"] for r in rows]
    mom_vals = [r["avg_change_pct"] if r["avg_change_pct"] is not None else 0.0 for r in rows]
    breadth_vals = [r["up_count"] / r["member_count"] for r in rows]
    lu_vals = [float(r["limitup_count"]) for r in rows]

    for r in rows:
        money = _pct_rank(inflow_vals, r["net_inflow_yi"])
        momentum = _pct_rank(mom_vals, r["avg_change_pct"] if r["avg_change_pct"] is not None else 0.0)
        breadth = _pct_rank(breadth_vals, r["up_count"] / r["member_count"])
        sentiment = _pct_rank(lu_vals, float(r["limitup_count"]))
        # 情绪层只在有涨停时参与，否则会用一个恒为 0.5 的分位把分数拉平
        if any(v > 0 for v in lu_vals):
            score = 10 * (0.34 * money + 0.28 * momentum + 0.20 * breadth + 0.18 * sentiment)
        else:
            score = 10 * (0.45 * money + 0.33 * momentum + 0.22 * breadth)
        r["strength_score"] = round(score, 1)
        r["dims"] = {
            "money": round(money * 10, 1),
            "momentum": round(momentum * 10, 1),
            "breadth": round(breadth * 10, 1),
            "sentiment": round(sentiment * 10, 1),
        }
        tags = []
        if money >= 0.8 and r["limitup_count"] >= 2:
            tags.append("资金+情绪共振")
        elif money >= 0.8:
            tags.append("资金流入")
        elif r["limitup_count"] >= 3:
            tags.append("情绪聚集")
        if momentum >= 0.85 and breadth >= 0.6:
            tags.append("量价扩散")
        r["tags"] = tags

    rows.sort(key=lambda x: (x["strength_score"], x["net_inflow_yi"]), reverse=True)
    return rows[:SECTOR_SIZE], available


def _herding(sectors: list[dict], limitup_snapshot: dict | None) -> dict:
    """主力抱团：板块层面的资金与情绪是否集中。

    两个可观测代理：
      ① 涨停池板块集中度（top3 板块涨停家数 / 总涨停家数）—— 抱团的**结果**
      ② 板块资金净流入占正流入板块的比例（top3 / 全部正流入）—— 抱团的**动作**
    二者都只是代理：真正的「抱团」要看席位与持仓，本项目拿不到。
    """
    sentiment = (limitup_snapshot or {}).get("sentiment") or {}
    total_lu = len((limitup_snapshot or {}).get("stocks") or [])
    lu_sectors = sorted(
        [s for s in (limitup_snapshot or {}).get("sectors") or []],
        key=lambda x: x.get("count") or 0,
        reverse=True,
    )
    top3_lu = sum(int(s.get("count") or 0) for s in lu_sectors[:3])
    concentration = (top3_lu / total_lu) if total_lu else None

    positive = [s for s in sectors if (s.get("net_inflow_yi") or 0) > 0]
    top3_money = sum((s.get("net_inflow_yi") or 0) for s in sorted(
        positive, key=lambda x: x.get("net_inflow_yi") or 0, reverse=True
    )[:3])
    all_money = sum((s.get("net_inflow_yi") or 0) for s in positive)
    money_share = (top3_money / all_money) if all_money > 0 else None

    if concentration is None and money_share is None:
        return {
            "level": "unknown",
            "score": None,
            "note": "涨停池与板块资金均不可用，本次无法判定抱团程度。",
            "top_sectors": lu_sectors[:3],
        }

    parts = [x for x in (concentration, money_share) if x is not None]
    agg = sum(parts) / len(parts)
    score = round(_clamp(agg * 13.5), 1)   # 经验缩放：集中度 0.6 左右约得 8 分
    if score >= 7:
        level = "high"
    elif score >= 4:
        level = "mid"
    else:
        level = "low"

    note_bits = []
    if concentration is not None:
        note_bits.append(f"前 3 板块占涨停 {concentration * 100:.0f}%（涨停共 {total_lu} 家）")
    if money_share is not None:
        note_bits.append(f"前 3 板块占净流入 {money_share * 100:.0f}%")
    if level == "high":
        note_bits.append("资金与情绪同时向少数板块集中 —— 抱团特征明显")
    elif level == "low":
        note_bits.append("资金与情绪均分散 —— 无明确抱团主线")
    else:
        note_bits.append("集中度中等")

    return {
        "level": level,
        "score": score,
        "concentration": round(concentration, 3) if concentration is not None else None,
        "money_share": round(money_share, 3) if money_share is not None else None,
        "limitup_total": total_lu,
        "sentiment_tone": sentiment.get("tone"),
        "note": "；".join(note_bits),
        "top_sectors": [
            {
                "sector": s.get("sector"),
                "limitup_count": int(s.get("count") or 0),
                "max_boards": int(s.get("max_boards") or 0),
                "net_inflow_yi": next(
                    (x.get("net_inflow_yi") for x in sectors if x.get("sector") == s.get("sector")), None
                ),
            }
            for s in lu_sectors[:5]
        ],
    }


def _leaders(items: list[dict], strong_sectors: set[str], limit: int = LEADER_SIZE) -> list[dict]:
    """潜力龙头：资金已进场、趋势成立、还没被拉到买不进的候选。

    刻意**排除当日接近涨停**的（涨幅 ≥ 9%）——那类标的大概率一字或秒板，
    列出来只会导向一个买不进的价格（打板口径的教训：收益大头落在买不进的档）。
    """
    out: list[dict] = []
    for it in items:
        dm = it["scores"].get("dark_money")
        tr = it["scores"].get("trend")
        if dm is None or tr is None:
            continue
        if dm < LEADER_MIN_DARK_MONEY or tr < LEADER_MIN_TREND:
            continue
        if it["change_pct"] >= LEADER_MAX_CHANGE_PCT:
            continue
        pfh = (it.get("metrics") or {}).get("pct_from_high", -99)
        if pfh < LEADER_MIN_PCT_FROM_HIGH:      # 距高点太远，谈不上"龙头"
            continue
        reasons = []
        fund = it.get("fund") or {}
        if fund.get("main_pct") is not None:
            reasons.append(f"主力净占比 {fund['main_pct']:.1f}%")
        if it.get("sector") in strong_sectors:
            reasons.append(f"{it['sector']} 属强势板块")
        if it["scores"]["trend"] >= 8:
            reasons.append("趋势结构明确")
        if it.get("turnover") is not None:
            reasons.append(f"换手 {it['turnover']:.1f}% 活跃")
        out.append(
            {
                "code": it["code"],
                "name": it["name"],
                "price": it["price"],
                "change_pct": it["change_pct"],
                "sector": it.get("sector"),
                "overall_score": it["overall_score"],
                "dark_money": dm,
                "trend": tr,
                "pct_from_high": pfh,
                "main_pct": fund.get("main_pct"),
                "reason": " · ".join(reasons) or "资金与趋势双达标",
            }
        )
    out.sort(key=lambda x: (x["dark_money"], x["overall_score"]), reverse=True)
    return out[:limit]


# ---------------- 榜单生成 ----------------

_VANGUARD_EVIDENCE_KEY = "vanguard_three_dim"


def _evidence_block() -> dict:
    ev = tactic_evidence.describe(_VANGUARD_EVIDENCE_KEY)
    return ev


def _timing_block() -> dict:
    """买卖时机的证据说明：复用 monitor_levels（买入侧实测为负）。"""
    ev = tactic_evidence.describe("monitor_levels")
    return {
        "evidence": ev,
        "note": (
            "支撑 / 压力 / 止损取自定义结构位（MA、布林、斐波那契、区间高低点），"
            "买卖点直接锚定主支撑与主压力，**不随现价漂移**。"
            "但按实测：买入侧（回踩可买）超额为负、与随机不可区分 —— "
            "所以这里是**价位结构参考**，不是买入指令。"
        ),
    }


async def generate_board(force_refresh: bool = False) -> dict:
    """生成决策先锋三维榜（每日懒生成 + DB 快照缓存）。"""
    today = await trade_calendar_service.last_trading_day()
    data_day = str(today)

    if not force_refresh:
        hit = await _load_db_board(data_day)
        if hit:
            return hit

    # refresh 穿透底层快照（选项 C：刷新按钮穿透到底层）。
    # force_refresh=True 时跳过两层行情缓存直拉全市场快照；冷却/节流由 _get_spot 内部守卫，
    # 触发风控时抛 RuntimeError（被路由转成 502 + 冷却文案）。前端 spotGuard 也会先二次确认 + 拦截冷却。
    spot = await quad_service.get_full_spot(force=force_refresh)
    if not spot:
        raise RuntimeError("获取全市场行情失败")

    fund = await _load_fund_flow(force=force_refresh)
    fund_rows = fund.get("rows") or []
    fund_available = fund.get("status") in ("ok", "cached") and bool(fund_rows)
    fund_by_code = {r["code"]: r for r in fund_rows if r.get("code")}

    wide_pool = _preselect(spot, fund_by_code, top_n=WIDE_POOL_TOP_N)
    if not wide_pool:
        raise RuntimeError("三维候选池为空（今日全市场无符合硬过滤条件的标的）")
    # 宽池（廉价预筛，无 K 线）只供浏览；精算只在「窄池」前 POOL_TOP_N 只上发生，
    # 因此 K 线请求数锁死在 POOL_TOP_N —— 调大宽池不会放大 IP 封禁风险。
    pool = wide_pool[:POOL_TOP_N]

    scored = await concurrency.gather_limited(
        (
            _score_one(r, fund_by_code.get(r["code"]), fund_available)
            for r in pool
        ),
        return_exceptions=True,
    )
    items = [x for x in scored if isinstance(x, dict)]
    if not items:
        raise RuntimeError("候选股票三维评分失败（K 线全部不可用）")

    # 板块强度（用已加载的资金批次 + 涨停池快照，均为既有数据/最佳努力，无新增逐股请求）
    snapshot: dict | None = None
    try:
        snapshot = await limitup_service.get_snapshot()
    except Exception as e:
        print(f"[vanguard] 涨停池不可用，板块情绪层降级: {e}")

    sectors, sector_field_available = _sector_strength(fund_rows, snapshot)
    strength_by_sector = {s["sector"]: s["strength_score"] for s in sectors}
    strong_sectors = {s["sector"] for s in sectors[:5]}

    # 市场状态（从已有全市场快照免费计算，无新增请求）：宽度分偏低 = 偏弱市，
    # 对高活跃度（高 beta 动量）标的降权，避免在退潮日追高。
    breadth_score = _breadth_score_from_spot(spot)

    # 给每个精算项挂板块强度 + 主线标签，并算 selection_score（选股用，不改三维分含义）
    for it in items:
        sec = it.get("sector")
        it["sector_strength"] = strength_by_sector.get(sec) if sector_field_available else None
        is_mainline = bool(sec) and sec in strong_sectors
        it["selection_score"] = _selection_score(it, it["sector_strength"], is_mainline, breadth_score)
        if is_mainline and "主线" not in it["tags"]:
            it["tags"] = [*it["tags"], "主线"]

    # 排名以 selection_score 为主、三维综合分兜底；这样板块/主线/状态信号
    # 能影响谁能上榜，但用户看到的「三维分」仍是纯粹的当日读数。
    items.sort(key=lambda x: (x.get("selection_score") or 0, x["overall_score"]), reverse=True)
    top = items[:BOARD_SIZE]
    for i, item in enumerate(top):
        item["rank"] = i + 1

    leaders = _leaders(items, strong_sectors)
    herding = _herding(sectors, snapshot)

    weights_note = (
        "三维加权：资金 0.40 / 趋势 0.35 / 活跃度 0.25"
        if fund_available
        else "资金维不可用，权重已重新归一化到 趋势 / 活跃度（缺失维不计 0 分）"
    )
    headline = (
        f"宽池 {len(wide_pool)} 只（廉价预筛）→ 精算 {len(items)} 只（K线）→ 上榜 {len(top)} 只；"
        f"资金维{'可用' if fund_available else '不可用'}（{fund.get('status')}）。"
        "三维分是当日读数，不是买入信号。"
    )

    # 宽池视图（廉价，无 K 线）：供前端「宽池候选」浏览/筛选。被精算命中的票带三维分与板块强度。
    scored_map = {it["code"]: it for it in items}
    wide_pool_view: list[dict] = []
    for r in wide_pool:
        code = r.get("code") or ""
        fr = fund_by_code.get(code) or {}
        sc = scored_map.get(code)
        wide_pool_view.append(
            {
                "code": code,
                "name": r.get("name") or "",
                "price": round(r.get("price") or 0, 2),
                "change_pct": round(r.get("change_pct") or 0, 2),
                "amount_yi": round(r.get("amount_yi") or 0, 2),
                "turnover": round(r["turnover"], 2) if r.get("turnover") is not None else None,
                "volume_ratio": round(r["volume_ratio"], 2) if r.get("volume_ratio") is not None else None,
                "sector": fr.get("sector") or None,
                "main_pct": round(fr["main_pct"], 2) if fr.get("main_pct") is not None else None,
                "pre_score": round(r.get("_pre_score") or 0, 2),
                "scored": code in scored_map,
                "overall_score": sc.get("overall_score") if sc else None,
                "sector_strength": sc.get("sector_strength") if sc else None,
                "selection_score": sc.get("selection_score") if sc else None,
            }
        )

    result = {
        "date": data_day,
        "source": "rule",
        "generated_at": trade_calendar_service.now_cn().isoformat(timespec="seconds"),
        "pool_size": len(pool),
        "scored_size": len(items),
        "wide_pool_size": len(wide_pool_view),
        "evidence": _evidence_block(),
        "dims": [
            {"key": "dark_money", "label": "暗盘资金", "desc": "主力净流入（超大单+大单）口径，非真实暗盘数据"},
            {"key": "trend", "label": "趋势", "desc": "均线排列 · MA20 斜率 · 距 250 日高点 · MACD"},
            {"key": "activity", "label": "活跃度", "desc": "按市值分层的换手 / 量比 / 成交额 / 振幅"},
        ],
        "weights_note": weights_note,
        "fund_flow": {
            "status": fund.get("status"),
            "covered": len(fund_rows),
            "note": fund.get("note"),
            "source": "东财 clist 批量资金流排行（fid=f62，非逐股请求）",
        },
        "sector_field_available": sector_field_available,
        "headline": headline,
        "timing": _timing_block(),
        "items": top,
        "sectors": sectors,
        "herding": herding,
        "leaders": leaders,
        "wide_pool": wide_pool_view,
        "market_state": {"breadth_score": breadth_score},
        # 资金快照映射：供「诊股」在冷实例上也能拿到资金维，而不必再打一次端点
        "fund_map": _fund_map(fund_rows),
    }

    await _save_db_board(data_day, result)
    put_bounded(_board_cache, data_day, (data_day, result), max_entries=_BOARD_CACHE_MAX)
    return result


async def get_board(force_refresh: bool = False) -> dict:
    """入口：优先内存 → DB → 懒生成。"""
    today = await trade_calendar_service.last_trading_day()
    key = str(today)
    if not force_refresh:
        cached = _board_cache.get(key)
        if cached:
            return cached[1]
    return await generate_board(force_refresh=force_refresh)


async def diagnose(code: str) -> dict:
    """诊股：单只票的三维体检 + 结构位 + 所属板块强度。

    与「深度分析」（LLM 多角色辩论）**刻意分工**：这里只给量化读数，
    不做结论、不做多空判断 —— 两者都叫"诊股"会让人分不清看哪个。

    优先用榜单快照里的现成结果（零请求）；不在榜内才现场算（2 次请求）。
    """
    code = (code or "").strip()
    if not code:
        raise ValueError("缺少股票代码")

    board: dict | None = None
    try:
        board = await get_board()
    except Exception as e:
        print(f"[vanguard] 诊股时榜单不可用（降级为现场计算）: {e}")

    if board:
        for item in board.get("items") or []:
            if item.get("code") == code:
                return {
                    "code": code,
                    "in_board": True,
                    "rank": item.get("rank"),
                    "item": item,
                    "sector": _sector_of(board, item.get("sector")),
                    "evidence": board.get("evidence"),
                    "timing": board.get("timing"),
                    "date": board.get("date"),
                }

    # --- 不在榜内：现场计算（受并发闸门约束的 2 次请求）---
    quotes = await asyncio.to_thread(data_service.get_spot_quote, [code])
    quote = quotes[0] if quotes else None
    if quote is None:
        raise RuntimeError("未取到该股实时行情（代码可能有误或行情源不可用）")

    # 资金维数据源（按优先级）：榜单快照里的资金映射 → 本进程资金批次缓存。
    # 两者都没有时才回落到「整批可用但该股不在两端」的中性处理。
    fund_row = None
    fund_available = False
    if board:
        fm = (board.get("fund_map") or {}).get(code)
        if fm:
            fund_row, fund_available = _fund_map_entry_to_row(code, quote.name or "", fm), True
    if fund_row is None and _fund_cache:
        fund_row = {r["code"]: r for r in _fund_cache[1] if r.get("code")}.get(code)
        fund_available = fund_row is not None
    if fund_row is None and _fund_is_globally_available(board):
        fund_available = True

    hist = await asyncio.to_thread(data_service.get_history, code, KLINE_DAYS)
    closes = list(hist.closes) if hist and hist.closes else []
    highs = list(hist.highs) if hist and hist.highs else []
    lows = list(hist.lows) if hist and hist.lows else []
    price = quote.price or (closes[-1] if closes else 0)
    # 与 _score_one 同理：不覆盖 closes[-1]（见那里的说明）。

    # ⚠️ `StockQuote` **没有成交额字段**（只有 volume）。因此单票现场计算时成交额只能
    # 来自资金流批次（f6）；两条路都拿不到就置 None，由 _score_activity 按「未观测」处理。
    amount_yi = None
    if fund_row and fund_row.get("amount"):
        amount_yi = fund_row["amount"] / 1e8

    rich = {
        "code": code,
        "name": quote.name or "",
        "price": price,
        "change_pct": quote.change_pct or 0,
        "amount_yi": amount_yi,
        "turnover": quote.turnover,
        "volume_ratio": getattr(quote, "volume_ratio", None),
        "market_cap_yi": (quote.market_cap / 1e8) if quote.market_cap else None,
        "change_5min": None,
    }

    metrics = _trend_metrics(closes, highs, lows, price)
    dm_score, dm_comment = _score_dark_money(fund_row, rich, fund_available)
    tr_score, tr_comment = _score_trend(metrics, price)
    ac_score, ac_comment = _score_activity(rich, metrics)
    scores: dict[str, float | None] = {"dark_money": dm_score, "trend": tr_score, "activity": ac_score}
    overall, weights_used = _composite(scores)
    levels = signal_service.compute_signals(closes, price, highs, lows)
    expected = signal_service.expected_price_from_levels(price, levels, "auto")
    sector_name = (fund_row or {}).get("sector")

    return {
        "code": code,
        "in_board": False,
        "rank": None,
        "item": {
            "code": code,
            "name": quote.name or "",
            "price": round(price, 2),
            "change_pct": round(quote.change_pct or 0, 2),
            "turnover": quote.turnover,
            "volume_ratio": rich["volume_ratio"],
            "amount_yi": round(rich["amount_yi"], 2),
            "market_cap_yi": rich["market_cap_yi"],
            "sector": sector_name,
            "overall_score": overall,
            "weights_used": weights_used,
            "scores": scores,
            "comments": {"dark_money": dm_comment, "trend": tr_comment, "activity": ac_comment},
            "fund": (
                {
                    "main_net_yi": round((fund_row.get("main_net") or 0) / 1e8, 3),
                    "main_pct": fund_row.get("main_pct"),
                    "super_net_yi": round((fund_row.get("super_net") or 0) / 1e8, 3)
                    if fund_row.get("super_net") is not None
                    else None,
                    "rank": fund_row.get("rank"),
                }
                if fund_row
                else None
            ),
            "metrics": (
                {
                    "pct_from_high": round(metrics["pct_from_high"], 2),
                    "ma5": round(metrics["ma5"], 2),
                    "ma20": round(metrics["ma20"], 2),
                    "ma60": round(metrics["ma60"], 2),
                    "ma20_slope": round(metrics["ma20_slope"], 2),
                    "r20": round(metrics["r20"], 2),
                }
                if metrics
                else None
            ),
            "levels": levels,
            "expected_price": expected,
            "tags": [],
        },
        "sector": _sector_of(board, sector_name),
        "evidence": _evidence_block() if not board else board.get("evidence"),
        "timing": _timing_block() if not board else board.get("timing"),
        "date": (board or {}).get("date"),
        "note": None if board else "榜单不可用，本结果为现场单票计算（无板块强度与抱团层）",
    }


def _fund_map_entry_to_row(code: str, name: str, entry: list) -> dict:
    """持久化的紧凑资金映射 → 与批次行同形的 dict（供诊股复用打分函数）。"""
    net_yi, pct, super_yi, sector = (list(entry) + [None, None, None, None])[:4]
    return {
        "code": code,
        "name": name,
        "main_net": (net_yi * 1e8) if net_yi is not None else None,
        "main_pct": pct,
        "super_net": (super_yi * 1e8) if super_yi is not None else None,
        "sector": sector,
        "rank": None,
    }


def _fund_is_globally_available(board: dict | None) -> bool:
    """资金批次整体是否可用（决定「不在批次内」该判中性还是判缺失）。"""
    if board:
        return (board.get("fund_flow") or {}).get("status") in ("ok", "cached")
    if _fund_cache:
        return True
    return False


def _sector_of(board: dict | None, sector_name: str | None) -> dict | None:
    if not board or not sector_name:
        return None
    for s in board.get("sectors") or []:
        if s.get("sector") == sector_name:
            return s
    return None


# ---------------- DB 快照（与 quad_service 同模式） ----------------


async def _load_db_board(data_day: str) -> dict | None:
    if not supabase_store.is_configured():
        return None
    try:
        sb = await supabase_store.get_service_client()
        res = (
            await sb.table("vanguard_snapshots")
            .select("result")
            .eq("snapshot_date", data_day)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0]["result"]
    except Exception as e:
        print(f"[vanguard] DB 读取失败: {e}")
    return None


async def _save_db_board(data_day: str, result: dict) -> None:
    if not supabase_store.is_configured():
        return
    try:
        sb = await supabase_store.get_service_client()
        existing = (
            await sb.table("vanguard_snapshots")
            .select("id")
            .eq("snapshot_date", data_day)
            .limit(1)
            .execute()
        )
        payload = {"snapshot_date": data_day, "result": result}
        if existing.data:
            await sb.table("vanguard_snapshots").update(payload).eq("id", existing.data[0]["id"]).execute()
        else:
            await sb.table("vanguard_snapshots").insert(payload).execute()
    except Exception as e:
        print(f"[vanguard] DB 保存失败: {e}")
