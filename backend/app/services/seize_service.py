"""封板雷达（抢封板观察层）。

## 这段能力解决什么

项目已有 ``limitup_service``：涨停池拿**已经封板**的票、``premium_readout`` 给「涨停价买入 →
次日集合竞价卖出」的收益读数（期望 +2%、胜率 61.7%）。但「抢封板」要的是在**封板瞬间 /
拉升过程中**就逮住它 —— 现有模块只展示封死后的结果。

封板瞬间拆成两个真实可下手窗口，且**全部从现有安全数据源（东财 push2ex 涨停池 + 炸板池，
单请求、零额外风控风险）派生**，不引入任何新的行情接口：

* **刚封板（just_sealed）**：涨停池里 ``fbt``（首封时间）在近 N 秒内的票 —— 最后封单窗口，
  可观察封单积累、小仓抢；
* **回封候选（reseal）**：炸板池（打到涨停后开板的票）里仍贴着涨停价的 —— 拉升回封过程中买入；
* **炸板预警（broken_alert）**：炸板池里振幅大、已明显掉离涨停的 —— 风险提示。

## 收益模型复用

卖出口径 = 现有的 ``limitup_premium``（涨停价买入 → 次日集合竞价卖出）。对于「刚封板」，买入价
就是涨停价，直接复用 ``premium_readout``；对于「回封候选」，收益**条件于回封成功**，给一份
**条件性**读数（取自 ``_TURNOVER_BUCKETS`` 可成交档均值），明确标注「若回封失败则无此收益」，
不把条件期望冒充成确定收益。

## 证据纪律

本模块只做观察与收益读数，**不构成买卖指令**。封板瞬间能否抢到、T+1 竞价能否溢价，都取决于
实时盘口与封单，属于执行层风险，不在任何历史回测覆盖范围内。措辞纪律沿用 limitup：
不出现「买 / 加仓 / 关注」动作词，百分比口径说明挂在 ``CaliberLine``。
"""
from __future__ import annotations

import asyncio
import datetime as dt
import time

from app.services import calibers, data_service, limitup_service, tactic_evidence, trade_calendar_service

# 复用涨停池模块里已经验证过的纯函数与常量，避免重复实现与口径漂移。
from app.services.limitup_service import (
    _TURNOVER_BUCKETS,
    _fetch_pool_sync,
    next_limit_price,
    normalize_broken,
    normalize_limit_up,
    premium_readout,
    price_limit_pct,
)

_RADAR_TTL = 15  # 雷达池取数短缓存（秒）：盘中高频轮询时压低 push2ex 请求量
_RADAR_CACHE_MAX = 4
_RADAR_CACHE: dict[str, tuple[float, dict]] = {}

# 刚封板窗口：首封时间距今 ≤ 此值（秒）视为「刚封板」，可观察/小仓抢。
_JUST_SEALED_WINDOW_SEC = 300

# 回封候选：炸板池里距涨停 ≤ 此百分比的票才进（太远的已明显走弱，不算回封候选）。
_RESEAL_MAX_DIST_PCT = 3.0

# 炸板预警：炸板池里距涨停 > 此百分比且振幅 ≥ 此值的票列为风险（已明显掉离涨停）。
_BROKEN_ALERT_MIN_DIST_PCT = 3.0
_BROKEN_ALERT_MIN_AMPLITUDE = 6.0

_CN_TZ = dt.timezone(dt.timedelta(hours=8))


def _cn_now() -> dt.datetime:
    return trade_calendar_service.now_cn()


def _seconds_since_seal(seal_time: str | None) -> float | None:
    """首封时间（HH:MM:SS）距今多少秒；缺值或解析失败返回 None。

    封板时间是当日时刻，与当前 CN 时间同日比较即可；盘中调用时封板时间一定早于 now。
    """
    if not seal_time or len(seal_time) < 5:
        return None
    try:
        hh, mm, ss = (int(seal_time[:2]), int(seal_time[2:4]), int(seal_time[4:6]))
    except (ValueError, IndexError):
        return None
    try:
        seal = dt.datetime.combine(_cn_now().date(), dt.time(hh, mm, ss), tzinfo=_CN_TZ)
    except ValueError:
        return None
    delta = (_cn_now() - seal).total_seconds()
    return delta if delta >= 0 else None


