"""A股交易日历服务：交易日识别 + 交易时段 + T日/T+1日 映射。

时间在股票分析里极其敏感，学同花顺/指南针的做法：
- 缓存/预测/推荐都按"交易日"对齐，而不是自然日
- "明日" = 下一个交易日（自动跳过周末和法定节假日）
- 交易时段区分：盘前/集合竞价/早盘/午休/午后/尾盘/收盘后
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging

import akshare as ak
import pandas as pd

from app.services import supabase_store

logger = logging.getLogger(__name__)

# 时区：A股以北京时间（UTC+8）为准
CN_TZ = dt.timezone(dt.timedelta(hours=8))

# 交易时段边界（北京时间）
OPEN = dt.time(9, 30)
MORNING_CLOSE = dt.time(11, 30)
AFTERNOON_OPEN = dt.time(13, 0)
CLOSE = dt.time(15, 0)
AUCTION_START = dt.time(9, 15)
AUCTION_END = dt.time(9, 30)  # 集合竞价结束（连续竞价开始）
TAIL_START = dt.time(14, 45)  # 尾盘


def now_cn() -> dt.datetime:
    """当前北京时间。"""
    return dt.datetime.now(CN_TZ)


def is_trading_day(date: dt.date | None = None) -> bool:
    """判断某天是否交易日（同步版：仅排除周末；精确节假日需查 DB）。

    盘内调用极频繁，先做快速周末判断（>90% 的情况）。
    若要精确排除节假日，调用 async is_trading_day_exact。
    """
    d = date or now_cn().date()
    return d.weekday() < 5


async def is_trading_day_exact(date: dt.date | None = None) -> bool:
    """精确判断：查 trade_calendar 表（akshare 节假日数据）。"""
    d = date or now_cn().date()
    if d.weekday() >= 5:
        return False
    cal = await _get_calendar()
    return cal.get(d.isoformat(), True)


async def last_trading_day(date: dt.date | None = None) -> dt.date:
    """最近的已过交易日（若 date 是交易日则返回它，否则往前找）。"""
    d = date or now_cn().date()
    cal = await _get_calendar()
    for _ in range(20):
        if cal.get(d.isoformat(), d.weekday() < 5):
            return d
        d -= dt.timedelta(days=1)
    # fallback：纯周末推断
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


async def next_trading_day(date: dt.date | None = None) -> dt.date:
    """下一个交易日（严格往后找，date 本身不算）。"""
    d = date or now_cn().date()
    cal = await _get_calendar()
    d += dt.timedelta(days=1)
    for _ in range(20):
        if cal.get(d.isoformat(), d.weekday() < 5):
            return d
        d += dt.timedelta(days=1)
    # fallback
    while d.weekday() >= 5:
        d += dt.timedelta(days=1)
    return d


def session_label() -> str:
    """当前交易时段标识（北京时间）。"""
    t = now_cn()
    if t.weekday() >= 5:
        return "休市"
    tm = t.time()
    if tm < AUCTION_START:
        return "盘前"
    if tm < AUCTION_END:
        return "集合竞价"
    if tm <= MORNING_CLOSE:
        return "早盘"
    if tm < AFTERNOON_OPEN:
        return "午休"
    if tm < TAIL_START:
        return "午后"
    if tm < CLOSE:
        return "尾盘"
    return "收盘后"


def is_after_close() -> bool:
    """是否已收盘（北京时间 15:00 后）。"""
    return now_cn().time() >= CLOSE


# ---------- 日历持久化 ----------

_calendar_cache: dict[str, bool] | None = None


async def _get_calendar() -> dict[str, bool]:
    """获取交易日历（date.isoformat -> is_trading），DB 缓存 + 本地缓存。

    覆盖范围：当前年份 ±2 年。DB 有则读；没有则 akshare 拉取全量交易日写入。
    """
    global _calendar_cache
    if _calendar_cache is not None and _calendar_cache:
        return _calendar_cache

    cal: dict[str, bool] = {}
    if supabase_store.is_configured():
        sb = await supabase_store.get_service_client()
        try:
            year = now_cn().year
            start, end = f"{year - 1}-01-01", f"{year + 2}-12-31"
            res = (
                await sb.table("trade_calendar")
                .select("date", "is_trading")
                .gte("date", start)
                .lte("date", end)
                .execute()
            )
            if res.data and len(res.data) > 200:
                for row in res.data:
                    cal[row["date"][:10]] = bool(row["is_trading"])
                _calendar_cache = cal
                return cal
        except Exception as e:
            logger.warning("读取交易日历失败: %s", e)

    # akshare 拉取全量交易日（含未来），生成完整日历（含非交易日 False）
    try:
        df = await asyncio.to_thread(ak.tool_trade_date_hist_sina)
        trade_set = {str(d)[:10] for d in df["trade_date"].tolist()}
        # 覆盖最近 ~5 年（akshare 数据从 1990 开始到未来）
        if trade_set:
            all_days = pd.date_range(
                f"{now_cn().year - 2}-01-01", f"{now_cn().year + 2}-12-31", freq="D"
            )
            cal = {d.strftime("%Y-%m-%d"): d.strftime("%Y-%m-%d") in trade_set for d in all_days}
        if supabase_store.is_configured():
            sb = await supabase_store.get_service_client()
            rows = [{"date": d, "is_trading": v} for d, v in cal.items()]
            # upsert（按批次）
            for i in range(0, len(rows), 500):
                await sb.table("trade_calendar").upsert(rows[i : i + 500]).execute()
        _calendar_cache = cal
        logger.info("交易日历已拉取并写入: %d 天", len(cal))
    except Exception as e:
        logger.warning("akshare 拉取交易日历失败，用周末推断兜底: %s", e)
        # 纯周末推断兜底（无法排除节假日但保证周末正确）；同样写缓存避免每次请求重试
        d = dt.date(now_cn().year - 2, 1, 1)
        while d <= dt.date(now_cn().year + 2, 12, 31):
            cal[d.isoformat()] = d.weekday() < 5
            d += dt.timedelta(days=1)
        _calendar_cache = cal
    return cal


async def clear_calendar_cache() -> None:
    global _calendar_cache
    _calendar_cache = None
