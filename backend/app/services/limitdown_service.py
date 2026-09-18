"""跌停板池与「次日修复」读数：抄底情绪的观察层。

## 它回答什么

「跌停的票第二天会不会修复、能不能靠低吸抄一把」是散户最常见的念头之一。
本模块用**真实收益口径**回答：D 日以跌停价（= D 日收盘价）买入，D+1 分别按
「集合竞价开盘」和「收盘」卖出各能拿到多少，以及次日盘中最高价相对买入价的弹性
（反抽到底存在不存在）。

## 它不回答什么（这一节比上面重要）

**不给抄底信号。** 实测口径见 ``tactic_evidence.STRATEGY_EVIDENCE['limitdown_repair']``：
在 2026-08-31 ~ 09-17 的 133 个样本上，D 日跌停买入 → D+1 集合竞价卖出的期望收益为
**−4.47%/次、胜率 4.5%**，打平需要 80.6% 的胜率 —— 是明确的负期望。按项目证据分级
（n ≥ 30 且超额为负 → ``unsupported``），本策略 ``actionable`` 恒为 false。
前端**不得**把这里任何字段渲染成买点、分批建仓或建议。

唯一的正向发现是「次日盘中确有反抽」：D+1 盘中最高价平均高出买入价 +0.57%、
50.4% 的样本盘中曾转正。但这点弹性覆盖不了次日平均 −4.47% 的低开 ——
它只能当**风险温度**读，不能当机会读。

## 数据源

东财 ``push2ex`` 跌停板池（``getTopicDTPool``），与涨停池同域不同端点，
因此和 ``limitup_service`` 一样**不接** ``spot_service`` 那套行情源冷却闸门。

⚠️ 该端点的 ``sort`` 参数**必须用** ``zdp:asc``（按跌幅）。照抄涨停池的 ``fbt:asc``
会返回**空池** —— 跌停池没有 ``fbt`` 字段，排序键不存在时接口给空结果而不是报错，
这个坑实测踩过。

⚠️ 回溯窗口与涨停池一致，**只有约 15 个交易日**。更早日期一律返回空池，但「空池」有两种
截然不同的成因，必须区分：一是**超出接口回溯范围**（数据缺陷），二是**当天真的没有跌停**
（市场强，是有效信息）。``repair_backtest`` 以「早于最早有跌停记录的那天」为判据，
分别输出 ``out_of_window_dates`` 与 ``zero_down_dates``；两者都不产生交易样本，
所以对统计量无影响 —— 区别只在读数，混在一起会让人把「市场无跌停」误读成「接口没数据」。
"""
from __future__ import annotations

import asyncio
import datetime as dt
import statistics
import time

import requests

from app.services import calibers, cache_utils, concurrency, tactic_evidence, trade_calendar_service
from app.services.data_service import get_history

_BASE = "https://push2ex.eastmoney.com"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_TIMEOUT = 12

_UT = "7eea3edcaed734bea9cbfc24409ed989"
_DPT = "wz.ztzt"

_DT_ENDPOINT = "getTopicDTPool"
_ZT_ENDPOINT = "getTopicZTPool"
_DT_SORT = "zdp:asc"  # ⚠️ 不是 fbt —— 见模块 docstring
_ZT_SORT = "fbt:asc"

_PAGE_SIZE = 300
_MAX_PAGES = 4
_PAGE_SLEEP = 0.15

_SNAP_TTL = 60              # 盘中最短缓存：跌停池盘中持续变化
_SNAP_CACHE_MAX = 8
_SNAP_CACHE: dict[str, tuple[float, dict]] = {}

_REPAIR_TTL = 6 * 3600      # 修复率只依赖已收盘交易日，半天内不会变
_REPAIR_CACHE: dict[str, tuple[float, dict]] = {}

# 东财跌停池的历史回溯上限（实测 2026-08-28 及以前返回空池，08-31 起才有数据）。
MAX_REPAIR_DAYS = 15

