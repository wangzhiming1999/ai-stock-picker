"""暗盘资金 G/S 信号（中小单代理 · 明暗背离形态）。

## 它回答什么

「今天有没有票出现**明暗背离** —— 明盘（超大单+大单）方向与中单方向相反」，
并按形态标注 ``G``（拆单吸筹嫌疑）/ ``S``（拉高派发嫌疑）。

## 口径（这是本模块的全部可信度来源，不得省略）

* **明盘** = 东财「主力」= 超大单 + 大单净额（``f62``，与 vanguard 资金维同口径）。
* **暗盘代理** = 中单净流入（``f78``）。小单（``f84``）随行下发但**不参与判定** ——
  小单以真散户为主，噪声更大。
* ⚠️ 中单是**「散户 + 拆单主力」的混合体**，公开数据（含 L2 逐笔）无账户维度，
  无法做真正的拆单归集。本模块只认「方向相反」这一形态，**不产出拆单金额估算**。
* **G/S 是启发式规则**（阈值未回测校准），且**恒定 ``status=unsupported``** ——
  未定义收益口径前不给买卖动作（全站红线），前端必须渲染成「未验证形态」。

## G/S 规则（启发式，单日横截面）

| 信号 | 明盘（主力净额） | 中单净额  | 当日涨幅        | 读法                             |
|------|------------------|-----------|-----------------|----------------------------------|
| G    | 流出 (< 0)       | 流入 (> 0)| −5% ~ 3%        | 明出暗进 + 未拉高 → 拆单吸筹嫌疑 |
| S    | 流入 (> 0)       | 流出 (< 0)| ≥ 3%            | 明进暗出 + 已拉高 → 拉高派发嫌疑 |

G 的涨幅带是**双向**的：深跌日（< −5%）中单流入以散户抄底为主，「吸筹嫌疑」的解读
不成立（实测 −14% 的票会被误标 G），宁可漏判不误判。

另有噪声闸门：``|中单净额 / 成交额| ≥ 2%`` 才出信号（成交额为 0/缺失的行不判）。

## 持续性（自积累快照，不打个股时序接口）

「连续 N 个交易日同一形态」需要时序，而个股资金流时序接口（``fflow/daykline``）逐只
请求必触发风控。正解是**自积累**：每日收盘形态落 ``dark_flow_daily_snapshot``（v21），
连续性从本表自己的历史里数（按有快照的交易日计）。首日/表未建时降级单日读数并**显式标注**。
streak 仍是结构读数 —— 「越连续」**不等于**「越会涨」，恒定 ``unsupported`` 不变。

## 取数与缓存

复用 ``spot_service.fetch_fund_flow_rows``（东财 clist 批量端点，一次覆盖数百只）：

* 明暗背离的票**必然**在主力净额两端之一（G 在流出侧、S 在流入侧），
  所以拉 f62 两端榜即可覆盖全部候选，不必再按 f78 排序拉两轮。
* 缓存 / force 节流 / 失败冷却与 ``vanguard_service._load_fund_flow`` 同哲学：
  force 节流锚点是**上一次真实取数**（``_last_live_at``），不是上一次 force ——
  否则「普通取数 → 紧跟 force」会直接绕过限流（vanguard 的实测坑）。
"""
from __future__ import annotations

import asyncio
import datetime as dt
import statistics
import time

from app.services import calibers, spot_service, supabase_store, trade_calendar_service

# ── 与 vanguard_service._load_fund_flow 同一套参数哲学 ──────────────────
_TTL = 600                 # 横截面是慢变量，10 分钟够用
_FAIL_COOLDOWN = 180       # 端点失败后的实例冷却（同源东财 push2，重试只会延长封禁）
_FORCE_MIN_INTERVAL = 60   # force 穿透的最小间隔（防连点）

# ── G/S 判定阈值（启发式，未回测校准 —— 调整必须同步改 CAVEATS 文案）──
_MID_MIN_PCT_OF_AMOUNT = 2.0   # 中单净额占成交额最小比例（%），低于此视为噪声
_G_MIN_CHANGE_PCT = -5.0       # G：当日涨幅下限 —— 深跌日中单流入以散户抄底为主，
                               # 「吸筹嫌疑」的解读不成立（实测 -14% 的票会被误标 G），宁可漏判
