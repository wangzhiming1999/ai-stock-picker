"""自选股服务：添加/删除/批量导入 + 实时涨跌看板。

与持仓(user_holdings)不同：自选是"关注但不一定持有"，主要用来跟踪涨跌。
后端用 service client 绕过 RLS，归属隔离由 user_id 保证。
"""
from __future__ import annotations

import asyncio
import datetime as dt

from app.services import data_service, supabase_store


def _require_configured():
    if not supabase_store.is_configured():
        raise RuntimeError("Supabase 未配置")


async def add_watch(user_id: str, code: str) -> dict:
    """添加一只自选（重复自动忽略）。"""
    _require_configured()
    code = code.strip()
    if not code or not code.isdigit() or len(code) != 6:
        raise ValueError("请输入有效的 6 位股票代码")

    name = ""
    try:
        quotes = await asyncio.to_thread(data_service.get_spot_quote, [code])
        if quotes:
            name = quotes[0].name or ""
    except Exception:
        pass

    sb = await supabase_store.get_service_client()
    # 幂等：已存在则忽略
    existing = (
        await sb.table("user_watchlist")
        .select("id")
        .eq("user_id", user_id)
        .eq("code", code)
        .limit(1)
        .execute()
    )
    if existing.data:
        return {"id": existing.data[0]["id"], "code": code, "name": name, "added": False}
    res = (
        await sb.table("user_watchlist")
        .insert({"user_id": user_id, "code": code, "name": name})
        .execute()
    )
    return {"id": res.data[0]["id"], "code": code, "name": name, "added": True}


async def import_watch(user_id: str, codes: list[str]) -> dict:
    """批量导入自选（跳过重复/非法）。"""
    _require_configured()
    added = 0
    skipped = 0
    errors: list[str] = []
    for code in codes:
        c = code.strip()
        if not c.isdigit() or len(c) != 6:
            skipped += 1
            continue
        try:
            res = await add_watch(user_id, c)
            added += 1 if res["added"] else 0
            if not res["added"]:
                skipped += 1
        except Exception as e:
            errors.append(str(e))
    return {"added": added, "skipped": skipped, "errors": errors[:5]}


async def list_watch(user_id: str) -> dict:
    """列出自选股（含实时行情：现价/涨跌/量比/换手等）。"""
    _require_configured()
    sb = await supabase_store.get_service_client()
    res = (
        await sb.table("user_watchlist")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return {"watchlist": [], "summary": None}

    codes = [r["code"] for r in rows]
    quotes = await asyncio.to_thread(data_service.get_spot_quote, codes)
    quote_map = {q.code: q for q in quotes}

    items = []
    up = down = flat = 0
    total_change = 0.0
    count = 0
    for r in rows:
        q = quote_map.get(r["code"])
        change = None
        if q:
            change = round(q.change_pct, 2)
            if q.change_pct > 0.01:
                up += 1
            elif q.change_pct < -0.01:
                down += 1
            else:
                flat += 1
            total_change += q.change_pct
            count += 1
        items.append(
            {
                **r,
                "price": q.price if q else None,
                "change_pct": change,
                "turnover": q.turnover if q else None,
                "volume": q.volume if q else None,
                "pe": q.pe if q else None,
                "market_cap": q.market_cap if q else None,
                "name": r.get("name") or (q.name if q else ""),
                "offline": q is None,
            }
        )

    return {
        "watchlist": items,
        "summary": {
            "total": len(items),
            "up": up,
            "down": down,
            "flat": flat,
            "avg_change": round(total_change / count, 2) if count else None,
        },
    }


async def remove_watch(user_id: str, watch_id: int) -> bool:
    """删除自选（按 id）。"""
    _require_configured()
    sb = await supabase_store.get_service_client()
    res = (
        await sb.table("user_watchlist")
        .delete()
        .eq("id", watch_id)
        .eq("user_id", user_id)
        .execute()
    )
    return bool(res.data)


async def is_watched(user_id: str, codes: list[str]) -> dict[str, bool]:
    """查询一批代码哪些已在自选（用于前端星标态）。"""
    if not supabase_store.is_configured() or not codes:
        return {}
    sb = await supabase_store.get_service_client()
    res = (
        await sb.table("user_watchlist")
        .select("code")
        .eq("user_id", user_id)
        .in_("code", codes)
        .execute()
    )
    out = {c: False for c in codes}
    for row in res.data or []:
        out[row["code"]] = True
    return out