# 收益回测要为**每只**跌停股拉一次日 K（逐只请求是行情源风控主因），
# 因此这里同时是「请求量上限」与「serverless 超时保护」。超出时按日期新→旧截断。
_MAX_SAMPLES = 200
_HIST_DAYS = 60

# 判「次日一字跌停卖不出去」的容差：最高价与最低价之差小于该值视为全天无成交区间。
_FLAT_EPS = 0.005


# ---------- 抓取 ----------


def _fetch_pool_sync(endpoint: str, sort: str, date_str: str) -> list[dict]:
    """同步抓取某天的池子，返回原始记录列表（未规范化）。

    空池（``tc = 0``）是合法返回值，不抛异常；只有整体失败才抛 ``RuntimeError``。
    """
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
            "sort": sort,
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
        raise RuntimeError(f"跌停板池请求失败({endpoint}/{date_str}): {last_error}")
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
    """封板时间是 HHMMSS 整数（``145600`` = 14:56:00），补零到 6 位再切分。"""
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return ""
    if v <= 0:
        return ""
    s = str(v).zfill(6)
    return f"{s[0:2]}:{s[2:4]}:{s[4:6]}"


def normalize_limit_down(item: dict) -> dict:
    """跌停池单条 → 内部结构。

    与涨停池的字段差异（照抄涨停池会踩）：

    * 没有 ``lbc``（连板数）→ 跌停池用 ``days`` 表示**连续跌停天数**；
    * 没有 ``zbc``（炸板次数）与 ``fbt``（首封时间）→ 只有 ``lbt``（最后封板时间）；
    * 封单金额在 ``fba``（元），**不是** ``fund`` —— 跌停池的 ``fund`` 是小额噪声字段
      （实测同一只票 ``fund`` 46 万 vs ``fba`` 1.64 亿），用错会让封单强度差三个数量级。

    价格单位同样是「厘」（``p = 7860`` 即 7.86 元），必须除 1000。
    """
    seal_fund = _num(item.get("fba"))
    float_mv = _num(item.get("ltsz"))
    return {
        "code": str(item.get("c") or "").strip(),
        "name": str(item.get("n") or "").strip(),
        "price": round(_num(item.get("p")) / 1000.0, 2),
        "change_pct": round(_num(item.get("zdp")), 2),
        "down_days": max(1, int(_num(item.get("days"), 1))),
        "last_seal_time": _fmt_time(item.get("lbt")),
        "seal_fund_yi": round(seal_fund / 1e8, 3),
        "float_mv_yi": round(float_mv / 1e8, 2),
        "turnover": round(_num(item.get("hs")), 2),
        "amount_yi": round(_num(item.get("amount")) / 1e8, 3),
        "sector": str(item.get("hybk") or "").strip() or "其他",
        # 封单占流通市值比（%）：衡量抛压厚度。与涨停侧的同名指标语义相反 ——
        # 涨停封单厚是买盘强，跌停封单厚是**卖不掉**，不能跨侧比较。
        "seal_ratio": round(seal_fund / float_mv * 100, 3) if float_mv > 0 else 0.0,
    }


# ---------- 聚合 ----------

# 连续跌停天数分桶上限：4 及以上合并为「4连跌+」，避免 count=1 的长尾桶稀释统计。
_LADDER_CAP = 4


def ladder_label(days: int) -> str:
    if days <= 1:
        return "首日跌停"
    if days >= _LADDER_CAP:
        return f"{_LADDER_CAP}连跌+"
    return f"{days}连跌"


def build_ladder(items: list[dict]) -> list[dict]:
    """按连续跌停天数分组，从高到低；组内按封单金额降序（封得越死越靠前）。"""
    buckets: dict[int, list[dict]] = {}
    for it in items:
        key = min(max(it["down_days"], 1), _LADDER_CAP)
        buckets.setdefault(key, []).append(it)
    out = []
    for key in sorted(buckets, reverse=True):
        rows = sorted(buckets[key], key=lambda x: -x["seal_fund_yi"])
        out.append({"key": key, "label": ladder_label(key), "count": len(rows), "items": rows})
    return out


