"""A 股数据服务：行情/历史K线基于腾讯接口，新闻多源兜底（优先东方财富）。"""
from __future__ import annotations

import datetime as dt
import json
import logging
import time
from typing import Any

import akshare as ak
import pandas as pd
import requests

from app.models import NewsItem, StockHistory, StockQuote
from app.services import akshare_guard

logger = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
_CN_TZ = dt.timezone(dt.timedelta(hours=8))


def _parse_qq_quote_time(raw: str | None) -> str | None:
    """解析腾讯行情时间；字段异常时只降级为未知时间，不丢弃整条行情。"""
    if not raw or len(raw) != 14:
        return None
    try:
        return (
            dt.datetime.strptime(raw, "%Y%m%d%H%M%S")
            .replace(tzinfo=_CN_TZ)
            .isoformat(timespec="seconds")
        )
    except ValueError:
        return None


def _code_to_symbol(code: str) -> str:
    """600519 -> sh600519；若已带 sh/sz/bj 前缀则原样返回（幂等）。"""
    code = code.strip().lower()
    if code.startswith(("sh", "sz", "bj")):
        return code
    if code.startswith(("6", "9")):
        return f"sh{code}"
    return f"sz{code}"


def _fetch_qq_spot(codes: list[str]) -> dict[str, list[str]]:
    """从腾讯行情接口拉取个股快照（原始字段数组）。"""
    symbols = ",".join(_code_to_symbol(c) for c in codes)
    url = f"https://qt.gtimg.cn/q={symbols}"
    try:
        resp = requests.get(url, headers={"User-Agent": _UA, "Referer": "https://gu.qq.com/"}, timeout=10)
        resp.encoding = "gbk"
        result: dict[str, list[str]] = {}
        for line in resp.text.strip().split(";"):
            line = line.strip()
            if "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip().strip("v_")
            val = val.strip().strip('"')
            result[key] = val.split("~")
        return result
    except Exception as e:
        logger.warning("腾讯行情接口失败: %s", e)
        return {}


def get_spot_quote(codes: list[str]) -> list[StockQuote]:
    """获取多只股票的实时行情快照（腾讯接口，字段更全）。"""
    quotes: list[StockQuote] = []
    raw = _fetch_qq_spot(codes)
    for code in codes:
        key = _code_to_symbol(code)
        fields = raw.get(key)
        if not fields or len(fields) < 48:
            continue
        try:
            price = float(fields[3] or 0)
            change_pct = float(fields[32] or 0)
            quotes.append(
                StockQuote(
                    code=code.strip(),
                    name=fields[1] or "",
                    price=price,
                    change_pct=change_pct,
                    turnover=float(fields[38]) if fields[38] else None,   # 换手率 %
                    volume=float(fields[36]) if fields[36] else None,      # 成交量 手
                    pe=float(fields[39]) if fields[39] else None,          # 市盈率
                    pb=float(fields[46]) if fields[46] else None,          # 市净率
                    market_cap=float(fields[45]) * 1e8 if fields[45] else None,  # 总市值 亿->元
                    # 腾讯行情字段 30 为服务端成交时间（YYYYMMDDHHMMSS）。保留真实行情时间，
                    # 避免上层把“接口请求完成时间”误当成行情新鲜度。
                    quote_time=_parse_qq_quote_time(fields[30] if len(fields) > 30 else None),
                )
            )
        except (ValueError, IndexError) as e:
            logger.warning("解析 %s 行情失败: %s", code, e)
            continue
    return quotes


def get_stock_name(code: str) -> str:
    quotes = get_spot_quote([code])
    return quotes[0].name if quotes else ""


# ---------------- 历史 K 线缓存 ----------------
# K 线盘中变化很小（只有当日那根在动），但每只票一次 akshare 请求要 1~4s，
# 简报(6只)/个股详情/持仓建议/盯盘都会重复拉取，是首屏延迟的主要来源。
# 成功缓存 5 分钟，失败短缓存 30s（避免瞬时故障被反复重试放大）。
_hist_cache: dict[tuple[str, int], tuple[float, StockHistory | None]] = {}
_HIST_TTL_OK = 300
_HIST_TTL_FAIL = 30
_HIST_CACHE_MAX = 400


