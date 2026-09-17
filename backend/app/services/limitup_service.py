"""连板梯队与板块聚集度：追连板「鱼腹」的观察层。

## 为什么单独开一条数据链路

现有全市场快照走 ``push2.eastmoney.com``（60 页分页，IP 级风控高危，见 ``spot_service``）。
连板数据来自 ``push2ex.eastmoney.com`` 的**涨停板池**业务端点，性质完全不同：

* **单次请求**返回全市场涨停池（一日约 40~90 只），比全市场快照少两个数量级；
* 直接带 ``lbc``（连板数）与 ``hybk``（所属板块），不必按 code 逐只回捞历史 K 线；
* 域名与 push2 相互独立 —— push2 被风控时本模块仍然可用。

``date=YYYYMMDD`` 支持回溯，于是晋级率回测**只需要涨停池本身**：把 D 日与 D+1 日的池子按
code 取交集，看 ``lbc`` 是否恰好 +1，即可得到晋级率，**零额外行情请求**。

⚠️ 但回溯窗口很短：实测 2026-08-27 及以前一律返回**空池**，只有最近约 15 个交易日有数据
（见 ``MAX_RELAY_DAYS``）。因此本模块的统计结论天然受限于 3 周窗口，且**空池必须与
「当天真的没有涨停」区分**——否则不同 ``days`` 会返回完全相同的统计量而不自知。

## 这一层只做「观察」，不做「买点」

连板接力的有效性尚未通过回测（见 ``tactic_evidence``），因此：

* 本模块不输出任何买卖动作，只输出客观的封板质量与位置描述；
* 该策略的证据等级（tier）由 ``relay_backtest`` 跑出的真实数字决定，**不允许人工拔高**；
* 前端展示必须带口径说明（``calibers.limitup_relay``）。

「鱼腹」在本模块的对应物是**位置分桶**（启动 / 加速 / 中继 / 高位 / 分歧）——
它是统计意义上的分组，不是建议。
"""
from __future__ import annotations

import asyncio
import datetime as dt
import time

import requests

from app.services import calibers, cache_utils, concurrency, tactic_evidence, trade_calendar_service

_BASE = "https://push2ex.eastmoney.com"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_TIMEOUT = 12

# 涨停板池各业务端点。字段差异见 normalize_* / normalize_broken。
_POOL_KIND = {
    "zt": "getTopicZTPool",  # 涨停板池：带 lbc 连板数、fbt 首封时间
    "zb": "getTopicZBPool",  # 炸板池：带 ztp 涨停价、zf 振幅，无 lbc
}

_UT = "7eea3edcaed734bea9cbfc24409ed989"
_DPT = "wz.ztzt"

_PAGE_SIZE = 500
_MAX_PAGES = 4
_PAGE_SLEEP = 0.15

# 全市场股票数（沪深京 A 股），用于把「次日涨停率」换算成随机基线。
# 注意方向：分母取偏大值会让基线偏小、结论偏宽松；这里取 5400 接近真实规模，
# 且真实晋级率与基线相差两个数量级（数十 % vs 不到 1 %），取值误差不影响定性结论。
_MARKET_UNIVERSE = 5400

_SNAP_TTL = 60           # 盘中最短短缓存：涨停池在盘中持续变化
_SNAP_CACHE_MAX = 8
_SNAP_CACHE: dict[str, tuple[float, dict]] = {}

_RELAY_TTL = 6 * 3600    # 晋级率只依赖已收盘交易日，半天内不会变
_RELAY_CACHE: dict[str, tuple[float, dict]] = {}

# 东财涨停池的历史回溯上限：实测 2026-08-27 及以前返回空池，08-28 起才有数据，
# 即**只覆盖最近约 15 个交易日（3 周）**。回测默认就取这个窗口 —— 取更大值只会
# 白白多打十几次必然返回空池的请求，统计量不会有任何变化（这个坑实测踩过）。
MAX_RELAY_DAYS = 15