_G_MAX_CHANGE_PCT = 3.0        # G：当日涨幅上限（还没拉高）
_S_MIN_CHANGE_PCT = 3.0        # S：当日涨幅下限（已经拉高）
_SIDE_SIZE = 10                # 每侧展示条数

# 与 sector_flow_service.CAVEATS 同角色：随接口下发，前端必须渲染。
CAVEATS = [
    "暗盘代理口径：中单（f78）是「散户 + 拆单主力」的混合体，公开数据无账户维度、拆不开，不是真实暗盘成交。",
    "G/S 是「明暗背离」形态识别（明盘大单与中单方向相反），不是拆单金额估算。",
    "阈值为启发式、未回测校准；未定义收益口径，G/S 恒为 unsupported，不是买卖建议。",
    "持续性（streak）按自积累快照（v21 起）的连续交易日同一形态计数，不是个股资金流时序；"
    "历史样本不足时降级单日读数并标注 —— 「越连续」不等于「越会涨」，仍是结构读数。",
]

# 快照保留窗口：与涨停/跌停池同哲学 —— 只写不删会撞 Supabase 免费额度，
# 而写路径失败是静默的（save_daily_snapshot 捕获异常后返回 0），清理是前提。
_SNAPSHOT_RETENTION_DAYS = 90
_SNAPSHOT_MIN_RETENTION_DAYS = 30

_cache: tuple[float, dict] | None = None  # (写入时刻 monotonic, 载荷)
_failed_at: float | None = None
_last_live_at: float | None = None


def _mid_pct(row: dict) -> float | None:
    """中单净额占成交额比例（%）。分母缺失/为 0 时返回 None（不判信号）。"""
    mid = row.get("mid_net")
    amount = row.get("amount")
    if mid is None or not amount:
        return None
    return mid / amount * 100.0


def _classify(row: dict) -> dict | None:
    """单行 → G/S 信号条目，或 None（不构成背离形态）。

    信号条目只带读数字段；``actionable`` / ``status`` 由装配层统一钉死，
    不从规则里来 —— 防止未来加规则时漏标 unsupported。
    """
    main = row.get("main_net")
    mid = row.get("mid_net")
    chg = row.get("change_pct")
    if main is None or mid is None or chg is None:
        return None

    pct = _mid_pct(row)
    if pct is None or abs(pct) < _MID_MIN_PCT_OF_AMOUNT:
        return None

    signal: str | None = None
    reason: str | None = None
    if main < 0 < mid and _G_MIN_CHANGE_PCT <= chg <= _G_MAX_CHANGE_PCT:
        signal = "G"
        reason = (
            f"明盘净流出 {main / 1e8:.2f}亿 + 中单净流入 {mid / 1e8:.2f}亿"
            f"（占成交额 {pct:.1f}%），涨幅 {chg:.1f}% 未拉高 —— 拆单吸筹嫌疑"
        )
    elif main > 0 > mid and chg >= _S_MIN_CHANGE_PCT:
        signal = "S"
        reason = (
            f"明盘净流入 {main / 1e8:.2f}亿 + 中单净流出 {mid / 1e8:.2f}亿"
            f"（占成交额 {pct:.1f}%），涨幅 {chg:.1f}% 已拉高 —— 拉高派发嫌疑"
        )
    else:
        return None

    return {
        "code": row.get("code"),
        "name": row.get("name"),
        "price": row.get("price"),
        "change_pct": chg,
        "sector": row.get("sector"),
        "main_net": main,
        "mid_net": mid,
        "small_net": row.get("small_net"),
        "amount": row.get("amount"),
        "mid_pct": round(pct, 2),
        "signal": signal,
        "reason": reason,
    }


def _empty_payload(status: str, note: str, fetched_at: float | None = None) -> dict:
    return {
        "status": status,
        "available": False,
        "signal_status": "unsupported",
        "actionable": False,
        "note": note,
        "caliber": "中小单代理（明暗背离形态）",
        "caveats": list(CAVEATS),
        "g_items": [],
        "s_items": [],
        "all_signals": [],
        "counts": {"g": 0, "s": 0, "scanned": 0},
        "persistence": {
            "available": False,
            "note": "本次未取到形态，无持续性读数",
            "sample_days": 0,
            "streak_stats": None,
            "four_questions": None,
            "four_questions_absent_reason": "本次未取到形态，无持续性分布可判",
        },
        "fetched_at": fetched_at,
    }