def _dist_to_limit_pct(price: float, limit_price: float) -> float:
    if limit_price <= 0:
        return 0.0
    return round((limit_price - price) / limit_price * 100, 2)


# 炸板池跨轮询价缓存：用来判断「正在回封」（价格向涨停回升）。
# 单实例内有效（serverless 多实例不共享，作为近似信号，不用于结算）。
_ZB_LAST: dict[str, tuple[float, float]] = {}


def _mark_zb_prices(stocks: list[dict]) -> None:
    now = time.monotonic()
    for s in stocks:
        _ZB_LAST[s["code"]] = (float(s["price"]), now)


def _recovering(code: str, price: float) -> tuple[bool, float | None]:
    """与上一次轮询比，价格是否向涨停回升。返回 (是否回升, 涨跌幅%)。"""
    last = _ZB_LAST.get(code)
    if last is None:
        return False, None
    last_price, last_t = last
    if last_price <= 0:
        return False, None
    trend = (price - last_price) / last_price * 100
    # 仅当本次轮询与上一次间隔合理（≤120s）时才算「近期回升」，避免跨实例乱序。
    return trend > 0.1 and (time.monotonic() - last_t) <= 120, round(trend, 2)


def _conditional_premium() -> dict:
    """回封候选的**条件性**次日竞价收益读数。

    来源：``_TURNOVER_BUCKETS`` 里 ``tradable=True`` 档的期望均值（已是项目登记口径，非编造）。
    语义：若回封成功（重新封板），则按 ``limitup_premium`` 同口径（次日集合竞价卖出）；
    回封失败则无此收益。明确标注 conditional，不冒充确定收益。
    """
    tradable = [b[2] for b in _TURNOVER_BUCKETS if b[4]]
    mean = round(sum(tradable) / len(tradable), 2) if tradable else 0.0
    return {
        "expect_pct": mean,
        "conditional": True,
        "note": (
            f"若回封成功，按次日集合竞价卖出；同口径可成交档历史读数约 {mean:+.2f}%。"
            "回封失败则无此收益，属条件性读数，非承诺。"
        ),
    }


# ---------- 三类信号派生（纯函数，便于离线测试） ----------


def derive_just_sealed(limit_up: list[dict], window_sec: int = _JUST_SEALED_WINDOW_SEC) -> list[dict]:
    """涨停池 → 刚封板候选。

    只取首封时间在窗口内的票（最后封单窗口）。保留 ``premium_readout`` 的完整读数、
    ``next_limit_price``（次日涨停价锚点）与 ``entry_discount``（=0，因为买入价就是涨停价）。
    """
    out: list[dict] = []
    for s in limit_up:
        secs = _seconds_since_seal(s.get("seal_time"))
        if secs is None or secs > window_sec:
            continue
        code = s["code"]
        name = s["name"]
        price = s["price"]
        premium = premium_readout(s)
        out.append(
            {
                "code": code,
                "name": name,
                "price": price,
                "limit_price": price,  # 已封板：现价即涨停价
                "change_pct": s["change_pct"],
                "seal_time": s.get("seal_time") or "",
                "seconds_since_seal": round(secs, 0),
                "seal_fund_yi": s.get("seal_fund_yi"),
                "seal_ratio": s.get("seal_ratio"),
                "break_count": s.get("break_count"),
                "turnover": s.get("turnover"),
                "sector": s.get("sector") or "其他",
                "limit_pct": price_limit_pct(code, name),
                "next_limit_price": next_limit_price(code, name, price),
                "entry_discount_pct": 0.0,  # 买入价=涨停价，无折价
                "premium": premium,
            }
        )
    out.sort(key=lambda x: x["seconds_since_seal"])
    return out


