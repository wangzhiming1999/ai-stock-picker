"""早盘竞价 / 尾盘机会选股。

- 早盘竞价（9:15-9:30）：开盘强势、博当日大涨
- 尾盘机会（14:45-15:00）：尾盘异动、博次日高开

数据源：akshare 全市场实时快照（东财），短缓存 60s。
"""
from __future__ import annotations

import asyncio
import re
import time

import akshare as ak

from app.services import supabase_store

_SHORT_CACHE: dict[str, tuple[float, list[dict]]] = {}
_TTL = 60


async def _get_rich_spot(force: bool = False) -> list[dict]:
    """全市场实时快照（含量比/换手/委比/5分钟涨跌）。短缓存 60s。

    优先东财（em）含丰富字段；若网络/超时失败则 fallback 腾讯（基础字段）。
    force=True 时忽略缓存重新拉取（供「强制重跑」穿透底层快照缓存）。
    """
    key = "rich_spot"
    now = time.monotonic()
    if not force and key in _SHORT_CACHE and now - _SHORT_CACHE[key][0] < _TTL:
        return _SHORT_CACHE[key][1]

    rows: list[dict] = []
    # 优先东财接口（含 量比/换手/5分钟涨跌）
    try:
        df = await asyncio.to_thread(ak.stock_zh_a_spot_em)
        for _, row in df.iterrows():
            try:
                amount = float(row.get("成交额", 0))
                rows.append(
                    {
                        "code": str(row.get("代码", "")).replace("sh", "").replace("sz", "").replace("bj", ""),
                        "name": str(row.get("名称", "")).strip(),
                        "price": float(row.get("最新价", 0)),
                        "change_pct": float(row.get("涨跌幅", 0)),
                        "amount_yi": amount / 1e8,
                        "volume_ratio": float(row.get("量比", 0) or 0),
                        "turnover": float(row.get("换手率", 0) or 0),
                        "pe": float(row.get("市盈率(动)", 0) or 0),
                        "amplitude": float(row.get("振幅", 0) or 0),
                        "change_5min": float(row.get("5分钟涨跌", 0) or 0),
                    }
                )
            except (ValueError, TypeError):
                continue
    except Exception as e:
        # Fallback：腾讯基础接口（基础字段，量比/换手/5分钟涨跌不可用）
        try:
            df = await asyncio.to_thread(ak.stock_zh_a_spot)
            for _, row in df.iterrows():
                try:
                    amount = float(row.get("成交额", 0))
                    rows.append(
                        {
                            "code": str(row.get("代码", "")).replace("sh", "").replace("sz", "").replace("bj", ""),
                            "name": str(row.get("名称", "")).strip(),
                            "price": float(row.get("最新价", 0)),
                            "change_pct": float(row.get("涨跌幅", 0)),
                            "amount_yi": amount / 1e8,
                            "volume_ratio": 0,
                            "turnover": 0,
                            "pe": 0,
                            "amplitude": float(row.get("振幅", 0) or 0),
                            "change_5min": 0,
                        }
                    )
                except (ValueError, TypeError):
                    continue
        except Exception as e2:
            raise RuntimeError(f"获取全市场快照失败: {e2}")

    _SHORT_CACHE[key] = (now, rows)
    return rows


_ST_NAME = re.compile("ST|\*ST")


def _is_valid_name(name: str) -> bool:
    return bool(name) and not _ST_NAME.search(name)


async def get_auction_opportunity(limit: int = 15, force: bool = False) -> list[dict]:
    """早盘竞价机会（9:15-9:30），目标：当日大涨。

    优先读 DB 缓存；没有且 force=False 时返回空列表（让前端引导用户触发）。
    """
    items, _cached = await _get_or_scan_opportunity("auction", limit=limit, force=force)
    return items


async def get_closing_opportunity(limit: int = 15, force: bool = False) -> list[dict]:
    """尾盘机会（14:45-15:00），目标：次日高开/继续上涨。优先读 DB 缓存。"""
    items, _cached = await _get_or_scan_opportunity("closing", limit=limit, force=force)
    return items


async def _get_or_scan_opportunity(stage: str, limit: int, force: bool) -> tuple[list[dict], bool]:
    """缓存读取 + 计算的统一入口。返回 (items, cached)。"""
    if not force:
        cached = await _load_cache(stage)
        if cached is not None:
            return cached[:limit], True
    items = await _scan_opportunity(stage, limit, force=force)
    if items:
        await _save_cache(stage, items, source="manual" if force else "auto")
    return items, False


def _auction_filter(rows: list[dict], limit: int) -> list[dict]:
    """早盘竞价筛选逻辑。"""
    out = []
    for r in rows:
        try:
            if not _is_valid_name(r["name"]):
                continue
            price = r["price"]
            change = r["change_pct"]
            amount_yi = r["amount_yi"]
            vol_ratio = r["volume_ratio"]
            if not (2 <= price <= 200):
                continue
            if abs(change) < 1.5 or abs(change) >= 9.5:
                continue
            if vol_ratio and vol_ratio < 1.5:
                continue
            if amount_yi < 0.5:
                continue
            if vol_ratio > 0:
                score = change * 0.6 + vol_ratio * 0.4
            else:
                score = change
            out.append({**r, "score": round(score, 2), "stage": "auction"})
        except (KeyError, TypeError):
            continue
    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:limit]


