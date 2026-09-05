"""价格预警中心：用户规则（持仓止损 / 目标价 / 破位）+ 事件落库。

触发双通道：
- 前端盯盘轮询驱动 `evaluate_for_user`（保证 5 分钟高频）
- Vercel Cron 兜底 `evaluate_all`（用户关机也记历史）

规则类型与触发方向：
- stop_loss:   现价 <= threshold  → 止损提醒
- breakdown:   现价 <= threshold  → 破位提醒
- price_target:现价 >= threshold  → 到价/止盈提醒
"""
from __future__ import annotations

import asyncio
import datetime as dt

from app.services import data_service, portfolio_service, supabase_store, watchlist_service

_RULE_TYPES = {"stop_loss", "breakdown", "price_target"}
# 同一规则命中后冷却期（避免盘中反复刷事件）
_COOLDOWN_HOURS = 24


def _require_configured() -> None:
    if not supabase_store.is_configured():
        raise RuntimeError("未配置 Supabase，预警功能不可用")


async def add_rule(user_id: str, code: str, rtype: str, threshold: float, name: str = "", note: str = "") -> dict:
    _require_configured()
    code = code.strip()
    if not code or not code.isdigit() or len(code) != 6:
        raise ValueError("股票代码格式不正确")
    if rtype not in _RULE_TYPES:
        raise ValueError("规则类型不支持")
    if not (0 < threshold < 100000):
        raise ValueError("阈值价格无效")
    sb = await supabase_store.get_service_client()
    payload = {
        "user_id": user_id,
        "code": code,
        "name": name or "",
        "type": rtype,
        "threshold": round(threshold, 3),
        "enabled": True,
        "note": note or "",
    }
    res = await sb.table("alert_rules").insert(payload).execute()
    return res.data[0]


async def list_rules(user_id: str) -> list[dict]:
    _require_configured()
    sb = await supabase_store.get_service_client()
    res = await sb.table("alert_rules").select("*").eq("user_id", user_id).order("created_at", desc=False).execute()
    return res.data or []


async def delete_rule(user_id: str, rule_id: int) -> bool:
    _require_configured()
    sb = await supabase_store.get_service_client()
    res = await sb.table("alert_rules").delete().eq("id", rule_id).eq("user_id", user_id).execute()
    return bool(res.data)


_STOP_RULE_NOTE = "auto:holding_stop"  # 自动规则的标记，与手动规则区分


async def sync_holding_stop_rules(user_id: str, code: str, name: str, stop_price: float) -> dict:
    """持仓止损自动预警：为持仓同步一条 stop_loss 规则（幂等，跟随最新止损位）。

    - 已有同 code 的 auto 规则 → 更新阈值（止损位随行情变化）
    - 没有 → 新建
    删除持仓时调 remove_holding_stop_rule 清理。
    """
    _require_configured()
    sb = await supabase_store.get_service_client()
    existing = (
        await sb.table("alert_rules")
        .select("id")
        .eq("user_id", user_id)
        .eq("code", code)
        .eq("type", "stop_loss")
        .eq("note", _STOP_RULE_NOTE)
        .limit(1)
        .execute()
    )
    if existing.data:
        await (
            sb.table("alert_rules")
            .update({"threshold": round(stop_price, 3), "name": name, "enabled": True})
            .eq("id", existing.data[0]["id"])
            .execute()
        )
        return {"action": "updated", "rule_id": existing.data[0]["id"]}
    rule = await add_rule(user_id, code, "stop_loss", stop_price, name=name, note=_STOP_RULE_NOTE)
    return {"action": "created", "rule_id": rule["id"]}


async def remove_holding_stop_rule(user_id: str, code: str) -> bool:
    """删除持仓时清理其自动止损规则（不影响用户手动建的规则）。"""
    if not supabase_store.is_configured():
        return False
    sb = await supabase_store.get_service_client()
    res = (
        await sb.table("alert_rules")
        .delete()
        .eq("user_id", user_id)
        .eq("code", code)
        .eq("type", "stop_loss")
        .eq("note", _STOP_RULE_NOTE)
        .execute()
    )
    return bool(res.data)


async def list_events(user_id: str, unread_only: bool = False, limit: int = 50) -> list[dict]:
    _require_configured()
    sb = await supabase_store.get_service_client()
    q = sb.table("alert_events").select("*").eq("user_id", user_id)
    if unread_only:
        q = q.eq("is_read", False)
    res = await q.order("created_at", desc=True).limit(limit).execute()
    return res.data or []


