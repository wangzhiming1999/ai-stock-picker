"""持仓服务：用户持仓 CRUD + 风险等级 + 持仓建议。

所有操作基于 JWT 解析出的 user_id 隔离数据（后端用 service client 绕过 RLS，
归属控制在后端代码中保证）。
"""
from __future__ import annotations

import asyncio
import datetime as dt

from app.services import data_service, signal_service, supabase_store

RISK_LEVELS = {"保守", "稳健", "进取", "激进"}


def _require_configured():
    if not supabase_store.is_configured():
        raise RuntimeError("Supabase 未配置")


async def get_profile(user_id: str) -> dict:
    """获取用户风险等级配置（无则返回默认）。"""
    _require_configured()
    sb = await supabase_store.get_service_client()
    res = (
        await sb.table("user_profiles")
        .select("*")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if res.data:
        return res.data[0]
    return {"user_id": user_id, "risk_level": "稳健", "total_capital": 100000}


async def set_profile(user_id: str, risk_level: str | None = None, total_capital: float | None = None) -> dict:
    """设置用户风险等级/总资金（upsert）。"""
    _require_configured()
    if risk_level and risk_level not in RISK_LEVELS:
        raise ValueError(f"风险等级必须是: {RISK_LEVELS}")

    sb = await supabase_store.get_service_client()
    existing = (
        await sb.table("user_profiles")
        .select("user_id")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    payload = {"updated_at": now}
    if risk_level:
        payload["risk_level"] = risk_level
    if total_capital is not None:
        payload["total_capital"] = total_capital

    if existing.data:
        await sb.table("user_profiles").update(payload).eq("user_id", user_id).execute()
    else:
        payload["user_id"] = user_id
        payload["created_at"] = now
        await sb.table("user_profiles").insert(payload).execute()

    return await get_profile(user_id)


async def add_holding(user_id: str, code: str, cost_price: float, shares: int, buy_date: str | None = None, note: str = "") -> dict:
    """添加持仓（同名代码更新）。"""
    _require_configured()
    code = code.strip()
    if not code or shares <= 0 or cost_price <= 0:
        raise ValueError("代码、成本价、数量必须有效")

    # 尝试获取股票名称
    name = ""
    try:
        quotes = await asyncio.to_thread(data_service.get_spot_quote, [code])
        if quotes:
            name = quotes[0].name or ""
    except Exception:
        pass

    sb = await supabase_store.get_service_client()
    existing = (
        await sb.table("user_holdings")
        .select("id")
        .eq("user_id", user_id)
        .eq("code", code)
        .limit(1)
        .execute()
    )
    payload = {
        "name": name,
        "cost_price": cost_price,
        "shares": shares,
        "buy_date": buy_date,
        "note": note,
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    if existing.data:
        await sb.table("user_holdings").update(payload).eq("id", existing.data[0]["id"]).execute()
        hid = existing.data[0]["id"]
    else:
        payload.update({"user_id": user_id, "code": code})
        res = await sb.table("user_holdings").insert(payload).execute()
        hid = res.data[0]["id"]

    # 自动止损预警：成本价 -7% 保底，技术信号止损位（若有且更低）优先
    stop_price = round(cost_price * 0.93, 2)
    try:
        hist = await asyncio.to_thread(data_service.get_history, code, 60)
        if hist and hist.closes:
            signal = signal_service.compute_signals(hist.closes, hist.closes[-1])
            if signal and signal.get("stop_loss") and signal["stop_loss"] < stop_price:
                stop_price = signal["stop_loss"]
    except Exception:
        pass
    rule_sync = None
    try:
        from app.services import alert_service

        rule_sync = await alert_service.sync_holding_stop_rules(user_id, code, name, stop_price)
    except Exception:
        pass  # 预警规则失败不阻塞持仓保存

    return {"id": hid, "code": code, "name": name, "auto_stop_rule": rule_sync, "stop_price": stop_price}


async def add_holdings_batch(user_id: str, items: list[dict]) -> dict:
    """批量导入持仓：一次批量补名称，逐只 upsert（同代码更新）。"""
    _require_configured()
    if not items:
        return {"added": 0, "skipped": 0}

    codes = [it["code"] for it in items]
    name_map: dict[str, str] = {}
    try:
        quotes = await asyncio.to_thread(data_service.get_spot_quote, codes)
        name_map = {q.code: q.name for q in quotes if q.name}
    except Exception:
        name_map = {}

    sb = await supabase_store.get_service_client()
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    # 查已存在的 code -> id（同代码视为更新）
    existing_map: dict[str, int] = {}
    try:
        res = await sb.table("user_holdings").select("id", "code").eq("user_id", user_id).in_("code", codes).execute()
        existing_map = {r["code"]: r["id"] for r in (res.data or [])}
    except Exception:
        existing_map = {}

    added = skipped = 0
    for it in items:
        code = it["code"]
        cost = float(it["cost_price"])
        shares = int(it["shares"])
        if cost <= 0 or shares <= 0:
            skipped += 1
            continue
        payload = {
            "name": it.get("name") or name_map.get(code, ""),
            "cost_price": cost,
            "shares": shares,
            "buy_date": it.get("buy_date"),
            "note": it.get("note") or "",
            "updated_at": now,
        }
        try:
            if code in existing_map:
                await sb.table("user_holdings").update(payload).eq("id", existing_map[code]).execute()
            else:
                payload.update({"user_id": user_id, "code": code})
                ins = await sb.table("user_holdings").insert(payload).execute()
                if ins.data:
                    existing_map[code] = ins.data[0]["id"]
            added += 1
        except Exception:
            skipped += 1

    # 批量导入后统一同步自动止损规则（逐只，失败不阻塞）
    if added:
        try:
            from app.services import alert_service

            for it in items[:added]:
                code = it["code"]
                stop_price = round(float(it.get("cost_price", 0)) * 0.93, 2)
                if stop_price <= 0:
                    continue
                try:
                    await alert_service.sync_holding_stop_rules(
                        user_id, code, it.get("name") or name_map.get(code, ""), stop_price
                    )
                except Exception:
                    continue
        except Exception:
            pass

    return {"added": added, "skipped": skipped}


async def list_holdings(user_id: str) -> list[dict]:
    """列出用户全部持仓（含最新行情、技术信号、盈亏）。"""
    _require_configured()
    sb = await supabase_store.get_service_client()
    res = (
        await sb.table("user_holdings")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    holdings = res.data or []
    if not holdings:
        # 无持仓也返回标准 dict 结构（避免调用方 list.get 崩溃）
        return {
            "holdings": [],
            "total_value": 0.0,
            "total_cost": 0.0,
            "total_pnl": 0.0,
            "total_pnl_pct": 0.0,
        }

    # 批量获取行情（同步 requests 丢线程池，避免阻塞事件循环）
    codes = [h["code"] for h in holdings]
    quotes = await asyncio.to_thread(data_service.get_spot_quote, codes)
    quote_map = {q.code: q for q in quotes}
    # K 线并发预取（原为循环内逐只同步请求，N+1 且阻塞）
    hists = await asyncio.gather(
        *(asyncio.to_thread(data_service.get_history, h["code"]) for h in holdings),
        return_exceptions=True,
    )

    enriched = []
    total_value = 0.0
    total_cost = 0.0
    for h, hist in zip(holdings, hists):
        q = quote_map.get(h["code"])
        price = q.price if q else None
        cost_price = h.get("cost_price") or 0
        shares = h.get("shares") or 0
        market_value = (price or cost_price) * shares
        pnl = (price - cost_price) * shares if price else None
        pnl_pct = (price / cost_price - 1) * 100 if price and cost_price else None
        total_value += market_value
        total_cost += cost_price * shares

        # 技术信号（K 线已并发预取）
        signal = None
        try:
            history = None if isinstance(hist, BaseException) else hist
            if history and history.closes and price:
                signal = signal_service.compute_signals(history.closes, price)
        except Exception:
            pass

        enriched.append(
            {
                **h,
                "current_price": price,
                "market_value": round(market_value, 2),
                "pnl": round(pnl, 2) if pnl is not None else None,
                "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
                "signal": signal,
            }
        )

    return {
        "holdings": enriched,
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2),
        "total_pnl": round(total_value - total_cost, 2),
        "total_pnl_pct": round((total_value / total_cost - 1) * 100, 2) if total_cost else 0,
    }


async def remove_holding(user_id: str, holding_id: int) -> bool:
    """删除持仓。"""
    _require_configured()
    sb = await supabase_store.get_service_client()
    # 先取 code（用于清理自动止损规则），再删除
    row = (
        await sb.table("user_holdings")
        .select("code")
        .eq("id", holding_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    res = (
        await sb.table("user_holdings")
        .delete()
        .eq("id", holding_id)
        .eq("user_id", user_id)
        .execute()
    )
    ok = bool(res.data)
    if ok and row.data:
        try:
            from app.services import alert_service

            await alert_service.remove_holding_stop_rule(user_id, row.data[0]["code"])
        except Exception:
            pass  # 规则清理失败不影响持仓删除
    return ok


async def update_holding(user_id: str, holding_id: int, **fields) -> dict:
    """更新持仓（成本价/数量/备注）。"""
    _require_configured()
    allowed = {"cost_price", "shares", "buy_date", "note"}
    payload = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not payload:
        raise ValueError("没有可更新的字段")
    payload["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()

    sb = await supabase_store.get_service_client()
    res = (
        await sb.table("user_holdings")
        .update(payload)
        .eq("id", holding_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not res.data:
        raise ValueError("持仓不存在")
    return res.data[0]


async def get_portfolio_advice(user_id: str) -> dict:
    """生成持仓建议：按风险等级 + 每只股票的技术信号。"""
    data = await list_holdings(user_id)
    holdings = data.get("holdings", [])
    profile = await get_profile(user_id)
    risk_level = profile.get("risk_level", "稳健")
    total_capital = profile.get("total_capital") or 100000

    # 风险等级参数
    risk_config = {
        "保守": {"max_positions": 5, "max_position_pct": 15, "min_strength": 6.5, "min_rr": 2.0, "desc": "低波动优先，严格控制仓位，单只不超过总资金 15%"},
        "稳健": {"max_positions": 8, "max_position_pct": 20, "min_strength": 5.5, "min_rr": 1.5, "desc": "攻守平衡，分散配置，单只不超过总资金 20%"},
        "进取": {"max_positions": 10, "max_position_pct": 25, "min_strength": 4.5, "min_rr": 1.0, "desc": "适度激进，可承担一定波动，单只不超过总资金 25%"},
        "激进": {"max_positions": 12, "max_position_pct": 35, "min_strength": 3.5, "min_rr": 0.5, "desc": "高弹性追求，容忍较大回撤，单只不超过总资金 35%"},
    }
    cfg = risk_config[risk_level]

    advice_items = []
    total_value = data.get("total_value", 0) or 0
    for h in holdings:
        code = h["code"]
        name = h["name"]
        price = h.get("current_price")
        cost = h.get("cost_price") or 0
        pnl_pct = h.get("pnl_pct")
        signal = h.get("signal") or {}
        strength = signal.get("strength", 0)
        rr = signal.get("rr_ratio", 0)
        support = signal.get("support")
        resistance = signal.get("resistance")
        stop_loss = signal.get("stop_loss")

        pos_pct = (h.get("market_value") or 0) / total_capital * 100 if total_capital else 0

        # 逐项建议
        tips = []
        action = "持有观察"
        if signal:
            if price and stop_loss and price <= stop_loss * 1.02:
                tips.append("已接近止损位，建议考虑减仓控制风险")
                action = "建议减仓"
            elif price and support and 0 < (price - support) / price < 0.05:
                tips.append("临近支撑位，可关注企稳信号")
            if strength >= cfg["min_strength"]:
                tips.append(f"信号强度 {strength:.1f} 达标（要求≥{cfg['min_strength']}）")
            else:
                tips.append(f"信号强度 {strength:.1f} 偏弱（要求≥{cfg['min_strength']}），不宜加仓")
            if rr >= cfg["min_rr"]:
                tips.append(f"风险收益比 {rr:.2f} 合理（要求≥{cfg['min_rr']}）")
            else:
                tips.append(f"风险收益比 {rr:.2f} 偏低，盈亏空间有限")
        if pos_pct > cfg["max_position_pct"]:
            tips.append(f"仓位占比 {pos_pct:.1f}% 超过上限（{cfg['max_position_pct']}%），建议减仓")
            if action == "持有观察":
                action = "建议减仓"
        elif pos_pct > cfg["max_position_pct"] * 0.7:
            tips.append(f"仓位占比 {pos_pct:.1f}% 接近上限，谨慎加仓")
        if pnl_pct is not None:
            if pnl_pct > 20:
                tips.append(f"浮盈 {pnl_pct:.1f}%，可考虑部分止盈")
            elif pnl_pct < -8:
                tips.append(f"浮亏 {pnl_pct:.1f}%，检查是否跌破止损逻辑")

        advice_items.append(
            {
                "code": code,
                "name": name,
                "price": price,
                "cost_price": cost,
                "pnl_pct": pnl_pct,
                "position_pct": round(pos_pct, 1),
                "strength": strength,
                "rr_ratio": rr,
                "support": support,
                "resistance": resistance,
                "stop_loss": stop_loss,
                "action": action,
                "tips": tips,
            }
        )

    # 组合层面建议
    portfolio_tips = []
    positions = len(holdings)
    if positions > cfg["max_positions"]:
        portfolio_tips.append(f"持仓 {positions} 只超过建议上限 {cfg['max_positions']} 只，建议聚焦核心标的")
    else:
        portfolio_tips.append(f"持仓 {positions} 只，在建议范围（≤{cfg['max_positions']}）内")
    avg_strength = sum(h.get("strength", 0) for h in advice_items) / positions if positions else 0
    if avg_strength >= 6:
        portfolio_tips.append(f"组合平均信号强度 {avg_strength:.1f}，整体偏强")
    elif avg_strength < 4:
        portfolio_tips.append(f"组合平均信号强度 {avg_strength:.1f}，整体偏弱，注意市场风险")
    else:
        portfolio_tips.append(f"组合平均信号强度 {avg_strength:.1f}，中性")

    return {
        "risk_level": risk_level,
        "risk_desc": cfg["desc"],
        "total_capital": total_capital,
        "total_value": data.get("total_value"),
        "total_pnl_pct": data.get("total_pnl_pct"),
        "portfolio_tips": portfolio_tips,
        "holdings_advice": advice_items,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
