"""四维牛股榜：基本面/技术面/资金面/消息面 四维都优秀的 Top 10 股票。

每交易日懒生成一次，结果按最近交易日快照缓存到 Supabase `quad_snapshots` 表。

- 候选池：东财全市场快照 → 硬过滤（排除 ST/退市/亏损/微盘/异常波动）→ 初筛分取 Top N
- 技术分：MA5/MA20/MA60 多头、距年内高点、MACD、RSI、近 5 日涨幅
- 基本面分：PE/PB/市值
- 资金面分：换手率 / 量比 / 成交额 / 5 分钟涨跌
- 消息面分：新闻标题利好/利空关键词情绪
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import akshare as ak

from app.services import data_service, supabase_store, trade_calendar_service

# 当日内存缓存：key=交易日, value=(生成时间, data)
_quad_cache: dict[str, tuple[str, dict]] = {}
_FULL_SPOT_TTL = 60  # 全市场快照短缓存（秒）
_full_spot_cache: tuple[float, list[dict]] | None = None

DIM_KEYS = ["fundamental", "technical", "capital", "news"]
DIM_NAMES = {"fundamental": "基本面", "technical": "技术面", "capital": "资金面", "news": "消息面"}

# 消息面情绪关键词
_POS_KW = [
    "中标", "业绩预增", "业绩增长", "净利润增长", "签约", "回购", "增持", "获批", "突破",
    "涨价", "提价", "订单", "创新高", "涨停", "利好", "扩产", "上调", "超预期", "扭亏",
    "分红", "重组", "资产注入", "战略合作", "签署", "预增",
]
_NEG_KW = [
    "减持", "处罚", "亏损", "诉讼", "质押", "退市", "问询", "立案", "跌停", "风险提示",
    "商誉减值", "预亏", "下调", "违规", "警示", "炸板", "跳水", "违约", "冻结", "监管",
    "收监管", "公告解读", "利空",
]


def _clamp(v: float, lo: float = 0.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, v))


def _get_news_fast(code: str, limit: int = 6) -> list[dict]:
    """快速个股新闻：只调东财个股新闻，失败即空（跳过慢的全球快讯兜底）。

    供批量打分场景使用，避免 40 只逐一触发慢兜底拖垮整体生成。
    """
    try:
        df = ak.stock_news_em(symbol=code.strip())
        if df is None or df.empty:
            return []
        items = []
        for _, row in df.head(limit).iterrows():
            items.append(
                {
                    "title": str(row.get("新闻标题", "")).strip(),
                    "date": str(row.get("发布时间", "")).strip() or None,
                }
            )
        return items
    except Exception:
        return []


def _full_spot() -> list[dict]:
    """全市场实时快照（东财富字段，60s 缓存），失败降级腾讯。"""
    global _full_spot_cache
    now = time.monotonic()
    if _full_spot_cache and now - _full_spot_cache[0] < _FULL_SPOT_TTL:
        return _full_spot_cache[1]

    def _num(row: Any, *keys: str) -> float | None:
        for k in keys:
            v = row.get(k)
            if v is None:
                continue
            try:
                f = float(v)
                return f
            except (ValueError, TypeError):
                continue
        return None

    rows: list[dict] = []
    try:
        df = ak.stock_zh_a_spot_em()
        for _, row in df.iterrows():
            code = str(row.get("代码", "")).strip().replace("sh", "").replace("sz", "").replace("bj", "")
            if not code:
                continue
            rows.append(
                {
                    "code": code,
                    "name": str(row.get("名称", "")).strip(),
                    "price": _num(row, "最新价") or 0,
                    "change_pct": _num(row, "涨跌幅") or 0,
                    "amount_yi": (_num(row, "成交额") or 0) / 1e8,
                    "volume_ratio": _num(row, "量比"),
                    "turnover": _num(row, "换手率"),
                    "pe": _num(row, "市盈率-动态", "市盈率(动)", "市盈率-静态"),
                    "pb": _num(row, "市净率"),
                    "market_cap_yi": (_num(row, "总市值") or 0) / 1e8,
                    "change_5min": _num(row, "5分钟涨跌"),
                }
            )
    except Exception as e:
        print(f"[quad] 东财快照失败，降级腾讯: {e}")
        try:
            df = ak.stock_zh_a_spot()
            for _, row in df.iterrows():
                code = str(row["代码"]).replace("sh", "").replace("sz", "").replace("bj", "")
                if not code:
                    continue
                rows.append(
                    {
                        "code": code,
                        "name": str(row["名称"]).strip(),
                        "price": float(row["最新价"]),
                        "change_pct": float(row["涨跌幅"]),
                        "amount_yi": float(row["成交额"]) / 1e8 if row["成交额"] else 0,
                        "volume_ratio": None,
                        "turnover": None,
                        "pe": None,
                        "pb": None,
                        "market_cap_yi": None,
                        "change_5min": None,
                    }
                )
        except Exception as e2:
            print(f"[quad] 腾讯快照也失败: {e2}")
            rows = []
    _full_spot_cache = (now, rows)
    return rows


def _is_clean(name: str) -> bool:
    return not any(x in name for x in ("ST", "退", "N", "C"))


def _preselect(rows: list[dict], top_n: int = 40) -> list[dict]:
    """硬过滤 + 初筛打分，取最有可能四维俱佳的 Top N。

    若行情源缺 PE/PB/换手（腾讯老快照降级时），会先批量补充腾讯行情再精筛，
    保证候选不因原数据分组顺序而偏向单一交易所。
    """
    hard: list[dict] = []
    for r in rows:
        name = r["name"]
        price = r["price"]
        if not _is_clean(name):
            continue
        if r["code"].startswith(("4", "8", "920")):  # 排除北交所
            continue
        if not (2 <= price <= 300):
            continue
        if (r["amount_yi"] or 0) < 3:
            continue
        pe, pb, turnover, mc = r["pe"], r["pb"], r["turnover"], r["market_cap_yi"]
        if pe is not None and not (0 < pe <= 80):
            continue
        if pb is not None and not (0 < pb <= 12):
            continue
        if mc is not None and not (60 <= mc <= 3000):
            continue
        if turnover is not None and not (0.8 <= turnover <= 18):
            continue
        if not (-4 <= r["change_pct"] <= 9.5):
            continue
        hard.append(r)
    if not hard:
        return []

    # 腾讯老快照缺基本面字段：先按成交额收窄到前 250，批量补全后再精筛
    missing = sum(1 for x in hard if x.get("pe") is None)
    if missing > len(hard) // 2:
        hard.sort(key=lambda x: x["amount_yi"] or 0, reverse=True)
        hard = hard[:250]
        quotes_map: dict[str, Any] = {}
        for i in range(0, len(hard), 60):
            chunk_codes = [x["code"] for x in hard[i : i + 60]]
            try:
                for q in data_service.get_spot_quote(chunk_codes):
                    quotes_map[q.code] = q
            except Exception:
                continue
        filled = []
        for x in hard:
            q = quotes_map.get(x["code"])
            if not q:
                continue
            pe = q.pe
            pb = q.pb
            turnover = q.turnover
            if pe is not None and not (0 < pe <= 80):
                continue
            if pb is not None and not (0 < pb <= 12):
                continue
            if turnover is not None and not (0.8 <= turnover <= 18):
                continue
            x["pe"] = pe if pe is not None else x.get("pe")
            x["pb"] = pb if pb is not None else x.get("pb")
            x["turnover"] = turnover if turnover is not None else x.get("turnover")
            x["market_cap_yi"] = (q.market_cap / 1e8) if q.market_cap else x.get("market_cap_yi")
            filled.append(x)
        hard = filled

    pool: list[dict] = []
    for r in hard:
        pe = r["pe"]
        pb = r["pb"]
        turnover = r["turnover"]
        mc = r["market_cap_yi"]
        s = 0.0
        if pe and 0 < pe <= 30:
            s += 2
        elif pe and pe <= 45:
            s += 1
        if pb and 0 < pb <= 3:
            s += 1.5
        elif pb and pb <= 6:
            s += 0.5
        if turnover:
            if 3 <= turnover <= 8:
                s += 2
            elif 1 <= turnover <= 12:
                s += 1
        vr = r["volume_ratio"]
        if vr is not None and 0.8 <= vr <= 3:
            s += 1
        if 5 <= r["amount_yi"] <= 120:
            s += 0.5
        if 0 <= r["change_pct"] <= 7:
            s += 1
        if mc and 100 <= mc <= 1500:
            s += 0.5
        r["_pre_score"] = s
        pool.append(r)
    # 同分时成交额更大者优先，避免原数据分组顺序造成偏交易所
    pool.sort(key=lambda x: (x["_pre_score"], x["amount_yi"] or 0), reverse=True)
    return pool[:top_n]


# ---------------- 四维评分 ----------------

def _score_fundamental(quote) -> tuple[float, str]:
    """基本面：PE/PB/市值。"""
    base = 5.0
    parts: list[str] = []
    pe = quote.pe
    pb = quote.pb
    mc = quote.market_cap / 1e8 if quote.market_cap else None
    if pe is not None and pe > 0:
        if pe <= 15:
            base += 2.0
            parts.append(f"PE {pe:.1f} 低估值")
        elif pe <= 30:
            base += 1.5
            parts.append(f"PE {pe:.1f} 合理偏低")
        elif pe <= 45:
            parts.append(f"PE {pe:.1f} 合理")
        else:
            base -= 1.5
            parts.append(f"PE {pe:.1f} 偏高")
    if pb is not None and pb > 0:
        if pb <= 2:
            base += 1.0
            parts.append(f"PB {pb:.2f} 低")
        elif pb <= 6:
            parts.append(f"PB {pb:.2f} 合理")
        elif pb <= 10:
            base -= 1.0
            parts.append(f"PB {pb:.2f} 偏高")
        else:
            base -= 2.0
            parts.append(f"PB {pb:.2f} 高")
    if mc is not None:
        if mc >= 1000:
            base += 0.5
            parts.append("大盘蓝筹")
        elif mc >= 80:
            base += 0.5
            parts.append("中大市值")
        else:
            base -= 1.0
    return round(_clamp(base), 1), "；".join(parts) or "数据有限"


def _score_technical(closes: list[float], price: float) -> tuple[float, str]:
    """技术面：均线多头 / 距高点 / MACD / RSI / 短期涨幅。"""
    if not closes or len(closes) < 30:
        return 4.5, "K线数据不足"
    base = 5.0
    parts: list[str] = []

    def _ma(n: int) -> float:
        return sum(closes[-n:]) / n

    ma5, ma20, ma60 = _ma(5), _ma(min(20, len(closes))), _ma(min(60, len(closes)))
    # 均线排列
    if len(closes) >= 60 and ma5 > ma20 > ma60 and price > ma5:
        base += 2.5
        parts.append("均线多头排列")
    elif ma5 > ma20 and price > ma5:
        base += 1.5
        parts.append("短期均线多头")
    elif price < ma20:
        base -= 2.0
        parts.append("跌破MA20")
    # 距 120 日高点
    high = max(closes)
    pct_from_high = (price / high - 1) * 100
    if pct_from_high > -5:
        base += 1.5
        parts.append("贴近年内高点")
    elif pct_from_high > -18:
        base += 0.5
        parts.append("处于上行趋势")
    elif pct_from_high < -35:
        base -= 2.0
        parts.append("距高点较远")
    # MACD
    ema12, ema26 = closes[0], closes[0]
    difs: list[float] = []
    for c in closes:
        ema12 += (c - ema12) * 2 / 13
        ema26 += (c - ema26) * 2 / 27
        difs.append(ema12 - ema26)
    dea = sum(difs[-9:]) / 9
    if difs[-1] > dea:
        base += 1.0
        parts.append("MACD 金叉运行")
    else:
        base -= 1.0
    # RSI(14)
    gains, losses = [], []
    for i in range(1, 15):
        diff = closes[-14 + i] - closes[-15 + i]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    ag, al = sum(gains) / 14, sum(losses) / 14
    rsi = 100 - 100 / (1 + ag / al) if al > 0 else 100
    if 55 <= rsi <= 78:
        base += 1.0
        parts.append(f"RSI {rsi:.0f} 强势不超买")
    elif rsi > 88:
        base -= 1.5
        parts.append(f"RSI {rsi:.0f} 超买")
    elif rsi < 40:
        base -= 1.0
    # 近 5 日涨幅（不追过热）
    if len(closes) >= 6 and closes[-6]:
        r5 = (closes[-1] / closes[-6] - 1) * 100
        if 0 <= r5 <= 12:
            base += 0.5
            parts.append(f"近5日 +{r5:.1f}% 稳健")
        elif r5 > 20:
            base -= 1.5
            parts.append(f"近5日 +{r5:.1f}% 短期过热")
    return round(_clamp(base), 1), "；".join(parts) or "趋势中性"


def _score_capital(rich: dict, quote) -> tuple[float, str]:
    """资金面：换手率（按市值分层）/ 量比 / 成交额 / 5分钟涨跌。"""
    base = 5.0
    parts: list[str] = []
    mc = (quote.market_cap / 1e8) if quote.market_cap else (rich.get("market_cap_yi") or 0)
    is_mega = mc >= 800  # 大盘蓝筹天然低换手
    turnover = quote.turnover if quote.turnover is not None else rich.get("turnover")
    if turnover is not None:
        if is_mega:
            if 0.4 <= turnover <= 2:
                base += 1.5
                parts.append(f"换手 {turnover:.2f}% 蓝筹稳健")
            elif 2 < turnover <= 6:
                base += 1.0
                parts.append(f"换手 {turnover:.2f}% 活跃")
            elif turnover < 0.25:
                base -= 1.5
                parts.append(f"换手 {turnover:.2f}% 清淡")
            else:
                base -= 0.5
        else:
            if 3 <= turnover <= 8:
                base += 2.0
                parts.append(f"换手 {turnover:.1f}% 活跃健康")
            elif 1.5 <= turnover < 3:
                base += 1.5
                parts.append(f"换手 {turnover:.1f}% 温和活跃")
            elif 1 <= turnover < 1.5:
                parts.append(f"换手 {turnover:.1f}% 正常")
            elif 8 < turnover <= 15:
                base -= 0.5
                parts.append(f"换手 {turnover:.1f}% 偏高")
            else:
                base -= 1.5
                parts.append(f"换手 {turnover:.1f}% 异常")
    vr = rich.get("volume_ratio")
    if vr is not None:
        if 1 <= vr <= 2.5:
            base += 1.5
            parts.append(f"量比 {vr:.2f} 温和放量")
        elif 0.5 <= vr < 1:
            base -= 0.5
        elif 2.5 < vr <= 5:
            base += 0.5
        elif vr > 6:
            base -= 1.5
            parts.append(f"量比 {vr:.2f} 爆量")
    amount = rich.get("amount_yi") or 0
    if amount >= 20:
        base += 1.0
        parts.append(f"成交 {amount:.0f}亿 大资金")
    elif amount >= 5:
        base += 0.5
    c5 = rich.get("change_5min")
    if c5 is not None and c5 >= 0.3:
        base += 0.5
        parts.append("盘口走强")
    return round(_clamp(base), 1), "；".join(parts) or "交投数据有限"


def _score_news(news: list) -> tuple[float, str]:
    """消息面：新闻数量 + 利好/利空关键词情绪。无新闻记中性分。"""
    if not news:
        return 5.0, "近期无针对性新闻，中性"
    base = 5.0
    titles = [(n.get("title", "") if isinstance(n, dict) else getattr(n, "title", "")) for n in news]
    pos = sum(1 for t in titles if any(k in t for k in _POS_KW))
    neg = sum(1 for t in titles if any(k in t for k in _NEG_KW))
    if pos:
        base += min(2.5, 0.6 * pos)
    if neg:
        base -= min(3.0, 0.8 * neg)
    if pos > 0 and neg == 0:
        base += 0.5
    if pos == 0 and neg == 0 and len(titles) >= 3:
        base += 0.2
    hot = "近期消息活跃" if len(titles) >= 4 else f"近期 {len(titles)} 条相关新闻"
    senti = ""
    if neg and not pos:
        senti = "，偏利空需留意"
    elif pos and not neg:
        senti = "，情绪偏暖"
    return round(_clamp(base), 1), hot + senti


# ---------------- 榜单生成 ----------------

async def _score_one(code: str, name: str, rich: dict, sem: asyncio.Semaphore) -> dict | None:
    """对单只股票做四维深度评分。"""
    async def _bounded(fn, *args):
        async with sem:
            return await asyncio.to_thread(fn, *args)

    quote = None
    hist = None
    news = []
    # 腾讯行情（补全 PE/PB/市值/换手）
    try:
        quotes = await _bounded(data_service.get_spot_quote, [code])
        quote = quotes[0] if quotes else None
    except Exception:
        quote = None
    if quote is None:
        return None
    try:
        hist = await _bounded(data_service.get_history, code, 120)
    except Exception:
        hist = None
    try:
        news = await _bounded(_get_news_fast, code, 6)
    except Exception:
        news = []

    closes = hist.closes if hist and hist.closes else None
    price = quote.price or 0

    f_score, f_comment = _score_fundamental(quote)
    t_score, t_comment = _score_technical(closes, price)
    c_score, c_comment = _score_capital(rich, quote)
    n_score, n_comment = _score_news(news)

    scores = {
        "fundamental": round(f_score, 1),
        "technical": round(t_score, 1),
        "capital": round(c_score, 1),
        "news": round(n_score, 1),
    }
    overall = round(sum(scores.values()) / 4, 2)

    tags = []
    if all(v >= 8 for v in scores.values()):
        tags.append("四维共振")
    elif all(v >= 7 for v in scores.values()):
        tags.append("全维强势")
    elif t_score >= 7.5 and f_score >= 6.5:
        tags.append("趋势+估值")
    if c_score >= 8:
        tags.append("资金强")

    return {
        "code": code,
        "name": name,
        "price": round(price, 2),
        "change_pct": round(quote.change_pct or 0, 2),
        "turnover": round(quote.turnover, 2) if quote.turnover is not None else None,
        "pe": round(quote.pe, 1) if quote.pe else None,
        "market_cap_yi": round(quote.market_cap / 1e8, 1) if quote.market_cap else None,
        "overall_score": overall,
        "scores": scores,
        "tags": tags,
        "comments": {
            "fundamental": f_comment,
            "technical": t_comment,
            "capital": c_comment,
            "news": n_comment,
        },
    }


async def generate_quad_rankings(force_refresh: bool = False) -> dict:
    """生成四维牛股榜（每日懒生成 + DB 快照缓存）。"""
    today = await trade_calendar_service.last_trading_day()
    data_day = str(today)

    # 1. DB 缓存命中（非强制刷新）
    if not force_refresh:
        hit = await _load_db_quad(data_day)
        if hit:
            return hit

    spot = await asyncio.to_thread(_full_spot)
    if not spot:
        raise RuntimeError("获取全市场行情失败")

    pool = _preselect(spot, top_n=40)
    if not pool:
        raise RuntimeError("四维牛股候选池为空（今日全市场无符合条件标的）")

    sem = asyncio.Semaphore(12)
    scored = await asyncio.gather(
        *(_score_one(r["code"], r["name"], r, sem) for r in pool)
    )
    items = [x for x in scored if x]
    if not items:
        raise RuntimeError("候选股票评分失败")

    # 排序：高分维度数优先（四维都 >=7 的最靠前），再比整体分
    def _rank_key(x: dict):
        vals = list(x["scores"].values())
        return (
            sum(1 for v in vals if v >= 7),
            sum(1 for v in vals if v >= 6.5),
            round(sum(vals) / 4, 2),
        )

    items.sort(key=_rank_key, reverse=True)
    top10 = items[:10]
    for i, item in enumerate(top10):
        item["rank"] = i + 1

    strict_count = sum(1 for x in top10 if all(v >= 7 for v in x["scores"].values()))
    result = {
        "date": data_day,
        "source": "rule",
        "pool_size": len(pool),
        "strict_count": strict_count,
        "items": top10,
    }
    await _save_db_quad(data_day, result)
    _quad_cache[data_day] = (data_day, result)
    return result


async def get_quad_rankings(force_refresh: bool = False) -> dict:
    """入口：优先内存 → DB → 懒生成。"""
    today = await trade_calendar_service.last_trading_day()
    key = str(today)
    if not force_refresh:
        cached = _quad_cache.get(key)
        if cached:
            return cached[1]
    return await generate_quad_rankings(force_refresh=force_refresh)


# ---------------- DB 快照（复用 daily_recommend_snapshots 模式） ----------------

async def _load_db_quad(data_day: str) -> dict | None:
    if not supabase_store.is_configured():
        return None
    try:
        sb = await supabase_store.get_service_client()
        res = (
            await sb.table("quad_snapshots")
            .select("result")
            .eq("snapshot_date", data_day)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0]["result"]
    except Exception as e:
        print(f"[quad] DB 读取失败: {e}")
    return None


async def _save_db_quad(data_day: str, result: dict) -> None:
    if not supabase_store.is_configured():
        return
    try:
        sb = await supabase_store.get_service_client()
        existing = (
            await sb.table("quad_snapshots")
            .select("id")
            .eq("snapshot_date", data_day)
            .limit(1)
            .execute()
        )
        payload = {"snapshot_date": data_day, "result": result}
        if existing.data:
            await sb.table("quad_snapshots").update(payload).eq("id", existing.data[0]["id"]).execute()
        else:
            await sb.table("quad_snapshots").insert(payload).execute()
    except Exception as e:
        print(f"[quad] DB 保存失败: {e}")