# ---------- 抓取 ----------


def _fetch_pool_sync(kind: str, date_str: str) -> list[dict]:
    """同步抓取某一天的某个池子，返回原始记录列表（未规范化）。

    空池（``tc = 0``）是合法返回值，不抛异常；只有整体失败才抛 ``RuntimeError``。
    """
    endpoint = _POOL_KIND[kind]
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": _UA,
            "Accept": "*/*",
            "Referer": "https://quote.eastmoney.com/",
            "Connection": "keep-alive",
        }
    )
    out: list[dict] = []
    last_error: Exception | None = None
    for page in range(_MAX_PAGES):
        params = {
            "ut": _UT,
            "dpt": _DPT,
            "Pageindex": str(page),
            "pagesize": str(_PAGE_SIZE),
            "sort": "fbt:asc",
            "date": date_str,
        }
        try:
            resp = session.get(f"{_BASE}/{endpoint}", params=params, timeout=_TIMEOUT)
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001 - 网络/解析异常统一降级或上抛
            last_error = exc
            break
        data = payload.get("data") or {}
        pool = data.get("pool") or []
        total = data.get("tc")
        out.extend(pool)
        if not pool:
            break
        if isinstance(total, int) and len(out) >= total:
            break
        time.sleep(_PAGE_SLEEP)
    if not out and last_error is not None:
        raise RuntimeError(f"涨停板池请求失败({kind}/{date_str}): {last_error}")
    return out


# ---------- 规范化（单位统一为 元 / 亿元 / %） ----------


def _num(value, default: float = 0.0) -> float:
    """东财缺值可能是 None / '' / '-'。"""
    try:
        if value is None or value == "" or value == "-":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _fmt_time(raw) -> str:
    """封板时间是 HHMMSS 整数（``92500`` = 09:25:00），补零到 6 位再切分。"""
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return ""
    if v <= 0:
        return ""
    s = str(v).zfill(6)
    return f"{s[0:2]}:{s[2:4]}:{s[4:6]}"


def normalize_limit_up(item: dict) -> dict:
    """涨停池单条 → 内部结构。

    价格单位是「厘」（``p = 37000`` 即 37.00 元），必须除 1000；
    市值与封单资金单位是元，换算成亿元便于展示。
    """
    stat = item.get("zttj") or {}
    seal_fund = _num(item.get("fund"))
    float_mv = _num(item.get("ltsz"))
    return {
        "code": str(item.get("c") or "").strip(),
        "name": str(item.get("n") or "").strip(),
        "price": round(_num(item.get("p")) / 1000.0, 2),
        "change_pct": round(_num(item.get("zdp")), 2),
        "boards": int(_num(item.get("lbc"))),
        "seal_time": _fmt_time(item.get("fbt")),
        "last_seal_time": _fmt_time(item.get("lbt")),
        "break_count": int(_num(item.get("zbc"))),
        "seal_fund_yi": round(seal_fund / 1e8, 3),
        "float_mv_yi": round(float_mv / 1e8, 2),
        "turnover": round(_num(item.get("hs")), 2),
        "amount_yi": round(_num(item.get("amount")) / 1e8, 3),
        "sector": str(item.get("hybk") or "").strip() or "其他",
        "stat_days": int(_num(stat.get("days"))),
        "stat_boards": int(_num(stat.get("ct"))),
        # 封单占流通市值比（%）：衡量封板强度。大市值股 1% 已属强势，
        # 小盘股需要更高比例才算封得结实，所以它只能横向比、不能跨市值硬套。
        "seal_ratio": round(seal_fund / float_mv * 100, 3) if float_mv > 0 else 0.0,
    }