def derive_reseal(broken: list[dict], max_dist_pct: float = _RESEAL_MAX_DIST_PCT) -> list[dict]:
    """炸板池 → 回封候选。

    炸板池字段：``price`` 现价、``ztp`` 涨停价（normalize_broken 已落到 limit_price）、
    ``zdp`` 涨跌幅、``zf`` 振幅、``zbc`` 开板次数。距涨停 ≤ max_dist_pct 的才算「贴着涨停、
    有望回封」；按距涨停升序（最接近回封的排最前），并标注「正在回升」。
    """
    out: list[dict] = []
    for b in broken:
        price = b.get("price") or 0.0
        limit_price = b.get("limit_price") or 0.0
        dist = _dist_to_limit_pct(price, limit_price)
        if limit_price <= 0 or dist > max_dist_pct:
            continue
        code = b["code"]
        recovering, trend = _recovering(code, price)
        out.append(
            {
                "code": code,
                "name": b.get("name") or "",
                "price": price,
                "limit_price": limit_price,
                "change_pct": b.get("change_pct") or 0.0,
                "dist_to_limit_pct": dist,
                "amplitude": b.get("amplitude") or 0.0,
                "break_count": b.get("break_count") or 0,
                "sector": b.get("sector") or "其他",
                "limit_pct": price_limit_pct(code, b.get("name") or ""),
                "recovering": recovering,
                "price_trend_pct": trend,
                "premium_if_sealed": _conditional_premium(),
            }
        )
    out.sort(key=lambda x: (not x["recovering"], x["dist_to_limit_pct"]))
    _mark_zb_prices(broken)
    return out


def derive_broken_alert(
    broken: list[dict],
    min_dist_pct: float = _BROKEN_ALERT_MIN_DIST_PCT,
    min_amplitude: float = _BROKEN_ALERT_MIN_AMPLITUDE,
) -> list[dict]:
    """炸板池 → 炸板预警（已明显掉离涨停、振幅大，提示风险）。"""
    out: list[dict] = []
    for b in broken:
        price = b.get("price") or 0.0
        limit_price = b.get("limit_price") or 0.0
        dist = _dist_to_limit_pct(price, limit_price)
        amp = b.get("amplitude") or 0.0
        if limit_price <= 0 or dist < min_dist_pct or amp < min_amplitude:
            continue
        out.append(
            {
                "code": b["code"],
                "name": b.get("name") or "",
                "price": price,
                "limit_price": limit_price,
                "change_pct": b.get("change_pct") or 0.0,
                "dist_to_limit_pct": dist,
                "amplitude": amp,
                "break_count": b.get("break_count") or 0,
                "sector": b.get("sector") or "其他",
            }
        )
    out.sort(key=lambda x: (-x["amplitude"], -x["dist_to_limit_pct"]))
    return out


# ---------- 聚合 ----------


async def _fetch_pool(kind: str, date_str: str, retries: int = 1) -> list[dict]:
    """带一次重试的池子拉取。

    ``_fetch_pool_sync`` 本身无重试（与 ``limitup_service.get_snapshot`` 同口径），但雷达
    定位是盘中高频轮询，冷实例首跳的偶发读超时（实测 push2ex 12s 边缘）不值得让整块
    面板 502 —— 单次请求成本低，重试一次不构成风控压力。
    """
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return await asyncio.to_thread(_fetch_pool_sync, kind, date_str)
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < retries:
                await asyncio.sleep(1)
    raise last  # type: ignore[misc]