def build_sectors(items: list[dict], limit: int = 8) -> list[dict]:
    """按所属板块聚合，用于识别「哪个板块在集体杀跌」。

    ⚠️ 与涨停侧的板块聚集度**方向相反**：那边家数多是抱团做多，
    这边家数多是**板块级利空/资金集体撤离**。回测显示后者与「次日修复」负相关
    （同板块 ≥5 只跌停的期望收益比孤立跌停更差），所以它在这里是**风险读数**。
    """
    groups: dict[str, list[dict]] = {}
    for it in items:
        groups.setdefault(it["sector"], []).append(it)

    out = []
    for sector, rows in groups.items():
        out.append(
            {
                "sector": sector,
                "count": len(rows),
                "max_down_days": max(r["down_days"] for r in rows),
                "chain_count": sum(1 for r in rows if r["down_days"] >= 2),
                "seal_fund_yi": round(sum(r["seal_fund_yi"] for r in rows), 2),
                "avg_turnover": round(sum(r["turnover"] for r in rows) / len(rows), 2),
                "codes": [r["code"] for r in rows],
                "names": [r["name"] for r in rows],
            }
        )
    out.sort(key=lambda x: (x["count"], x["max_down_days"], x["seal_fund_yi"]), reverse=True)
    return out[:limit]


def build_sentiment(down: list[dict], limit_up_count: int = 0) -> dict:
    """当日跌停情绪：跌停家数、连跌家数、涉及板块数、最集中板块。

    涨停侧对应物是「炸板率」；跌停侧刻意**不造**对称的比率指标 ——
    跌停池不提供盘中开板次数，用成交额或换手做代理都会造出一个看着精确、
    实际无法解释的数字，这正是本项目反复出现的可信度越界。
    """
    chain = [t for t in down if t["down_days"] >= 2]
    sector_counts: dict[str, int] = {}
    for t in down:
        sector_counts[t["sector"]] = sector_counts.get(t["sector"], 0) + 1
    top = max(sector_counts.items(), key=lambda kv: kv[1]) if sector_counts else None
    return {
        "limit_down_count": len(down),
        "limit_up_count": limit_up_count,
        # 跌停/涨停 家数比：>1 说明抛压占优。涨停数缺失时给 None 而不是 0，
        # 前端要能区分「比值为 0」和「算不出来」。
        "down_up_ratio": round(len(down) / limit_up_count, 2) if limit_up_count else None,
        "chain_count": len(chain),
        "max_down_days": max((t["down_days"] for t in down), default=0),
        "sector_count": len(sector_counts),
        "top_sector": top[0] if top else None,
        "top_sector_count": top[1] if top else 0,
    }


# 情绪分级只做「当日横向」描述 —— 没有历史分位数据时不写「冰点 / 高位」这类
# 分位口径的词，否则读者会以为做了统计比较。
def sentiment_note(s: dict) -> dict:
    n = s["limit_down_count"]
    if n == 0:
        return {"tone": "neutral", "text": "全市场无跌停，抛压很小"}
    if n >= 20:
        return {"tone": "warn", "text": f"{n} 家跌停，恐慌盘集中释放"}
    if n >= 8:
        return {"tone": "neutral", "text": f"{n} 家跌停，分歧与获利了结并存"}
    return {"tone": "neutral", "text": f"{n} 家跌停，属零星个股行为"}