def normalize_broken(item: dict) -> dict:
    """炸板池单条 → 内部结构（该池没有连板数字段）。"""
    return {
        "code": str(item.get("c") or "").strip(),
        "name": str(item.get("n") or "").strip(),
        "price": round(_num(item.get("p")) / 1000.0, 2),
        "change_pct": round(_num(item.get("zdp")), 2),
        "limit_price": round(_num(item.get("ztp")) / 1000.0, 2),
        "break_count": int(_num(item.get("zbc"))),
        "amplitude": round(_num(item.get("zf")), 2),
        "sector": str(item.get("hybk") or "").strip() or "其他",
    }


# ---------- 聚合 ----------

# 连板高度分桶上限：6 及以上合并为「6板+」，避免出现 count=1 的长尾桶稀释统计。
_LADDER_CAP = 6


def ladder_label(boards: int) -> str:
    if boards <= 1:
        return "首板"
    if boards >= _LADDER_CAP:
        return f"{_LADDER_CAP}板+"
    return f"{boards}板"


def build_ladder(items: list[dict]) -> list[dict]:
    """按连板高度分组，从高到低；组内按首封时间升序（越早封板越靠前）。"""
    buckets: dict[int, list[dict]] = {}
    for it in items:
        key = min(max(it["boards"], 1), _LADDER_CAP)
        buckets.setdefault(key, []).append(it)
    out = []
    for key in sorted(buckets, reverse=True):
        rows = sorted(buckets[key], key=lambda x: x["seal_time"] or "99:99:99")
        out.append(
            {
                "key": key,
                "label": ladder_label(key),
                "count": len(rows),
                "items": rows,
            }
        )
    return out


def build_sectors(items: list[dict], limit: int = 8) -> list[dict]:
    """按所属板块聚合，用于识别「主线」。

    排序主键是板块内涨停家数 —— 家数比封单金额更能反映资金是否在这个板块里抱团。
    """
    groups: dict[str, list[dict]] = {}
    for it in items:
        groups.setdefault(it["sector"], []).append(it)

    out = []
    for sector, rows in groups.items():
        relay = [r for r in rows if r["boards"] >= 2]
        out.append(
            {
                "sector": sector,
                "count": len(rows),
                "relay_count": len(relay),
                "max_boards": max(r["boards"] for r in rows),
                "seal_fund_yi": round(sum(r["seal_fund_yi"] for r in rows), 2),
                "avg_turnover": round(sum(r["turnover"] for r in rows) / len(rows), 2),
                "codes": [r["code"] for r in rows],
                "names": [r["name"] for r in rows],
            }
        )
    out.sort(key=lambda x: (x["count"], x["max_boards"], x["seal_fund_yi"]), reverse=True)
    return out[:limit]


def build_sentiment(limit_up: list[dict], broken: list[dict]) -> dict:
    """当日情绪温度：涨停家数 / 炸板率 / 最高板 / 连板家数。

    炸板率 = 炸板家数 ÷ (涨停家数 + 炸板家数)。分母用「曾涨停过的家数」，
    而不是当日涨停家数，否则盘中炸板多、涨停少时该比值会突破 100%。
    """
    lu = len(limit_up)
    zb = len(broken)
    denom = lu + zb
    relay = [t for t in limit_up if t["boards"] >= 2]
    return {
        "limit_up_count": lu,
        "broken_count": zb,
        "break_rate": round(zb / denom * 100, 1) if denom else 0.0,
        "max_boards": max((t["boards"] for t in limit_up), default=0),
        "relay_count": len(relay),
        "first_board_count": lu - len(relay),
        "intact_count": sum(1 for t in limit_up if t["break_count"] == 0),
    }


# 情绪分级只做「当日横向」描述。之所以不写「历史高位 / 冰点」，是因为这里没有历史分位数据，
# 用分位口径的词会让读者以为做了统计比较 —— 那正是本项目反复出现的可信度越界。
def sentiment_note(s: dict) -> dict:
    rate = s["break_rate"]
    top = s["max_boards"]
    if rate >= 40:
        tone, text = "warn", "炸板率偏高，接力分歧加大"
    elif rate <= 20 and top >= 4:
        tone, text = "good", "封板扎实、高度尚在，接力相对顺畅"
    elif top == 0:
        tone, text = "neutral", "暂无涨停，情绪偏冷"
    else:
        tone, text = "neutral", "封板与炸板相对均衡"
    return {"tone": tone, "text": text}