async def get_radar(force: bool = False) -> dict:
    """封板雷达：刚封板 + 回封候选 + 炸板预警，附条件性次日竞价收益读数。

    15 秒内存缓存：盘中前端高频轮询时压低 push2ex 请求量；``force`` 穿透缓存。
    涨停池与炸板池并发拉取（各 1 次请求，与 ``limitup_service.get_snapshot`` 同源同风险等级）。
    """
    today = trade_calendar_service.now_cn().date()
    key = today.isoformat()
    now_mono = time.monotonic()
    if not force:
        hit = _RADAR_CACHE.get(key)
        if hit and now_mono - hit[0] < _RADAR_TTL:
            return {**hit[1], "cached": True}

    date_str = today.strftime("%Y%m%d")
    zt_raw, zb_raw = await asyncio.gather(
        _fetch_pool("zt", date_str),
        _fetch_pool("zb", date_str),
        return_exceptions=True,
    )
    if isinstance(zt_raw, Exception):
        raise RuntimeError(f"涨停池获取失败: {zt_raw}")
    limit_up = [normalize_limit_up(x) for x in zt_raw]
    zb_ok = not isinstance(zb_raw, Exception)
    broken = [normalize_broken(x) for x in zb_raw] if zb_ok else []

    just_sealed = derive_just_sealed(limit_up)
    reseal = derive_reseal(broken)
    broken_alert = derive_broken_alert(broken)

    # 当日已封板票的「次日竞价卖出」收益读数（复用现有口径，给雷达一个背景读数）。
    premium_summary = limitup_service.premium_summary(limit_up) if limit_up else None

    now = _cn_now()
    local_time = now.time()
    market_open = now.weekday() < 5 and (
        dt.time(9, 15) <= local_time <= dt.time(11, 30)
        or dt.time(13, 0) <= local_time <= dt.time(15, 0)
    )

    data = {
        "trade_date": key,
        "session": trade_calendar_service.session_label(),
        "updated_at": now.isoformat(timespec="seconds"),
        "market_open": market_open,
        "poll_interval_seconds": 15 if market_open else 120,
        "just_sealed": just_sealed,
        "reseal": reseal,
        "broken_alert": broken_alert,
        # 全量涨停池成员（收益闭环的收盘判定依据：收盘后仍在池 = 封住）
        "zt_codes": [s["code"] for s in limit_up],
        "counts": {
            "just_sealed": len(just_sealed),
            "reseal": len(reseal),
            "broken_alert": len(broken_alert),
        },
        "zb_ok": zb_ok,
        "premium_summary": premium_summary,
        "evidence": tactic_evidence.describe("limitup_premium"),
        "caliber": calibers.describe("limitup_premium"),
        "note": (
            "封板雷达只做观察与收益读数，不构成买卖指令。抢封板需在封板瞬间自行决策："
            "T+1 竞价卖出口径见 limitup_premium（涨停价买入 → 次日集合竞价卖出，历史期望约 +2%、"
            "胜率约 62%）。回封候选的收益条件于回封成功，属条件性读数。"
        ),
    }
    from app.services import cache_utils

    # 盘中信号落库（首 sighting；ignore_duplicates 跳过重复，节流 120s 压 Supabase 写量）。
    if market_open and not _throttled("ingest", 120):
        await _ingest_candidates(key, just_sealed, reseal)

    cache_utils.put_bounded(_RADAR_CACHE, key, (now_mono, data), max_entries=_RADAR_CACHE_MAX)
    return {**data, "cached": False}


# ---------- 收益闭环：落库 → 收盘判定 → D+1 开盘结算 ----------
#
# 纪律：三条链路全部 best-effort（表未建/Supabase 未配置/网络失败 → 静默降级返回 0），
# 绝不拖垮雷达实时链路 —— 「没跑迁移」与「跑挂了」都只影响闭环，不影响信号本身。


def _resolve_next_open(
    hist_dates: list[str], hist_opens: list[float | None], trade_date: str
) -> float | None:
    """从日 K 里找 trade_date 之后的第一个交易日的开盘价（纯函数，便于测试）。

    D+1 停牌 / 数据缺失时返回 None（留待下次结算，不写 0 冒充）。
    """
    if not hist_dates or not hist_opens:
        return None
    for d, o in zip(hist_dates, hist_opens):
        if d > trade_date and o is not None and o > 0:
            return float(o)
    return None


def _calc_return_pct(buy_price: float, next_open: float) -> float | None:
    """(D+1 开盘 - 信号买入价) / 信号买入价 × 100。buy_price 非法时返回 None。"""
    if buy_price <= 0 or next_open <= 0:
        return None
    return round((next_open - buy_price) / buy_price * 100, 2)