def _build_payload(rows: list[dict], note: str, fetched_at: float | None) -> dict:
    g_items: list[dict] = []
    s_items: list[dict] = []
    for row in rows:
        item = _classify(row)
        if not item:
            continue
        (g_items if item["signal"] == "G" else s_items).append(item)

    # 金额大的那批才有信息量（与 vanguard._fund_map 同哲学）；金额相同再按占比稳序。
    g_items.sort(key=lambda r: (r["mid_net"] or 0), reverse=True)
    s_items.sort(key=lambda r: (r["mid_net"] or 0))
    # all_signals 是**未截断**全集（落库 + 持续性用）：展示榜截断会把「昨日 G 第 15 名、
    # 今日 G 第 3 名」这种连续误判成断档 —— 样本必须记全，展示才截断。
    all_signals = g_items + s_items
    g_items = g_items[:_SIDE_SIZE]
    s_items = s_items[:_SIDE_SIZE]

    return {
        "status": "ok",
        "available": True,
        # ⚠️ 红线：未定义收益口径前不给买卖动作。这两个字段恒定钉死，
        # 前端据「signal_status=unsupported」渲染未验证形态，不得渲染成买卖建议。
        "signal_status": "unsupported",
        "actionable": False,
        "note": note,
        "caliber": "中小单代理（明暗背离形态）",
        "caveats": list(CAVEATS),
        "g_items": g_items,
        "s_items": s_items,
        "all_signals": all_signals,
        # counts 数**全集**（截断只属展示）：把展示上限当形态计数会低估形态出现频次。
        "counts": {
            "g": sum(1 for item in all_signals if item["signal"] == "G"),
            "s": sum(1 for item in all_signals if item["signal"] == "S"),
            "scanned": len(rows),
        },
        "fetched_at": fetched_at,
    }


async def get_signals(force: bool = False) -> dict:
    """暗盘资金 G/S 信号载荷（结构完整，取数失败也带 caveats 降级返回）。

    status:
      * ``ok``        本次真拉成功
      * ``cached``    命中内存缓存（含 force 节流窗口内的「返回上次结果」）
      * ``cooldown``  行情源共享冷却期，本次跳过（不视为失败、不延长冷却）
      * ``unavailable`` 拉取失败（本模块已进入冷却）
    """
    global _cache, _failed_at, _last_live_at
    now = time.monotonic()

    if _cache and now - _cache[0] < _TTL:
        if not force:
            return {**_cache[1], "status": "cached"}
        if _last_live_at is not None and now - _last_live_at < _FORCE_MIN_INTERVAL:
            return {
                **_cache[1],
                "status": "cached",
                "note": "刷新间隔过短，返回上次结果",
            }

    if _failed_at is not None and now - _failed_at < _FAIL_COOLDOWN:
        remaining = int(_FAIL_COOLDOWN - (now - _failed_at))
        if _cache:
            return {
                **_cache[1],
                "status": "unavailable",
                "available": True,
                "note": f"资金流端点冷却中（{remaining}s），返回上次结果",
            }
        return _empty_payload("unavailable", f"资金流端点冷却中（{remaining}s）")

    # 与全市场快照同一批东财域名：共享冷却期内撞端点只会延长封禁（vanguard 同款守卫）。
    # 函数内延迟导入避免 market ↔ 本模块的循环导入。
    from app.routes import market as market_routes

    cooling = await market_routes.spot_cooldown_seconds()
    if cooling > 0:
        if _cache:
            return {
                **_cache[1],
                "status": "cooldown",
                "available": True,
                "note": f"行情源被风控，冷却中（{int(cooling)}s），返回上次结果",
            }
        return _empty_payload("cooldown", f"行情源被风控，冷却中（{int(cooling)}s）")

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
        _failed_at = now
        return _empty_payload(
            "unavailable",
            f"资金流端点不可用（流入侧 {type(inflow).__name__} / 流出侧 {type(outflow).__name__}）",
        )

    rows = list(merged.values())
    note = "两侧批量榜已合并（G 候选出自流出侧、S 候选出自流入侧）"
    payload = _build_payload(rows, note, fetched_at=now)
    if ok_sides < 2:
        payload["note"] = f"{note}；仅 {ok_sides}/2 侧取到数据"
    await _attach_persistence(payload)
    _cache = (now, payload)
    _last_live_at = now
    _failed_at = None
    return payload


def clear_caches() -> None:
    """测试隔离用。"""
    global _cache, _failed_at, _last_live_at
    _cache = None
    _failed_at = None
    _last_live_at = None


