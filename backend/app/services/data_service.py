"""A 股数据服务：行情/历史K线基于腾讯接口，新闻多源兜底（优先东方财富）。"""
from __future__ import annotations

import datetime as dt
import logging
import time
from typing import Any

import akshare as ak
import pandas as pd
import requests

from app.models import NewsItem, StockHistory, StockQuote

logger = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"


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
                )
            )
        except (ValueError, IndexError) as e:
            logger.warning("解析 %s 行情失败: %s", code, e)
            continue
    return quotes


def get_stock_name(code: str) -> str:
    quotes = get_spot_quote([code])
    return quotes[0].name if quotes else ""


def get_history(code: str, days: int = 120) -> StockHistory | None:
    """获取历史日 K 数据（腾讯接口）。"""
    end = dt.date.today()
    start = end - dt.timedelta(days=days * 2)
    try:
        df = ak.stock_zh_a_hist_tx(
            symbol=_code_to_symbol(code),
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
        )
        if df is None or df.empty:
            return None
        df = df.tail(days)
        return StockHistory(
            dates=[str(d)[:10] for d in df["date"]],
            closes=[float(x) for x in df["close"]],
            volumes=[float(x) for x in df["amount"]] if "amount" in df.columns else None,
        )
    except Exception as e:
        logger.warning("获取 %s 历史K线失败: %s", code, e)
        return None


def get_news(code: str, name: str, limit: int = 8) -> list[NewsItem]:
    """获取个股新闻：优先东方财富，失败则用市场快讯过滤兜底。"""
    try:
        df = ak.stock_news_em(symbol=code.strip())
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
        df = ak.stock_info_global_em()
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


def get_notices_today() -> dict[str, list[str]]:
    """东财当日全市场公告 -> {code: [公告标题, ...]}。60 分钟缓存，失败返回 {}。"""
    global _notice_cache
    now = time.time()
    if _notice_cache and now - _notice_cache[0] < 3600:
        return _notice_cache[1]
    out: dict[str, list[str]] = {}
    try:
        df = ak.stock_notice_report(symbol="全部", date=dt.date.today().strftime("%Y%m%d"))
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


def get_global_news(limit: int = 300) -> list[dict]:
    """全市场财经快讯（东财，一条请求覆盖所有个股），5 分钟缓存。"""
    global _global_news_cache
    now = time.time()
    if _global_news_cache and now - _global_news_cache[0] < 300:
        return _global_news_cache[1]
    rows: list[dict] = []
    try:
        df = ak.stock_info_global_em()
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