_THROTTLE: dict[str, float] = {}


def _throttled(key: str, seconds: float) -> bool:
    """距上次执行不足 seconds 秒则跳过（闭环是低频后台活，不值得每次雷达请求都跑）。"""
    now = time.monotonic()
    last = _THROTTLE.get(key, 0.0)
    if now - last < seconds:
        return True
    _THROTTLE[key] = now
    return False


def _log_rows(trade_date: str, just_sealed: list[dict], reseal: list[dict]) -> list[dict]:
    """把两类信号压成落库行（首 sighting 的 buy_price 固化 = 拉升过程中的入场价）。"""
    now_iso = _cn_now().isoformat(timespec="seconds")
    rows: list[dict] = []
    for r in just_sealed:
        rows.append(
            {
                "trade_date": trade_date,
                "code": r["code"],
                "name": r["name"],
                "signal_kind": "just_sealed",
                "buy_price": r["price"],
                "limit_price": r["limit_price"],
                "dist_to_limit_pct": 0.0,
                "first_seen_at": now_iso,
                "last_seen_at": now_iso,
            }
        )
    for r in reseal:
        rows.append(
            {
                "trade_date": trade_date,
                "code": r["code"],
                "name": r["name"],
                "signal_kind": "reseal",
                "buy_price": r["price"],
                "limit_price": r["limit_price"],
                "dist_to_limit_pct": r["dist_to_limit_pct"],
                "first_seen_at": now_iso,
                "last_seen_at": now_iso,
            }
        )
    return rows


async def _ingest_candidates(trade_date: str, just_sealed: list[dict], reseal: list[dict]) -> int:
    """盘中信号落库（首 sighting）。返回写入行数；任何失败静默降级返回 0。"""
    if supabase_store is None or not supabase_store.is_configured():
        return 0
    rows = _log_rows(trade_date, just_sealed, reseal)
    if not rows:
        return 0
    try:
        sb = await supabase_store.get_service_client()
        res = await (
            sb.table("seize_radar_log")
            .upsert(rows, on_conflict="trade_date,code,signal_kind", ignore_duplicates=True)
            .execute()
        )
        return len(res.data or [])
    except Exception as e:  # noqa: BLE001 - 表未建/网络失败都是预期内降级
        print(f"[seize] 候选落库失败({trade_date}): {e}")
        return 0


async def _close_out_today(trade_date: str, zt_codes: set[str]) -> int:
    """收盘后判定：今天落库的票最终是否封住（= 收盘时仍在涨停池）。

    零额外行情请求 —— 判定依据就是本次雷达已经拉到的涨停池成员。返回更新行数。
    """
    if supabase_store is None or not supabase_store.is_configured():
        return 0
    try:
        sb = await supabase_store.get_service_client()
        res = await (
            sb.table("seize_radar_log")
            .select("id,code")
            .eq("trade_date", trade_date)
            .is_("sealed_final", "null")
            .execute()
        )
        pending = res.data or []
        updated = 0
        for row in pending:
            sealed = row["code"] in zt_codes
            up = await (
                sb.table("seize_radar_log").update({"sealed_final": sealed}).eq("id", row["id"]).execute()
            )
            updated += len(up.data or [])
        return updated
    except Exception as e:  # noqa: BLE001
        print(f"[seize] 收盘判定失败({trade_date}): {e}")
        return 0