# ── 持续性（自积累快照，纯函数可测）──────────────────────────────────


def compute_streaks(
    history_rows: list[dict],
    today: str,
    today_signals: dict[str, str],
) -> dict:
    """从自积累快照行算连续性 —— 不打任何外部接口（风控红线）。

    * ``current``   今日各码的连续同形态天数（含今日；今日不在历史里就是 1）。
    * ``episodes``  历史「连续段」长度分布（含今日结尾段）—— 持续性分布的四问样本。
    * ``sample_days`` 有快照数据的交易日数（历史积累量）。

    连续性按**有快照的交易日**序列数：周末/节假日/缺采日天然不在序列里，
    「当日无信号」（形态未出现）才会把连续段断开。缺表/无历史 → 全部降级单日
    （current=1、episodes 空），由调用方**显式标注**，不静默假装「连续 1 天」。
    """
    by_code: dict[str, dict[str, str]] = {}
    history_dates: set[str] = set()
    for row in history_rows:
        day = str(row.get("signal_date") or "")[:10]
        code = str(row.get("code") or "")
        signal = row.get("signal")
        if not day or not code or signal not in ("G", "S"):
            continue
        by_code.setdefault(code, {})[day] = signal
        history_dates.add(day)

    dates = set(history_dates)
    if today:
        dates.add(today)
        for code, signal in today_signals.items():
            if signal in ("G", "S"):
                by_code.setdefault(code, {})[today] = signal
    timeline = sorted(dates)

    episodes: list[int] = []
    current: dict[str, int] = {}
    for code, day_map in by_code.items():
        run_signal: str | None = None
        run_len = 0
        for day in timeline:
            signal = day_map.get(day)
            if signal is not None and signal == run_signal:
                run_len += 1
            else:
                if run_len >= 1:
                    episodes.append(run_len)
                run_signal = signal
                run_len = 1 if signal is not None else 0
            if day == today and run_len >= 1:
                current[code] = run_len
        if run_len >= 1:
            episodes.append(run_len)
    for code in today_signals:
        current.setdefault(code, 1)

    return {
        "current": current,
        "episodes": episodes,
        "sample_days": len(history_dates),
    }


async def _load_history_rows() -> list[dict] | None:
    """整表读取持续性历史（90 天 × ≤30 行/日 ≈ 千余行，一次查询）。

    缺表（v21 未执行）/ 未配置 / 查询失败 → 返回 None，调用方降级单日并标注。
    """
    if not supabase_store.is_configured():
        return None
    try:
        sb = await supabase_store.get_service_client()
        res = await sb.table("dark_flow_daily_snapshot").select("signal_date, code, signal").execute()
        return res.data or []
    except Exception as e:
        print(f"[dark_flow] 持续性历史读取失败（缺表需执行 v21 迁移？）: {e}")
        return None


async def _attach_persistence(payload: dict) -> None:
    """把 streak / 持续性分布 / 四问守卫挂进载荷（无历史时降级单日并标注）。"""
    today = trade_calendar_service.now_cn().date().isoformat()
    signals = payload.get("all_signals") or []
    today_signals = {item["code"]: item["signal"] for item in signals if item.get("code")}
    history = await _load_history_rows()

    if history is None:
        streaks = compute_streaks([], today, today_signals)
        note = "历史样本不可用（表未建/未配置，需执行 v21 迁移）—— 降级单日读数，streak 恒为 1"
        available = False
    else:
        streaks = compute_streaks(history, today, today_signals)
        if streaks["sample_days"] == 0:
            note = "历史样本积累中（今日是首个快照日）—— 降级单日读数，streak 恒为 1"
            available = False
        else:
            note = (
                f"持续性按自积累快照的连续交易日同一形态计（已积累 {streaks['sample_days']} 个快照日）"
            )
            available = True

    for item in signals:
        item["streak"] = streaks["current"].get(item["code"], 1)

    episodes = streaks["episodes"]
    stats = None
    if episodes:
        stats = {
            "n": len(episodes),
            "median": round(statistics.median(episodes), 2),
            "mean": round(statistics.mean(episodes), 2),
        }
    # 四问只在**有历史**时出：无历史时今日单段（episode=[1]）是构造产物，
    # 拿它过「样本量」一问等于给单日读数披合格外衣。
    four = (
        calibers.four_questions_with_notes(
            {
                "sample": "样本 = 历史「连续段」（episode）个数，不是票数；每个连续段 = 同一形态在有快照交易日上的最长连续出现（含今日进行中的段）",
                "tradable": "不涉及成交（形态计数与连续天数，不是买卖读数）",
                "benchmark_sign": "持续性没有收益基准可换 —— 「越连续」不等于「越会涨」，不可读成胜率或期望收益",
            },
            n=len(episodes),
            median=stats["median"] if stats else None,
            mean=stats["mean"] if stats else None,
            tradable_ratio=None,
            benchmark_sign_flips=None,
        )
        if episodes and available
        else None
    )
    payload["persistence"] = {
        "available": available,
        "note": note,
        "sample_days": streaks["sample_days"],
        "streak_stats": stats if available else None,
        "four_questions": four,
        # 没有四问 ≠ 四问过了：缺分布样本时把原因显式下发（evidence_ledger 同纪律）
        "four_questions_absent_reason": (
            None
            if four is not None
            else "历史样本不足（表未建/未积累），持续性分布答不上来 —— 单日读数不参与分布判定"
        ),
    }