async def unread_count(user_id: str) -> int:
    _require_configured()
    sb = await supabase_store.get_service_client()
    res = await sb.table("alert_events").select("id", count="exact").eq("user_id", user_id).eq("is_read", False).execute()
    return res.count or 0


async def mark_read(user_id: str, event_ids: list[int] | None = None) -> int:
    _require_configured()
    sb = await supabase_store.get_service_client()
    q = sb.table("alert_events").update({"is_read": True}).eq("user_id", user_id)
    if event_ids:
        q = q.in_("id", event_ids)
    res = await q.execute()
    return len(res.data or [])


async def _collect_codes(user_id: str) -> list[str]:
    """收集需要评估的股票代码：规则 + 持仓 + 自选。"""
    codes: set[str] = set()
    try:
        rules = await list_rules(user_id)
        for r in rules:
            if r.get("enabled"):
                codes.add(r["code"])
    except Exception:
        pass
    try:
        holdings = await portfolio_service.list_holdings(user_id)
        for h in holdings:
            codes.add(h["code"])
    except Exception:
        pass
    try:
        wl = await watchlist_service.list_watchlist(user_id)
        for w in wl:
            codes.add(w["code"])
    except Exception:
        pass
    return list(codes)


def _should_fire(rtype: str, price: float, threshold: float) -> bool:
    if rtype in ("stop_loss", "breakdown"):
        return price <= threshold
    if rtype == "price_target":
        return price >= threshold
    return False


def _severity_of(rtype: str) -> str:
    return "danger" if rtype in ("stop_loss", "breakdown") else "warn"


def _title_of(rtype: str, name: str, code: str) -> str:
    label = {"stop_loss": "止损触发", "breakdown": "破位触发", "price_target": "目标价到达"}[rtype]
    return f"{label} · {name or code}"


async def _fire_for_user(user_id: str, codes: list[str]) -> int:
    """对单个用户评估并落库事件，返回新增事件数。"""
    if not codes:
        return 0
    try:
        quotes = await asyncio.to_thread(data_service.get_spot_quote, codes)
    except Exception:
        return 0
    quote_map = {q.code: q for q in quotes}

    rules = await list_rules(user_id)
    enabled = [r for r in rules if r.get("enabled")]
    if not enabled:
        return 0

    sb = await supabase_store.get_service_client()
    now = dt.datetime.now(dt.timezone.utc)
    since = (now - dt.timedelta(hours=_COOLDOWN_HOURS)).isoformat()

    new_count = 0
    for r in enabled:
        code = r["code"]
        q = quote_map.get(code)
        if not q or q.price is None:
            continue
        if not _should_fire(r["type"], q.price, r["threshold"]):
            continue
        # 冷却：同一规则 24h 内已有事件则跳过
        try:
            recent = await sb.table("alert_events").select("id", count="exact").eq("user_id", user_id).eq("rule_id", r["id"]).gte("created_at", since).execute()
            if (recent.count or 0) > 0:
                continue
        except Exception:
            pass
        payload = {
            "user_id": user_id,
            "rule_id": r["id"],
            "code": code,
            "name": q.name or r.get("name") or "",
            "title": _title_of(r["type"], q.name or r.get("name") or "", code),
            "message": f"现价 {q.price:.2f} 触发阈值 {r['threshold']:.2f}（{r['type']}）",
            "price": round(q.price, 3),
            "severity": _severity_of(r["type"]),
            "is_read": False,
        }
        try:
            await sb.table("alert_events").insert(payload).execute()
            new_count += 1
        except Exception:
            continue
    return new_count


async def evaluate_for_user(user_id: str) -> int:
    """前端盯盘轮询调用：评估当前用户全部相关代码。"""
    _require_configured()
    codes = await _collect_codes(user_id)
    return await _fire_for_user(user_id, codes)


async def evaluate_all() -> dict:
    """Cron 兜底：遍历所有有规则/持仓/自选的用户并评估。"""
    _require_configured()
    sb = await supabase_store.get_service_client()
    # 收集有预警规则的用户
    rule_users = await sb.table("alert_rules").select("user_id").execute()
    users = {r["user_id"] for r in (rule_users.data or [])}
    if not users:
        return {"users": 0, "events": 0}
    total = 0
    for uid in users:
        try:
            total += await evaluate_for_user(uid)
        except Exception:
            continue
    return {"users": len(users), "events": total}