def position_tag(item: dict) -> dict:
    """位置分桶 —— 「鱼腹」所在的段位。

    ⚠️ 这是**统计分桶，不是建议**。连板接力尚未通过回测（见 ``tactic_evidence``），
    因此这里只描述「处在哪个位置」，绝不含任何动作词。
    """
    b = item["boards"]
    if b <= 1:
        return {"tag": "启动", "reason": "首板，尚未形成连板"}
    if b >= 5:
        return {"tag": "高位", "reason": f"{b} 连板，位置偏高、波动放大"}
    if item["break_count"] >= 3:
        return {"tag": "分歧", "reason": f"{b} 连板，盘中反复开板 {item['break_count']} 次"}
    if b >= 4:
        return {"tag": "中继", "reason": f"{b} 连板，进入中继段"}
    return {"tag": "加速", "reason": f"{b} 连板，处于加速段"}


# ---------- 当日全景 ----------


async def get_snapshot(force: bool = False) -> dict:
    """当日连板全景：情绪 + 梯队 + 板块 + 个股位置标注。

    60 秒内存缓存。涨停池与炸板池并发拉取（各 1 次请求）。
    """
    today = trade_calendar_service.now_cn().date()
    key = today.isoformat()
    now = time.monotonic()
    if not force:
        hit = _SNAP_CACHE.get(key)
        if hit and now - hit[0] < _SNAP_TTL:
            return {**hit[1], "cached": True}

    date_str = today.strftime("%Y%m%d")
    zt_raw, zb_raw = await asyncio.gather(
        asyncio.to_thread(_fetch_pool_sync, "zt", date_str),
        asyncio.to_thread(_fetch_pool_sync, "zb", date_str),
        return_exceptions=True,
    )
    if isinstance(zt_raw, Exception):
        raise RuntimeError(f"涨停池获取失败: {zt_raw}")
    limit_up = [normalize_limit_up(x) for x in zt_raw]
    # 炸板池失败只影响炸板率，不该让整条链路失败 —— 降级为空并放一个标记。
    broken_ok = not isinstance(zb_raw, Exception)
    broken = [normalize_broken(x) for x in zb_raw] if broken_ok else []

    sentiment = build_sentiment(limit_up, broken)
    # 先统一挂上位置标注，再进各聚合层 —— 三处（ladder / sectors / stocks）必须看到同一份数据。
    # 反例：只给 stocks 挂 position 会让展开后的「连板梯队」缺字段，前端读到 undefined。
    decorated = [{**t, "position": position_tag(t)} for t in limit_up]
    stocks = sorted(decorated, key=lambda x: (-x["boards"], x["seal_time"] or "99:99:99"))
    data = {
        "trade_date": key,
        "session": trade_calendar_service.session_label(),
        "sentiment": sentiment,
        "sentiment_note": sentiment_note(sentiment),
        "ladder": build_ladder(decorated),
        "sectors": build_sectors(decorated),
        "stocks": stocks,
        "broken_ok": broken_ok,
        "evidence": tactic_evidence.describe("limitup_relay"),
        "caliber": calibers.describe("limitup_relay"),
    }
    cache_utils.put_bounded(_SNAP_CACHE, key, (now, data), max_entries=_SNAP_CACHE_MAX)
    return {**data, "cached": False}


# ---------- 晋级率回测 ----------