def position_tag(item: dict) -> dict:
    """位置分桶 —— **统计分组，不是建议**，因此绝不含动作词。

    与涨停侧（启动/加速/中继/高位/分歧）对称，这里描述的是「跌到哪一步了」。
    """
    d = item["down_days"]
    if d >= 3:
        return {"tag": "深跌", "reason": f"连续 {d} 日跌停，抛压尚未衰竭"}
    if d == 2:
        return {"tag": "连跌", "reason": "连续 2 日跌停"}
    if item["seal_ratio"] >= 1.0:
        return {"tag": "封死", "reason": "跌停封单相对流通市值偏大，当日基本没有承接"}
    if item["turnover"] >= 10:
        return {"tag": "换手", "reason": f"换手 {item['turnover']}%，筹码大幅交换"}
    return {"tag": "首跌", "reason": "首个跌停日"}


# ---------- 当日全景 ----------


async def get_snapshot(force: bool = False) -> dict:
    """当日跌停全景：情绪 + 连跌梯队 + 板块聚集 + 个股位置标注。

    60 秒内存缓存。跌停池与涨停池并发拉取（各 1 次请求）；
    涨停池只为算「跌停/涨停家数比」，失败时降级为缺失而不是让整条链路失败。
    """
    today = trade_calendar_service.now_cn().date()
    key = today.isoformat()
    now = time.monotonic()
    if not force:
        hit = _SNAP_CACHE.get(key)
        if hit and now - hit[0] < _SNAP_TTL:
            return {**hit[1], "cached": True}

    date_str = today.strftime("%Y%m%d")
    dt_raw, zt_raw = await asyncio.gather(
        asyncio.to_thread(_fetch_pool_sync, _DT_ENDPOINT, _DT_SORT, date_str),
        asyncio.to_thread(_fetch_pool_sync, _ZT_ENDPOINT, _ZT_SORT, date_str),
        return_exceptions=True,
    )
    if isinstance(dt_raw, Exception):
        raise RuntimeError(f"跌停池获取失败: {dt_raw}")
    limit_up_ok = not isinstance(zt_raw, Exception)
    limit_up_count = len(zt_raw) if limit_up_ok else 0

    down = [normalize_limit_down(x) for x in dt_raw]
    sentiment = build_sentiment(down, limit_up_count)
    # 先统一挂上位置标注，再进各聚合层 —— 三处（ladder / sectors / stocks）必须看到同一份数据。
    decorated = [{**t, "position": position_tag(t)} for t in down]
    stocks = sorted(decorated, key=lambda x: (-x["down_days"], -x["seal_fund_yi"]))
    data = {
        "trade_date": key,
        "session": trade_calendar_service.session_label(),
        "sentiment": sentiment,
        "sentiment_note": sentiment_note(sentiment),
        "ladder": build_ladder(decorated),
        "sectors": build_sectors(decorated),
        "stocks": stocks,
        "limit_up_ok": limit_up_ok,
        "evidence": tactic_evidence.describe("limitdown_repair"),
        "caliber": calibers.describe("limitdown_repair"),
    }
    cache_utils.put_bounded(_SNAP_CACHE, key, (now, data), max_entries=_SNAP_CACHE_MAX)
    return {**data, "cached": False}


# ---------- 次日修复回测 ----------


async def _completed_trading_days(n: int) -> list[dt.date]:
    """最近 n 个**已收盘**的交易日，从旧到新。

    盘中调用会跳过当天：当天池子还在变，用它统计「次日表现」等于把半成品当样本。
    """
    d = await trade_calendar_service.last_trading_day()
    if not trade_calendar_service.is_after_close():
        d = await trade_calendar_service.last_trading_day(d - dt.timedelta(days=1))
    out: list[dt.date] = []
    for _ in range(max(1, n)):
        out.append(d)
        d = await trade_calendar_service.last_trading_day(d - dt.timedelta(days=1))
    return list(reversed(out))


def _norm_date(s: str) -> str:
    return str(s).replace("-", "")


def _cluster_bucket(n: int) -> str:
    if n >= 5:
        return "≥5家"
    if n >= 2:
        return "2-4家"
    return "1家"