async def _realize_pending(today_iso: str, cap: int = 30) -> int:
    """给已判定但未结算的行补 D+1 开盘价并算实际收益。

    逐只拉日 K（腾讯 newfqkline）＝行情源风控主因，所以：只补 `trade_date < 今天` 的行、
    单次上限 cap 只、写入即固化（下次不再拉）。盘中/竞价阶段不拉（D+1 还没开盘）。
    """
    if supabase_store is None or not supabase_store.is_configured():
        return 0
    try:
        sb = await supabase_store.get_service_client()
        res = await (
            sb.table("seize_radar_log")
            .select("id,code,trade_date,buy_price")
            .eq("next_open", "null")
            .lt("trade_date", today_iso)
            .not_.is_("sealed_final", "null")
            .order("trade_date", desc=True)
            .limit(cap)
            .execute()
        )
        pending = res.data or []
        if not pending:
            return 0
        realized = 0
        for row in pending:
            try:
                hist = await asyncio.to_thread(data_service.get_history, row["code"], 15)
            except Exception:  # noqa: BLE001
                continue
            if not hist or not hist.dates or not hist.opens:
                continue
            nxt = _resolve_next_open(hist.dates, hist.opens, row["trade_date"])
            if nxt is None:
                continue
            ret = _calc_return_pct(float(row["buy_price"]), nxt)
            up = await (
                sb.table("seize_radar_log")
                .update(
                    {
                        "next_open": nxt,
                        "next_open_pct": round((nxt / float(row["buy_price"]) - 1) * 100, 2)
                        if float(row["buy_price"]) > 0
                        else None,
                        "realized_return_pct": ret,
                    }
                )
                .eq("id", row["id"])
                .execute()
            )
            realized += len(up.data or [])
        return realized
    except Exception as e:  # noqa: BLE001
        print(f"[seize] 收益结算失败: {e}")
        return 0


async def get_history_log(days: int = 14) -> dict:
    """收益追踪：近 N 个自然日的落库记录 + 已结算汇总。

    顺带触发收盘判定与结算（各自带节流：收盘判定 10 分钟一次、结算 30 分钟一次），
    让前端打开一次就能看到最新结果，不需要独立维护 cron。
    """
    today = _cn_now().date()
    today_iso = today.isoformat()
    radar = await get_radar()
    if radar["trade_date"] == today_iso:
        zt_codes = set(radar.get("zt_codes") or [])
        # 收盘判定用全量涨停池成员（收盘后仍在池 = 封住）。
        if not _throttled("close_out", 600):
            await _close_out_today(today_iso, zt_codes)
    if not _throttled("realize", 1800):
        await _realize_pending(today_iso)

    enabled = True
    rows: list[dict] = []
    if supabase_store is None or not supabase_store.is_configured():
        enabled = False
    else:
        try:
            sb = await supabase_store.get_service_client()
            since = (today - dt.timedelta(days=days)).isoformat()
            res = await (
                sb.table("seize_radar_log")
                .select(
                    "trade_date,code,name,signal_kind,buy_price,limit_price,"
                    "dist_to_limit_pct,sealed_final,next_open,realized_return_pct"
                )
                .gte("trade_date", since)
                .order("trade_date", desc=True)
                .order("first_seen_at", desc=True)
                .limit(300)
                .execute()
            )
            rows = res.data or []
        except Exception as e:  # noqa: BLE001 - 表未建时 v15 迁移还没跑
            print(f"[seize] 收益读回失败: {e}")
            enabled = False

    settled = [r for r in rows if r.get("realized_return_pct") is not None]
    wins = [r for r in settled if float(r["realized_return_pct"]) > 0]
    summary = {
        "total": len(rows),
        "settled": len(settled),
        "pending": len(rows) - len(settled),
        "win_rate": round(len(wins) / len(settled) * 100, 1) if settled else None,
        "avg_return": round(sum(float(r["realized_return_pct"]) for r in settled) / len(settled), 2)
        if settled
        else None,
    }
    return {
        "enabled": enabled,
        "days": days,
        "summary": summary,
        "rows": rows,
        "note": (
            "口径：realized_return_pct =（D+1 开盘价 − 信号时买入价）/ 信号时买入价。"
            "信号时买入价是首次命中雷达那一刻的现价（拉升过程中），非涨停价；"
            "因此与 limitup_premium（涨停价买入）口径不同、不可比、不可加。"
            "样本为盘中自动记录，未含手续费与滑点，非投资建议。"
        ),
    }


def clear_cache() -> None:
    """清空模块缓存（测试与手动刷新用）。"""
    _RADAR_CACHE.clear()
    _ZB_LAST.clear()
    _THROTTLE.clear()