async def _completed_trading_days(n: int) -> list[dt.date]:
    """最近 n 个**已收盘**的交易日，从旧到新。

    盘中调用会跳过当天：当天池子还在变，用它统计「次日晋级」等于把半成品当样本。
    """
    d = await trade_calendar_service.last_trading_day()
    if not trade_calendar_service.is_after_close():
        d = await trade_calendar_service.last_trading_day(d - dt.timedelta(days=1))
    out: list[dt.date] = []
    for _ in range(max(1, n)):
        out.append(d)
        d = await trade_calendar_service.last_trading_day(d - dt.timedelta(days=1))
    return list(reversed(out))


def _cluster_bucket(sector_count: int) -> str:
    if sector_count >= 5:
        return "≥5家"
    if sector_count >= 3:
        return "3-4家"
    return "1-2家"


def _relay_stats(days: list[dt.date], per_day: dict[str, list[dict]]) -> dict:
    """核心统计：N 连板 → 次日晋级率，并按板块聚集度分组对比。

    晋级判定：次日涨停池里该 code 的 ``lbc`` 恰好等于当日 +1。
    停牌或未晋级一律记未晋级（保守），不做「剔除无法交易样本」这类对结论有利的处理。

    ⚠️ 为什么必须给「高度 × 聚集度」交叉表：板块聚集度与连板高度是**混淆**的 ——
    一个板块当天涨停 7 只时，这 7 只往往全是首板（板块启动第一天），而首板晋级率天然最低。
    只看聚集度的边缘分布，会把「首板占比高」误读成「热点板块不容易连板」。
    分层之后才能回答「控制住高度，板块聚集本身还有没有额外信息」。
    """
    by_boards: dict[int, dict] = {}
    by_cluster: dict[str, dict] = {}
    by_boards_cluster: dict[tuple[int, str], dict] = {}
    total = promoted_total = 0
    sessions = 0

    for i in range(len(days) - 1):
        cur = per_day.get(days[i].isoformat())
        nxt = per_day.get(days[i + 1].isoformat())
        if cur is None or nxt is None:
            continue
        sessions += 1
        next_map = {t["code"]: t["boards"] for t in nxt}

        sector_count: dict[str, int] = {}
        for t in cur:
            sector_count[t["sector"]] = sector_count.get(t["sector"], 0) + 1

        for t in cur:
            if not t["code"] or t["boards"] < 1:
                continue
            promoted = next_map.get(t["code"], 0) == t["boards"] + 1
            total += 1
            promoted_total += int(promoted)

            key = min(t["boards"], _LADDER_CAP)
            slot = by_boards.setdefault(key, {"key": key, "label": ladder_label(key), "total": 0, "promoted": 0})
            slot["total"] += 1
            slot["promoted"] += int(promoted)

            ckey = _cluster_bucket(sector_count[t["sector"]])
            slot2 = by_cluster.setdefault(ckey, {"key": ckey, "total": 0, "promoted": 0})
            slot2["total"] += 1
            slot2["promoted"] += int(promoted)

            slot3 = by_boards_cluster.setdefault(
                (key, ckey), {"boards": key, "cluster": ckey, "total": 0, "promoted": 0}
            )
            slot3["total"] += 1
            slot3["promoted"] += int(promoted)

    def _ratio(slot: dict) -> float:
        return round(slot["promoted"] / slot["total"] * 100, 1) if slot["total"] else 0.0

    boards_rows = [{**slot, "rate": _ratio(slot)} for slot in sorted(by_boards.values(), key=lambda x: x["key"])]
    cluster_order = {"1-2家": 0, "3-4家": 1, "≥5家": 2}
    cluster_rows = [
        {**slot, "rate": _ratio(slot)}
        for slot in sorted(by_cluster.values(), key=lambda x: cluster_order.get(x["key"], 9))
    ]

    # 交叉表按高度归并，只保留两层都有样本的组合，避免展示 n=1 的格子误导读者。
    cross: dict[int, list[dict]] = {}
    for (bkey, ckey), slot in by_boards_cluster.items():
        cross.setdefault(bkey, []).append({**slot, "rate": _ratio(slot)})
    cross_rows = [
        {
            "boards": bkey,
            "label": ladder_label(bkey),
            "clusters": sorted(cross[bkey], key=lambda x: cluster_order.get(x["cluster"], 9)),
        }
        for bkey in sorted(cross)
    ]

    return {
        "sessions": sessions,
        "total_samples": total,
        "overall_rate": round(promoted_total / total * 100, 1) if total else 0.0,
        "by_boards": boards_rows,
        "by_cluster": cluster_rows,
        "by_boards_cluster": cross_rows,
    }