# ── 快照落库（dark_flow_daily_snapshot，v21）─────────────────────────


def _snapshot_rows(signal_date: str, items: list[dict]) -> list[dict]:
    rows = []
    for item in items:
        code = str(item.get("code") or "")
        signal = item.get("signal")
        if not code or signal not in ("G", "S"):
            continue
        rows.append({
            "signal_date": signal_date,
            "code": code,
            "name": item.get("name") or "",
            "signal": signal,
            "price": item.get("price") or 0,
            "change_pct": item.get("change_pct") or 0,
            "main_net": item.get("main_net") or 0,
            "mid_net": item.get("mid_net") or 0,
            "mid_pct": item.get("mid_pct") or 0,
            "amount": item.get("amount") or 0,
            "sector": item.get("sector") or "",
            "reason": item.get("reason") or "",
        })
    return rows


async def save_daily_snapshot(trade_date: str | None = None, payload: dict | None = None) -> int:
    """把某日 G/S 形态写入 dark_flow_daily_snapshot（upsert 幂等，覆盖为最新状态）。

    默认落**当日**：不传 payload 时现场拉一次形态。落库必须用 ``all_signals``
    （全集）而非展示截断的 g/s_items —— 持续性靠它数连续，截断会造成假断档。
    返回新写入行数；Supabase 未配置 / 表未建（v21 未执行）时返回 0（静默降级，不抛异常）。
    """
    if not supabase_store.is_configured():
        return 0
    date_key = trade_date or trade_calendar_service.now_cn().date().isoformat()
    try:
        if payload is None:
            payload = await get_signals()
        items = payload.get("all_signals")
        if not items:
            items = (payload.get("g_items") or []) + (payload.get("s_items") or [])
        rows = _snapshot_rows(date_key, items)
        if not rows:
            return 0
        sb = await supabase_store.get_service_client()
        res = await (
            sb.table("dark_flow_daily_snapshot")
            .upsert(rows, on_conflict="signal_date,code")
            .execute()
        )
        return len(res.data or [])
    except Exception as e:
        # 表未建是预期内降级（需执行 v21 迁移）；其他异常同样只记录，不拖垮调用方
        print(f"[dark_flow] 快照落库失败({date_key}): {e}")
        return 0


async def purge_old_snapshots(keep_days: int = _SNAPSHOT_RETENTION_DAYS) -> int:
    """删除保留窗口之外的形态快照，返回删除行数。理由同涨停/跌停池：只写不删会
    静默撞额度上限。表未建 / 未配置 → 返回 0（不影响 cron 其它步骤）。
    """
    if not supabase_store.is_configured():
        return 0
    try:
        days = max(_SNAPSHOT_MIN_RETENTION_DAYS, int(keep_days))
    except (TypeError, ValueError):
        days = _SNAPSHOT_RETENTION_DAYS
    cutoff = (trade_calendar_service.now_cn().date() - dt.timedelta(days=days)).isoformat()
    try:
        sb = await supabase_store.get_service_client()
        res = await sb.table("dark_flow_daily_snapshot").delete().lt("signal_date", cutoff).execute()
        return len(res.data or [])
    except Exception as e:
        print(f"[dark_flow] 快照清理失败(cutoff={cutoff}): {e}")
        return 0