def stats_of(rows: list[dict]) -> dict:
    """一组样本的收益统计（纯函数，便于单测）。

    主口径是 ``ret_open``（D+1 集合竞价卖出），因为那正是「跌停买入、次日竞价套现」
    这个动作的收益。``ret_close``（持有到收盘）与 ``ret_high``（次日盘中最高）
    只作对照，用来说明「反抽是否存在、换时点能不能改善」。
    """
    if not rows:
        return {"n": 0}
    opens = [r["ret_open"] for r in rows]
    wins = [x for x in opens if x > 0]
    loses = [x for x in opens if x <= 0]
    avg = statistics.fmean(opens)
    avg_win = statistics.fmean(wins) if wins else 0.0
    avg_loss = statistics.fmean(loses) if loses else 0.0
    denom = avg_win + abs(avg_loss)
    closes = [r["ret_close"] for r in rows if r["ret_close"] is not None]
    highs = [r["ret_high"] for r in rows]
    return {
        "n": len(rows),
        "expect_open": round(avg * 100, 2),
        "median_open": round(statistics.median(opens) * 100, 2),
        "win_rate_open": round(len(wins) / len(rows) * 100, 1),
        "avg_win": round(avg_win * 100, 2),
        "avg_loss": round(avg_loss * 100, 2),
        # 打平所需胜率：在当前「平均盈利 / 平均亏损」结构下，期望为 0 的临界胜率。
        # 这是本模块最该被看见的数字 —— 它把「胜率看起来还行」直接翻译成「够不够」。
        "breakeven_win_rate": round(abs(avg_loss) / denom * 100, 1) if denom else 0.0,
        "expect_close": round(statistics.fmean(closes) * 100, 2) if closes else None,
        "win_rate_close": (
            round(sum(1 for x in closes if x > 0) / len(closes) * 100, 1) if closes else None
        ),
        "avg_high": round(statistics.fmean(highs) * 100, 2) if highs else None,
        "high_positive_rate": (
            round(sum(1 for x in highs if x > 0) / len(highs) * 100, 1) if highs else None
        ),
        "next_sealed_down_rate": round(
            sum(1 for r in rows if r["next_sealed_down"]) / len(rows) * 100, 1
        ),
        "next_limit_up_rate": round(sum(1 for r in rows if r["next_limit_up"]) / len(rows) * 100, 1),
    }


def _brief(r: dict) -> dict:
    return {
        "date": r["d"],
        "code": r["code"],
        "name": r["name"],
        "sector": r["sector"],
        "ret_open": round(r["ret_open"] * 100, 2),
    }