async def relay_backtest(days: int = MAX_RELAY_DAYS, force: bool = False) -> dict:
    """历史 N 连板 → 次日晋级率（口径见 ``calibers.limitup_relay``）。

    只打涨停池接口，每天 1 次请求，走 ``concurrency.gather_limited`` 限流。
    结果缓存 6 小时（只依赖已收盘交易日，半天内不会变）。

    ⚠️ **数据窗口只有约 15 个交易日**：东财涨停池对更早的日期返回**空池**（实测
    2026-08-27 及以前全为 0 条，08-28 起才有数据）。空池必须与「当天真的没有涨停」区分开 ——
    前者要标为无数据并排除出样本，否则会把「接口不提供」算成「样本不足」，
    更糟的是会让不同 ``days`` 请求返回**完全相同**的统计量而不自知。
    """
    days = max(2, min(days, 40))
    cache_key = str(days)
    now = time.monotonic()
    if not force:
        hit = _RELAY_CACHE.get(cache_key)
        if hit and now - hit[0] < _RELAY_TTL:
            return {**hit[1], "cached": True}

    trading_days = await _completed_trading_days(days)
    results = await concurrency.gather_limited(
        [asyncio.to_thread(_fetch_pool_sync, "zt", d.strftime("%Y%m%d")) for d in trading_days],
        return_exceptions=True,
    )

    per_day: dict[str, list[dict]] = {}
    skipped: list[str] = []
    empty: list[str] = []
    for d, res in zip(trading_days, results):
        if isinstance(res, Exception):
            skipped.append(d.isoformat())
            continue
        if not res:
            # 空池 = 该日期超出接口回溯范围（见 docstring），不是「零样本」。
            empty.append(d.isoformat())
            continue
        per_day[d.isoformat()] = [normalize_limit_up(x) for x in res]

    stats = _relay_stats(trading_days, per_day)
    # 随机基线：不看任何条件、随手买一只票，次日刚好封上涨停的概率 ≈ 日均涨停家数 ÷ 全市场股票数。
    # 注意它不是「同口径基准」—— 晋级率的样本本身就是今日已封板的强势股，天然占优，
    # 这个数字只用来标出「随机水平」的量级，不能当作超额收益的基准（见 calibers.limitup_relay.pitfall）。
    avg_daily = round(stats["total_samples"] / stats["sessions"], 1) if stats["sessions"] else 0.0
    covered = sorted(per_day)
    data = {
        "caliber": calibers.describe("limitup_relay"),
        "evidence": tactic_evidence.describe("limitup_relay"),
        "days": days,
        "date_range": [trading_days[0].isoformat(), trading_days[-1].isoformat()] if trading_days else [],
        "data_window": [covered[0], covered[-1]] if covered else [],
        "effective_days": len(covered),
        "empty_dates": empty,
        "skipped_dates": skipped,
        "avg_daily_limit_up": avg_daily,
        "baseline_rate": round(avg_daily / _MARKET_UNIVERSE * 100, 4),
        "market_universe": _MARKET_UNIVERSE,
        **stats,
    }
    cache_utils.put_bounded(_RELAY_CACHE, cache_key, (now, data), max_entries=_SNAP_CACHE_MAX)
    return {**data, "cached": False}


def clear_caches() -> None:
    """清空模块缓存（测试与手动刷新用）。"""
    _SNAP_CACHE.clear()
    _RELAY_CACHE.clear()