def _parse_qq_history_payload(payload: dict, symbol: str, days: int) -> StockHistory | None:
    """校验并解析腾讯 K 线响应。第三方响应异常时返回 None。"""
    try:
        node = payload.get("data", {}).get(symbol, {})
        rows = node.get("qfqday") or node.get("day") or node.get("hfqday") or []
        if not isinstance(rows, list):
            return None
        valid = []
        for row in rows[-days:]:
            if not isinstance(row, list) or len(row) < 6:
                continue
            date = str(row[0])[:10]
            close = float(row[2])
            volume = float(row[5])
            if close <= 0:
                continue
            valid.append((date, close, volume))
        if not valid:
            return None
        return StockHistory(
            dates=[row[0] for row in valid],
            closes=[row[1] for row in valid],
            volumes=[row[2] for row in valid],
        )
    except (AttributeError, TypeError, ValueError, KeyError, IndexError):
        return None


def _fetch_history(code: str, days: int) -> StockHistory | None:
    """直接拉取腾讯历史日 K，避免 AkShare 的 JS 解析器导致进程级崩溃。"""
    symbol = _code_to_symbol(code)
    url = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"
    params = {"param": f"{symbol},day,,,{max(days, 60)},qfq", "_var": "kline_dayqfq"}
    try:
        resp = requests.get(url, params=params, headers={"User-Agent": _UA, "Referer": "https://gu.qq.com/"}, timeout=10)
        resp.raise_for_status()
        text = resp.text.strip()
        json_start = text.find("{")
        if json_start < 0:
            return None
        return _parse_qq_history_payload(json.loads(text[json_start:]), symbol, days)
    except (requests.RequestException, json.JSONDecodeError) as e:
        logger.warning("获取 %s 历史K线失败: %s", code, e)
        return None