def _closing_filter(rows: list[dict], limit: int) -> list[dict]:
    """尾盘筛选逻辑。"""
    out = []
    for r in rows:
        try:
            if not _is_valid_name(r["name"]):
                continue
            price = r["price"]
            change = r["change_pct"]
            amount_yi = r["amount_yi"]
            vol_ratio = r["volume_ratio"]
            turnover = r["turnover"]
            change_5min = r["change_5min"]
            if not (2 <= price <= 300):
                continue
            if not (0.2 <= change <= 6):
                continue
            if vol_ratio and vol_ratio < 1.5:
                continue
            if turnover and turnover < 1.5:
                continue
            if change_5min and change_5min < 0.3:
                continue
            if amount_yi < 1:
                continue
            score = (
                change * 0.5
                + (change_5min if change_5min > 0 else 0) * 0.3
                + (vol_ratio if vol_ratio > 0 else 0) * 0.2
            )
            out.append({**r, "score": round(score, 2), "stage": "closing"})
        except (KeyError, TypeError):
            continue
    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:limit]


async def _scan_opportunity(stage: str, limit: int, force: bool = False) -> list[dict]:
    """实际扫描：拉全市场快照并按 stage 筛选。force 时穿透快照短缓存。"""
    try:
        rows = await _get_rich_spot(force=force)
    except Exception as e:
        raise RuntimeError(f"获取全市场快照失败: {e}")
    if stage == "auction":
        return _auction_filter(rows, limit)
    if stage == "closing":
        return _closing_filter(rows, limit)
    return []


# ---------- 缓存 DB 读/写 ----------

async def _load_cache(stage: str) -> list[dict] | None:
    """读取今日缓存。无缓存返回 None。"""
    from app.services import trade_calendar_service

    if not supabase_store.is_configured():
        return None
    trade_date = (await trade_calendar_service.last_trading_day()).isoformat()
    try:
        sb = await supabase_store.get_service_client()
        res = (
            await sb.table("opportunity_cache")
            .select("items")
            .eq("stage", stage)
            .eq("trade_date", trade_date)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0]["items"]
    except Exception as e:
        print(f"[opportunity] 缓存读取失败: {e}")
    return None


async def _save_cache(stage: str, items: list[dict], source: str = "auto") -> None:
    """写入今日缓存（upsert）。"""
    from app.services import trade_calendar_service

    if not supabase_store.is_configured() or not items:
        return
    trade_date = (await trade_calendar_service.last_trading_day()).isoformat()
    try:
        sb = await supabase_store.get_service_client()
        # upsert
        existing = (
            await sb.table("opportunity_cache")
            .select("id")
            .eq("stage", stage)
            .eq("trade_date", trade_date)
            .limit(1)
            .execute()
        )
        payload = {
            "stage": stage,
            "trade_date": trade_date,
            "items": items,
            "count": len(items),
            "source": source,
        }
        if existing.data:
            await sb.table("opportunity_cache").update(payload).eq("id", existing.data[0]["id"]).execute()
        else:
            await sb.table("opportunity_cache").insert(payload).execute()
    except Exception as e:
        print(f"[opportunity] 缓存写入失败: {e}")


# ---------- 带元数据的 detail 版本（接口层使用） ----------

async def get_auction_opportunity_detail(limit: int = 15, force: bool = False) -> dict:
    """早盘竞价：返回 items + needs_scan + cached 元数据。"""
    return await _opportunity_detail("auction", limit=limit, force=force)


async def get_closing_opportunity_detail(limit: int = 15, force: bool = False) -> dict:
    """尾盘：返回 items + needs_scan + cached 元数据。"""
    return await _opportunity_detail("closing", limit=limit, force=force)


async def _opportunity_detail(stage: str, limit: int, force: bool) -> dict:
    """带元数据的统一接口。"""
    from app.services import trade_calendar_service

    stage_label = "早盘竞价 9:15-9:30" if stage == "auction" else "尾盘 14:45-15:00"
    goal = "博当日大涨" if stage == "auction" else "博次日高开"
    if not force:
        cached = await _load_cache_meta(stage)
        if cached:
            return {
                "stage": stage,
                "stage_label": stage_label,
                "goal": goal,
                "items": cached["items"][:limit],
                "cached": True,
                "needs_scan": False,
                "trade_date": cached["trade_date"],
                "generated_at": cached["generated_at"],
                "source": "cache",
                "count": cached["count"],
            }
    # 没缓存或强制刷新
    items, was_cached = await _get_or_scan_opportunity(stage, limit=limit, force=force)
    trade_date = (await trade_calendar_service.last_trading_day()).isoformat()
    return {
        "stage": stage,
        "stage_label": stage_label,
        "goal": goal,
        "items": items,
        "cached": was_cached,
        "needs_scan": not items,
        "trade_date": trade_date,
        "generated_at": None if not items else None,
        "source": "cache" if was_cached else "live",
        "count": len(items),
    }


async def _load_cache_meta(stage: str) -> dict | None:
    """读今日缓存（含元数据：trade_date, generated_at, count, items）。"""
    from app.services import trade_calendar_service

    if not supabase_store.is_configured():
        return None
    trade_date = (await trade_calendar_service.last_trading_day()).isoformat()
    try:
        sb = await supabase_store.get_service_client()
        res = (
            await sb.table("opportunity_cache")
            .select("items, generated_at, count")
            .eq("stage", stage)
            .eq("trade_date", trade_date)
            .limit(1)
            .execute()
        )
        if res.data:
            row = res.data[0]
            return {
                "items": row["items"] or [],
                "trade_date": trade_date,
                "generated_at": row["generated_at"],
                "count": row["count"] or 0,
            }
    except Exception as e:
        print(f"[opportunity] 缓存读取失败: {e}")
    return None


async def get_closing_opportunity(limit: int = 15, force: bool = False) -> list[dict]:
    """（兼容旧调用）尾盘机会，结果由上方 detail 版本管理；优先缓存。"""
    items, _cached = await _get_or_scan_opportunity("closing", limit=limit, force=force)
    return items