async def repair_backtest(days: int = MAX_REPAIR_DAYS, force: bool = False) -> dict:
    """跌停次日修复回测：D 日跌停买入 → D+1 不同时点卖出的真实收益分布。

    ⚠️ 与 ``limitup_service.relay_backtest`` 的成本不同：那条链路只打涨停池，
    **零额外行情请求**；这条必须为每只跌停股拉一次日 K（逐只请求是风控主因），
    因此样本上限 ``_MAX_SAMPLES`` 同时承担请求量控制与 serverless 超时保护，
    且结果缓存 6 小时。走 ``concurrency.gather_limited`` 的进程级配额。
    """
    days = max(2, min(days, 30))
    cache_key = str(days)
    now = time.monotonic()
    if not force:
        hit = _REPAIR_CACHE.get(cache_key)
        if hit and now - hit[0] < _REPAIR_TTL:
            return {**hit[1], "cached": True}

    today_key = trade_calendar_service.now_cn().date().isoformat()
    trading_days = await _completed_trading_days(days)
    date_strs = [d.strftime("%Y%m%d") for d in trading_days]

    dt_results, zt_results = await asyncio.gather(
        concurrency.gather_limited(
            [asyncio.to_thread(_fetch_pool_sync, _DT_ENDPOINT, _DT_SORT, s) for s in date_strs],
            return_exceptions=True,
        ),
        concurrency.gather_limited(
            [asyncio.to_thread(_fetch_pool_sync, _ZT_ENDPOINT, _ZT_SORT, s) for s in date_strs],
            return_exceptions=True,
        ),
    )

    per_day: dict[str, list[dict]] = {}
    skipped: list[str] = []
    empty: list[str] = []
    for d, res in zip(trading_days, dt_results):
        if isinstance(res, Exception):
            skipped.append(d.isoformat())
            continue
        if not res:
            # 空池 = 超出接口回溯范围（见 docstring），不是「零跌停」，必须排除出样本。
            empty.append(d.isoformat())
            continue
        per_day[d.isoformat()] = [normalize_limit_down(x) for x in res]

    zt_codes: dict[str, set[str]] = {}
    for d, res in zip(trading_days, zt_results):
        if isinstance(res, Exception):
            continue
        zt_codes[d.isoformat()] = {str(x.get("c") or "").strip() for x in res}

    samples: list[tuple[dt.date, dict]] = []
    for d in trading_days:
        for it in per_day.get(d.isoformat(), []):
            if it["code"]:
                samples.append((d, it))
    candidate_size = len(samples)
    if candidate_size > _MAX_SAMPLES:
        samples = sorted(samples, key=lambda x: x[0], reverse=True)[:_MAX_SAMPLES]

    codes = sorted({it["code"] for _, it in samples})
    hist_results = await concurrency.gather_limited(
        [asyncio.to_thread(get_history, c, _HIST_DAYS) for c in codes],
        return_exceptions=True,
    )
    hist = {
        c: h for c, h in zip(codes, hist_results) if not isinstance(h, Exception) and h is not None
    }

    day_index = {d.isoformat(): i for i, d in enumerate(trading_days)}
    sector_counts_by_day: dict[str, dict[str, int]] = {}
    for d_key, items in per_day.items():
        cnt: dict[str, int] = {}
        for it in items:
            cnt[it["sector"]] = cnt.get(it["sector"], 0) + 1
        sector_counts_by_day[d_key] = cnt

    rows: list[dict] = []
    for d, it in samples:
        code = it["code"]
        h = hist.get(code)
        if h is None or not h.opens or not h.highs or not h.lows:
            continue
        dates_norm = [_norm_date(x) for x in h.dates]
        try:
            i = dates_norm.index(_norm_date(d.isoformat()))
        except ValueError:
            continue
        if i + 1 >= len(h.dates):
            continue
        buy = h.closes[i]  # D 日跌停收盘价 = 买入价
        if buy <= 0 or h.opens[i + 1] <= 0:
            continue

        nxt_open = h.opens[i + 1]
        nxt_close = h.closes[i + 1]
        nxt_high = h.highs[i + 1]
        nxt_low = h.lows[i + 1]
        # D+1 是今天（盘中）：开盘价已确定可用，收盘价还没定，置 None 而不是拿实时价冒充。
        next_is_today = dates_norm[i + 1] == _norm_date(today_key)

        # 当日全天封死跌停：最高价 == 收盘价 == 跌停价，即「随时买得到但没人接」。
        sealed_day = abs(h.highs[i] - h.closes[i]) < _FLAT_EPS
        # 次日一字跌停：全天无价格区间且开盘即跌停 —— 这种局面**挂单也卖不出去**。
        next_unsellable = (nxt_high - nxt_low) < _FLAT_EPS and nxt_open / buy - 1 <= -0.095

        di = day_index.get(d.isoformat())
        nxt_date = (
            trading_days[di + 1].isoformat() if di is not None and di + 1 < len(trading_days) else None
        )
        # 「次日仍跌停」用池子口径（不受各板块涨跌幅限制差异影响），比用 K 线判断更准。
        next_in_down_pool = nxt_date is not None and code in {
            x["code"] for x in per_day.get(nxt_date, [])
        }

        rows.append(
            {
                "d": d.isoformat(),
                "code": code,
                "name": it["name"],
                "sector": it["sector"],
                "down_days": it["down_days"],
                "day_down_n": len(per_day.get(d.isoformat(), [])),
                "sector_down_n": sector_counts_by_day.get(d.isoformat(), {}).get(it["sector"], 0),
                "sealed_day": sealed_day,
                "ret_open": nxt_open / buy - 1,
                "ret_close": None if next_is_today else nxt_close / buy - 1,
                "ret_high": nxt_high / buy - 1,
                "next_sealed_down": next_in_down_pool,
                "next_limit_up": nxt_date is not None and code in zt_codes.get(nxt_date, set()),
                "unsellable": next_unsellable,
            }
        )

    sealed_rows = [r for r in rows if r["sealed_day"]]
    opened_rows = [r for r in rows if not r["sealed_day"]]
    by_sealed = [
        {"key": "sealed", "label": "全天封死跌停", **stats_of(sealed_rows)},
        {"key": "opened", "label": "盘中开过板", **stats_of(opened_rows)},
    ]
    by_down_days = [
        {"key": "1", "label": "首日跌停", **stats_of([r for r in rows if r["down_days"] <= 1])},
        {"key": "2", "label": "连续 2 日", **stats_of([r for r in rows if r["down_days"] == 2])},
        {"key": "3+", "label": "连续 3 日+", **stats_of([r for r in rows if r["down_days"] >= 3])},
    ]
    by_cluster = [
        {
            "key": lab,
            "label": lab,
            **stats_of([r for r in rows if _cluster_bucket(r["sector_down_n"]) == lab]),
        }
        for lab in ("1家", "2-4家", "≥5家")
    ]

    drop9 = [r for r in rows if r["ret_open"] <= -0.09]
    tail = {
        "drop9_n": len(drop9),
        "drop9_rate": round(len(drop9) / len(rows) * 100, 1) if rows else 0.0,
        "unsellable_n": sum(1 for r in rows if r["unsellable"]),
    }

    covered = sorted(per_day)
    # ⚠️ 「空池」的两种成因必须分开（见模块 docstring）：早于「最早有跌停记录的那天」的
    # 空池只能是超窗口，其余是当天真的零跌停。两者都不产生样本，但读数含义完全不同 ——
    # 前者是数据缺陷，后者说明市场当天根本没有跌停股。
    first_covered = covered[0] if covered else None
    out_of_window = [d for d in empty if first_covered is not None and d < first_covered]
    zero_down = [d for d in empty if first_covered is not None and d > first_covered]
    data = {
        "caliber": calibers.describe("limitdown_repair"),
        "evidence": tactic_evidence.describe("limitdown_repair"),
        "days": days,
        "date_range": [trading_days[0].isoformat(), trading_days[-1].isoformat()] if trading_days else [],
        "data_window": [covered[0], covered[-1]] if covered else [],
        "effective_days": len(covered),
        "empty_dates": empty,
        "zero_down_dates": zero_down,
        "out_of_window_dates": out_of_window,
        "skipped_dates": skipped,
        "candidate_size": candidate_size,
        "sample_size": len(rows),
        "truncated": candidate_size > _MAX_SAMPLES,
        "overall": stats_of(rows),
        "by_sealed": by_sealed,
        "by_down_days": by_down_days,
        "by_cluster": by_cluster,
        "tail": tail,
        "worst": [_brief(r) for r in sorted(rows, key=lambda r: r["ret_open"])[:8]],
        "best": [_brief(r) for r in sorted(rows, key=lambda r: -r["ret_open"])[:8]],
    }
    cache_utils.put_bounded(_REPAIR_CACHE, cache_key, (now, data), max_entries=_SNAP_CACHE_MAX)
    return {**data, "cached": False}


def clear_caches() -> None:
    """清空模块缓存（测试与手动刷新用）。"""
    _SNAP_CACHE.clear()
    _REPAIR_CACHE.clear()