def get_history(code: str, days: int = 120) -> StockHistory | None:
    """获取历史日 K 数据（腾讯接口），带 TTL 缓存。"""
    key = (code, days)
    now = time.time()
    hit = _hist_cache.get(key)
    if hit:
        cached_at, cached_val = hit
        ttl = _HIST_TTL_OK if cached_val is not None else _HIST_TTL_FAIL
        if now - cached_at < ttl:
            return cached_val

    result = _fetch_history(code, days)

    # 容量控制：超过上限淘汰最旧的一半，避免 serverless 实例内存无限增长
    if len(_hist_cache) >= _HIST_CACHE_MAX:
        for k in sorted(_hist_cache, key=lambda k: _hist_cache[k][0])[: _HIST_CACHE_MAX // 2]:
            _hist_cache.pop(k, None)
    _hist_cache[key] = (now, result)
    return result


# ---------------- 分钟 K 线缓存 ----------------
# 分钟线盘中每根都会变（5 分钟线每 5 分钟新增一根），缓存要远短于日线：
# 盘中 60s、休市 600s（收盘后当日分钟线不再变化），失败 30s。
_MIN_TTL_TRADING = 60
_MIN_TTL_CLOSED = 600
_MIN_TTL_FAIL = 30
_min_cache: dict[tuple[str, str, int], tuple[float, StockHistory | None]] = {}
_MIN_CACHE_MAX = 300

# 前端周期 -> 腾讯 mkline 周期参数
_QQ_MIN_PERIOD = {"1m": "m1", "5m": "m5", "15m": "m15", "30m": "m30", "60m": "m60"}
# 各周期 320 根覆盖的跨度：5m≈5天 / 15m≈15天 / 30m≈30天 / 60m≈60天
_MIN_DEFAULT_LIMIT = 320


def _is_trading_now(now: dt.datetime | None = None) -> bool:
    """是否处于 A 股连续竞价时段（决定分钟线缓存时长）。"""
    now = now or dt.datetime.now(dt.timezone.utc).astimezone(_CN_TZ)
    if now.weekday() >= 5:
        return False
    t = now.time()
    return dt.time(9, 30) <= t <= dt.time(11, 30) or dt.time(13, 0) <= t <= dt.time(15, 0)


def _parse_qq_min_payload(payload: dict, symbol: str, period: str, limit: int) -> StockHistory | None:
    """解析腾讯分钟 K 线：行结构 [时间, open, close, high, low, volume, ...]。"""
    try:
        node = payload.get("data", {}).get(symbol, {}) or {}
        rows = node.get(_QQ_MIN_PERIOD.get(period, "m5")) or []
        if not isinstance(rows, list):
            return None
        dates: list[str] = []
        opens: list[float] = []
        highs: list[float] = []
        lows: list[float] = []
        closes: list[float] = []
        volumes: list[float] = []
        for row in rows[-limit:]:
            if not isinstance(row, list) or len(row) < 6:
                continue
            try:
                o = float(row[1])
                c = float(row[2])
                h = float(row[3])
                lo = float(row[4])
                v = float(row[5] or 0)
            except (TypeError, ValueError):
                continue
            if c <= 0 or h <= 0 or lo <= 0:
                continue
            dates.append(str(row[0]))
            opens.append(o)
            closes.append(c)
            highs.append(h)
            lows.append(lo)
            volumes.append(v)
        if not closes:
            return None
        return StockHistory(
            dates=dates,
            closes=closes,
            volumes=volumes,
            opens=opens,
            highs=highs,
            lows=lows,
        )
    except (AttributeError, TypeError, ValueError, KeyError, IndexError):
        return None


def _fetch_intraday(code: str, period: str = "5m", limit: int = _MIN_DEFAULT_LIMIT) -> StockHistory | None:
    """拉取腾讯分钟 K 线（含 OHLC），供日内多周期决策使用。"""
    symbol = _code_to_symbol(code)
    qq_period = _QQ_MIN_PERIOD.get(period)
    if not qq_period:
        return None
    url = "https://ifzq.gtimg.cn/appstock/app/kline/mkline"
    params = {"param": f"{symbol},{qq_period},,{limit}"}
    try:
        resp = requests.get(
            url,
            params=params,
            headers={"User-Agent": _UA, "Referer": "https://gu.qq.com/"},
            timeout=10,
        )
        resp.raise_for_status()
        return _parse_qq_min_payload(resp.json(), symbol, period, limit)
    except (requests.RequestException, ValueError) as e:
        logger.warning("获取 %s %s 分钟K线失败: %s", code, period, e)
        return None


def get_intraday_history(code: str, period: str = "5m", limit: int = _MIN_DEFAULT_LIMIT) -> StockHistory | None:
    """获取分钟 K 线（腾讯接口），盘中/休市差异化 TTL 缓存。"""
    key = (code, period, limit)
    now = time.time()
    hit = _min_cache.get(key)
    if hit:
        cached_at, cached_val = hit
        ttl = _MIN_TTL_FAIL if cached_val is None else (_MIN_TTL_TRADING if _is_trading_now() else _MIN_TTL_CLOSED)
        if now - cached_at < ttl:
            return cached_val

    result = _fetch_intraday(code, period, limit)

    if len(_min_cache) >= _MIN_CACHE_MAX:
        for k in sorted(_min_cache, key=lambda k: _min_cache[k][0])[: _MIN_CACHE_MAX // 2]:
            _min_cache.pop(k, None)
    _min_cache[key] = (now, result)
    return result


def get_news(code: str, name: str, limit: int = 8) -> list[NewsItem]:
    """获取个股新闻：优先东方财富，失败则用市场快讯过滤兜底。"""
    try:
        df = akshare_guard.call(ak.stock_news_em, symbol=code.strip())
        if df is not None and not df.empty:
            items: list[NewsItem] = []
            for _, row in df.head(limit).iterrows():
                items.append(
                    NewsItem(
                        title=str(row.get("新闻标题", "")).strip(),
                        url=str(row.get("新闻链接", "")).strip() or None,
                        date=str(row.get("发布时间", "")).strip() or None,
                        source="东方财富",
                    )
                )
            return items
    except Exception as e:
        logger.debug("东方财富个股新闻不可用(%s)，尝试兜底", e)

    # 兜底：全市场财经快讯按关键词过滤
    try:
        df = akshare_guard.call(ak.stock_info_global_em)
        if df is None or df.empty:
            return []
        keywords = [code.strip()]
        if name:
            keywords.append(name.replace(" ", ""))
        mask = df["标题"].astype(str).str.contains("|".join(keywords), na=False)
        matched = df[mask]
        if matched.empty:
            return []
        items = []
        for _, row in matched.head(limit).iterrows():
            items.append(
                NewsItem(
                    title=str(row.get("标题", "")).strip(),
                    url=str(row.get("链接", "")).strip() or None,
                    date=str(row.get("发布时间", "")).strip() or None,
                    source="财经快讯",
                )
            )
        return items
    except Exception as e:
        logger.debug("新闻兜底源失败: %s", e)
        return []


# ---------------- 全局预拉数据（公告 / 财经快讯，供批量场景一次请求覆盖全部候选） ----------------

_notice_cache: tuple[float, dict[str, list[str]]] | None = None


def get_notices_today(force: bool = False) -> dict[str, list[str]]:
    """东财当日全市场公告 -> {code: [公告标题, ...]}。60 分钟缓存，失败返回 {}。

    force=True 时忽略缓存重新拉取（供「强制刷新」穿透）。
    """
    global _notice_cache
    now = time.time()
    if not force and _notice_cache and now - _notice_cache[0] < 3600:
        return _notice_cache[1]
    out: dict[str, list[str]] = {}
    try:
        df = akshare_guard.call(ak.stock_notice_report, symbol="全部", date=dt.date.today().strftime("%Y%m%d"))
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                code = (
                    str(row.get("代码", "")).strip().replace("sh", "").replace("sz", "").replace("bj", "")
                )
                title = str(row.get("公告标题", "")).strip()
                if code and code.isdigit() and title:
                    out.setdefault(code, []).append(title)
    except Exception as e:
        logger.warning("获取当日公告失败: %s", e)
    _notice_cache = (now, out)
    return out


_global_news_cache: tuple[float, list[dict]] | None = None


def get_global_news(limit: int = 300, force: bool = False) -> list[dict]:
    """全市场财经快讯（东财，一条请求覆盖所有个股），5 分钟缓存。

    force=True 时忽略缓存重新拉取（供「强制刷新」穿透）。
    """
    global _global_news_cache
    now = time.time()
    if not force and _global_news_cache and now - _global_news_cache[0] < 300:
        return _global_news_cache[1]
    rows: list[dict] = []
    try:
        df = akshare_guard.call(ak.stock_info_global_em)
        if df is not None and not df.empty:
            for _, row in df.head(limit).iterrows():
                rows.append(
                    {
                        "title": str(row.get("标题", "")).strip(),
                        "date": str(row.get("发布时间", "")).strip() or None,
                    }
                )
    except Exception as e:
        logger.warning("获取财经快讯失败: %s", e)
    _global_news_cache = (now, rows)
    return rows


def format_market_cap(v: float | None) -> str:
    """市值格式化（亿元）"""
    if not v:
        return "-"
    return f"{v / 1e8:.0f}亿"


def build_stock_context(quote: StockQuote, history: StockHistory | None, news: list[NewsItem]) -> str:
    """组装给 LLM 的个股上下文文本。"""
    lines: list[str] = []
    lines.append(f"股票：{quote.name}（{quote.code}）")
    lines.append(
        f"最新价 {quote.price:.2f} 元，涨跌幅 {quote.change_pct:+.2f}%"
        + (f"，换手率 {quote.turnover:.2f}%" if quote.turnover else "")
        + (f"，市盈率 {quote.pe:.1f}" if quote.pe else "")
        + (f"，市净率 {quote.pb:.2f}" if quote.pb else "")
        + (f"，总市值 {format_market_cap(quote.market_cap)}" if quote.market_cap else "")
    )

    if history and history.closes:
        closes = history.closes
        ma5 = sum(closes[-5:]) / len(closes[-5:])
        ma20 = sum(closes[-20:]) / len(closes[-20:])
        ma60 = sum(closes[-60:]) / len(closes[-60:]) if len(closes) >= 60 else None
        high = max(closes)
        low = min(closes)
        recent_ret = (closes[-1] / closes[0] - 1) * 100 if closes[0] else 0
        lines.append(
            f"近{len(closes)}日走势：MA5={ma5:.2f}，MA20={ma20:.2f}"
            + (f"，MA60={ma60:.2f}" if ma60 else "")
            + f"，区间最高 {high:.2f}，最低 {low:.2f}，期间涨幅 {recent_ret:+.1f}%"
        )
        if len(closes) >= 6:
            last5 = (closes[-1] / closes[-6] - 1) * 100
            lines.append(f"近5日涨幅 {last5:+.1f}%")

    if news:
        lines.append("最新新闻：")
        for n in news[:5]:
            lines.append(f"  - {n.date or ''} {n.title}")

    return "\n".join(lines)
