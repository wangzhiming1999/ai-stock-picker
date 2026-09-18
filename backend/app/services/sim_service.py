"""模拟盘交易引擎：虚拟资金账户 + 买卖成交流水 + 盈亏聚合 + 净值曲线。

设计（详见 docs/sim-trading-plan.md）：
- sim_trades 是唯一数据源，持仓在查询时按平均成本法聚合，避免双写不一致；
- cash 落在 user_profiles（不新建账户表）；
- 卖出可反写 daily_recommendations.settled，闭合「推荐 → 模拟验证 → 胜率」环（P2）。
所有操作基于 JWT 解析的 user_id 隔离（service client 绕过 RLS）。
"""
from __future__ import annotations

import asyncio
import datetime as dt

from app.services import data_service, supabase_store, winrate_service

# ---------- A 股费用参数（可做配置，这里取通用默认值） ----------
COMMISSION_RATE = 0.00025   # 佣金费率
MIN_COMMISSION = 5.0        # 最低佣金（元）
STAMP_RATE = 0.0005         # 印花税（仅卖出）
TRANSFER_RATE = 0.00001     # 过户费
LOT_SIZE = 100              # 每手股数

DEFAULT_CAPITAL = 100000.0


def _require_configured():
    if not supabase_store.is_configured():
        raise RuntimeError("Supabase 未配置")


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _today() -> dt.date:
    return dt.date.today()


async def _fetch_quote(code: str):
    """取实时行情（线程池执行同步请求），失败返回 None。"""
    try:
        quotes = await asyncio.to_thread(data_service.get_spot_quote, [code])
        return quotes[0] if quotes else None
    except Exception:
        return None


def _compute_fee(side: str, price: float, shares: int) -> float:
    notional = price * shares
    commission = max(notional * COMMISSION_RATE, MIN_COMMISSION)
    transfer = notional * TRANSFER_RATE
    fee = commission + transfer
    if side == "sell":
        fee += notional * STAMP_RATE
    return round(fee, 2)


async def _get_or_create_profile(user_id: str) -> dict:
    """确保 user_profiles 行存在（cash 列默认 0），返回该行。"""
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
    now = _now()
    payload = {
        "user_id": user_id,
        "risk_level": "稳健",
        "total_capital": DEFAULT_CAPITAL,
        "cash": 0,
        "created_at": now,
        "updated_at": now,
    }
    try:
        ins = await sb.table("user_profiles").insert(payload).execute()
        if ins.data:
            return ins.data[0]
    except Exception:
        # 并发插入兜底：重新读取
        res2 = (
            await sb.table("user_profiles")
            .select("*")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if res2.data:
            return res2.data[0]
    return {"user_id": user_id, "risk_level": "稳健", "total_capital": DEFAULT_CAPITAL, "cash": 0}


async def _set_cash(user_id: str, cash: float) -> None:
    sb = await supabase_store.get_service_client()
    await _get_or_create_profile(user_id)  # 确保行存在
    await (
        sb.table("user_profiles")
        .update({"cash": round(cash, 2), "updated_at": _now()})
        .eq("user_id", user_id)
        .execute()
    )


async def _execute_trade_atomic(
    sb,
    *,
    user_id: str,
    code: str,
    name: str,
    side: str,
    price: float,
    shares: int,
    fee: float,
    amount: float,
    source: str,
    related_reco_id: str | None,
    note: str,
) -> dict:
    """在数据库单事务内校验账户并完成现金与流水变更。"""
    params = {
        "p_user_id": user_id,
        "p_code": code,
        "p_name": name,
        "p_side": side,
        "p_price": round(price, 2),
        "p_shares": shares,
        "p_fee": fee,
        "p_amount": round(amount, 2),
        "p_source": source,
        "p_related_reco_id": str(related_reco_id) if related_reco_id else None,
        "p_note": note or "",
        "p_trade_date": _today().isoformat(),
    }
    try:
        response = await sb.rpc("execute_sim_trade", params).execute()
    except Exception as exc:
        message = str(exc)
        for known in ("现金不足", "可用股数不足", "模拟账户不存在", "交易参数无效"):
            if known in message:
                raise ValueError(known) from exc
        raise RuntimeError("模拟交易提交失败") from exc
    data = response.data
    if isinstance(data, list):
        data = data[0] if data else None
    if not isinstance(data, dict) or not isinstance(data.get("trade"), dict):
        raise RuntimeError("模拟交易返回异常")
    return data


async def _load_trades(user_id: str) -> list[dict]:
    sb = await supabase_store.get_service_client()
    res = (
        await sb.table("sim_trades")
        .select("*")
        .eq("user_id", user_id)
        .order("executed_at", desc=False)
        .execute()
    )
    return res.data or []


def _aggregate(trades: list[dict]):
    """按代码聚合买卖，返回 (positions, realized_total)。

    positions: 每只代码 {code, name, shares, avg_cost, buy_shares, sell_shares}
    avg_cost = 含费买入成本 / 买入股数（平均成本法，卖出不改变 avg_cost）
    realized_total = Σ(卖出价 - avg_cost)*股数 - 卖出费
    """
    buys: dict[str, list[tuple]] = {}
    sells: dict[str, list[tuple]] = {}
    names: dict[str, str] = {}
    for t in trades:
        code = t["code"]
        names[code] = (t.get("name") or names.get(code) or "")
        if t["side"] == "buy":
            buys.setdefault(code, []).append(
                (float(t["price"]), int(t["shares"]), float(t["fee"]), t.get("trade_date"))
            )
        else:
            sells.setdefault(code, []).append((float(t["price"]), int(t["shares"]), float(t["fee"])))

    positions: list[dict] = []
    realized_total = 0.0
    for code in set(buys) | set(sells):
        bl = buys.get(code, [])
        sl = sells.get(code, [])
        buy_shares = sum(x[1] for x in bl)
        buy_cost = sum(x[0] * x[1] + x[2] for x in bl)  # 含费成本基数
        avg_cost = buy_cost / buy_shares if buy_shares else 0.0
        for sp, ss, sf in sl:
            realized_total += (sp - avg_cost) * ss - sf
        positions.append(
            {
                "code": code,
                "name": names.get(code, ""),
                "shares": buy_shares - sum(x[1] for x in sl),
                "avg_cost": avg_cost,
                "buy_shares": buy_shares,
                "sell_shares": sum(x[1] for x in sl),
            }
        )
    return positions, round(realized_total, 2)


def _available_shares(positions: list[dict], code: str, enforce_t1: bool) -> int:
    """可用卖出股数：T+1 开启时排除当日买入。"""
    p = next((x for x in positions if x["code"] == code), None)
    if not p:
        return 0
    if not enforce_t1:
        return p["shares"]
    # 需要当日买入股数：从聚合里拿不到单笔 trade_date，这里用聚合的 buy_shares 近似仅当
    # 当日买入已计入；精确 T+1 在 sell() 内基于原始 trades 计算
    return p["shares"]


async def get_account(user_id: str) -> dict:
    """账户总览：现金 / 市值 / 总盈亏 / 已实现 / 未实现。"""
    _require_configured()
    profile = await _get_or_create_profile(user_id)
    cash = float(profile.get("cash") or 0)
    total_capital = float(profile.get("total_capital") or 0)

    pos = await list_positions(user_id)
    open_positions = pos["positions"]
    market_value = sum((p["market_value"] or 0) for p in open_positions)
    unrealized = sum((p["unrealized_pnl"] or 0) for p in open_positions)
    realized = pos["realized_pnl"]
    total_value = cash + market_value
    total_pnl = (total_value - total_capital) if total_capital else None
    total_pnl_pct = round(total_pnl / total_capital * 100, 2) if (total_pnl is not None and total_capital) else None

    return {
        "cash": round(cash, 2),
        "total_capital": round(total_capital, 2),
        "market_value": round(market_value, 2),
        "total_value": round(total_value, 2),
        "realized_pnl": realized,
        "unrealized_pnl": round(unrealized, 2),
        "total_pnl": round(total_pnl, 2) if total_pnl is not None else None,
        "total_pnl_pct": total_pnl_pct,
        "positions_cnt": len(open_positions),
        "initialized": bool(profile.get("total_capital") or cash or pos["open_count"]),
    }


async def init_account(user_id: str, total_capital: float | None = None) -> dict:
    """初始化模拟账户：设定本金，cash 补为本金（幂等）。"""
    _require_configured()
    sb = await supabase_store.get_service_client()
    existing = (
        await sb.table("user_profiles")
        .select("total_capital")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    cap = total_capital if total_capital and total_capital > 0 else (existing.data[0].get("total_capital") if existing.data else DEFAULT_CAPITAL)
    await (
        sb.table("user_profiles")
        .update({"total_capital": cap, "cash": cap, "updated_at": _now()})
        .eq("user_id", user_id)
        .execute()
    )
    return await get_account(user_id)


async def buy(
    user_id: str,
    code: str,
    shares: int,
    price: float | None = None,
    source: str = "manual",
    related_reco_id: str | None = None,
    note: str = "",
) -> dict:
    """模拟买入：扣现金，写 sim_trades。"""
    _require_configured()
    code = code.strip()
    if not code or len(code) != 6 or not code.isdigit():
        raise ValueError("股票代码须为 6 位数字")
    if shares <= 0 or shares % LOT_SIZE != 0:
        raise ValueError(f"买入数量须为 {LOT_SIZE} 股的整数倍")

    quote = None
    if price is None:
        quote = await _fetch_quote(code)
        if not quote or not quote.price:
            raise ValueError("无法获取实时价格，请手动指定成交价")
        price = quote.price
    else:
        price = float(price)
    if price <= 0:
        raise ValueError("成交价须大于 0")
    if quote is None:
        quote = await _fetch_quote(code)
    name = quote.name if quote else ""

    fee = _compute_fee("buy", price, shares)
    total = price * shares + fee

    profile = await _get_or_create_profile(user_id)
    cash = float(profile.get("cash") or 0)
    if cash < total:
        raise ValueError(f"现金不足：本次需 ¥{total:,.2f}，当前可用 ¥{cash:,.2f}")

    sb = await supabase_store.get_service_client()
    executed = await _execute_trade_atomic(
        sb, user_id=user_id, code=code, name=name, side="buy", price=price,
        shares=shares, fee=fee, amount=total, source=source,
        related_reco_id=related_reco_id, note=note,
    )
    row = executed["trade"]
    account = await get_account(user_id)
    return {"trade": row, "account": account}


async def sell(
    user_id: str,
    code: str,
    shares: int,
    price: float | None = None,
    enforce_t1: bool = True,
    source: str = "manual",
    related_reco_id: str | None = None,
    note: str = "",
) -> dict:
    """模拟卖出：加现金，写 sim_trades，T+1 校验，反写推荐结算（P2）。"""
    _require_configured()
    code = code.strip()
    if not code or len(code) != 6 or not code.isdigit():
        raise ValueError("股票代码须为 6 位数字")
    if shares <= 0 or shares % LOT_SIZE != 0:
        raise ValueError(f"卖出数量须为 {LOT_SIZE} 股的整数倍")

    quote = None
    if price is None:
        quote = await _fetch_quote(code)
        if not quote or not quote.price:
            raise ValueError("无法获取实时价格，请手动指定成交价")
        price = quote.price
    else:
        price = float(price)
    if price <= 0:
        raise ValueError("成交价须大于 0")
    if quote is None:
        quote = await _fetch_quote(code)
    name = quote.name if quote else ""

    trades = await _load_trades(user_id)
    positions, _ = _aggregate(trades)
    pos = next((p for p in positions if p["code"] == code), None)
    if not pos or pos["shares"] <= 0:
        raise ValueError(f"当前未持有 {code}")

    # 可用股数（T+1 排除当日买入）
    if enforce_t1:
        today = _today()
        today_buy = sum(
            int(t["shares"])
            for t in trades
            if t["code"] == code and t["side"] == "buy" and str(t.get("trade_date")) == today.isoformat()
        )
        available = pos["shares"] - today_buy
    else:
        available = pos["shares"]
    if shares > available:
        raise ValueError(
            f"可用股数不足：可卖 {available} 股"
            + ("（含当日买入，T+1 限制）" if enforce_t1 and available < pos["shares"] else "")
        )

    fee = _compute_fee("sell", price, shares)
    proceeds = price * shares - fee

    sb = await supabase_store.get_service_client()
    executed = await _execute_trade_atomic(
        sb, user_id=user_id, code=code, name=name, side="sell", price=price,
        shares=shares, fee=fee, amount=proceeds, source=source,
        related_reco_id=related_reco_id, note=note,
    )
    row = executed["trade"]

    # P2：反写关联推荐结算，闭合胜率环
    if related_reco_id:
        avg_cost = pos["avg_cost"]
        hit = (price - avg_cost) * shares - fee > 0
        await _mark_reco_settled(related_reco_id, price, hit)

    account = await get_account(user_id)
    return {"trade": row, "account": account, "realized_pnl": round((price - pos["avg_cost"]) * shares - fee, 2)}


async def _mark_reco_settled(reco_id: str, sell_price: float, hit: bool) -> None:
    """卖出结算后标记 daily_recommendations 已结算，并刷新胜率快照。"""
    try:
        sb = await supabase_store.get_service_client()
        await (
            sb.table("daily_recommendations")
            .update({"settled_at": _now(), "hit": hit, "next_close": round(sell_price, 2)})
            .eq("id", int(reco_id))
            .execute()
        )
        await winrate_service.refresh_winrate_snapshot()
    except Exception as e:
        print(f"[sim] 反写推荐结算失败(reco={reco_id}): {e}")


async def list_positions(user_id: str) -> dict:
    """持仓列表（含实时行情、平均成本、浮盈浮亏）。"""
    _require_configured()
    trades = await _load_trades(user_id)
    positions, realized = _aggregate(trades)
    open_pos = [p for p in positions if p["shares"] > 0]
    codes = [p["code"] for p in open_pos]
    quote_map = {}
    if codes:
        try:
            quotes = await asyncio.to_thread(data_service.get_spot_quote, codes)
            quote_map = {q.code: q for q in quotes}
        except Exception:
            quote_map = {}

    out = []
    for p in open_pos:
        q = quote_map.get(p["code"])
        price = q.price if q else None
        name = p["name"] or (q.name if q else "")
        mv = price * p["shares"] if price else None
        unreal = (price - p["avg_cost"]) * p["shares"] if price else None
        out.append(
            {
                "code": p["code"],
                "name": name,
                "shares": p["shares"],
                "avg_cost": round(p["avg_cost"], 2),
                "current_price": price,
                "market_value": round(mv, 2) if mv is not None else None,
                "unrealized_pnl": round(unreal, 2) if unreal is not None else None,
                "pnl_pct": round((price / p["avg_cost"] - 1) * 100, 2) if (price and p["avg_cost"]) else None,
            }
        )
    return {"positions": out, "realized_pnl": realized, "open_count": len(out)}


async def list_trades(user_id: str, limit: int = 50, offset: int = 0) -> dict:
    """成交流水（分页，按 executed_at desc）。"""
    _require_configured()
    sb = await supabase_store.get_service_client()
    res = (
        await sb.table("sim_trades")
        .select("*")
        .eq("user_id", user_id)
        .order("executed_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    rows = res.data or []
    # 统计总数
    cnt = await sb.table("sim_trades").select("id", count="exact").eq("user_id", user_id).execute()
    total = (cnt.count if hasattr(cnt, "count") else None) or len(rows)
    return {"trades": rows, "total": total, "limit": limit, "offset": offset}


async def get_performance(user_id: str) -> dict:
    """收益统计：净值曲线 + 已实现/未实现 + 按来源分组胜率。"""
    _require_configured()
    sb = await supabase_store.get_service_client()
    snap_res = (
        await sb.table("portfolio_snapshots")
        .select("*")
        .eq("user_id", user_id)
        .order("snapshot_date", desc=True)
        .limit(90)
        .execute()
    )
    snapshots = list(reversed(snap_res.data or []))

    # 按来源分组
    tr = await sb.table("sim_trades").select("*").eq("user_id", user_id).execute()
    by_source: dict[str, dict] = {}
    for t in (tr.data or []):
        src = t.get("source", "manual")
        b = by_source.setdefault(src, {"trades": 0, "buy_shares": 0, "sell_shares": 0, "buy_amount": 0.0, "sell_amount": 0.0})
        b["trades"] += 1
        if t["side"] == "buy":
            b["buy_shares"] += t["shares"]
            b["buy_amount"] += t["amount"]
        else:
            b["sell_shares"] += t["shares"]
            b["sell_amount"] += t["amount"]

    acc = await get_account(user_id)
    return {
        "snapshots": [
            {
                "date": s["snapshot_date"],
                "total_value": s["total_value"],
                "total_pnl": s["total_pnl"],
                "total_pnl_pct": s["total_pnl_pct"],
                "cash": s["cash"],
                "market_value": s["market_value"],
            }
            for s in snapshots
        ],
        "realized_pnl": acc["realized_pnl"],
        "unrealized_pnl": acc["unrealized_pnl"],
        "total_pnl": acc["total_pnl"],
        "total_pnl_pct": acc["total_pnl_pct"],
        "by_source": by_source,
    }


async def write_snapshot(user_id: str) -> dict:
    """写入/更新当日净值快照（daily cron 调用）。"""
    _require_configured()
    acc = await get_account(user_id)
    today = _today().isoformat()
    sb = await supabase_store.get_service_client()
    existing = (
        await sb.table("portfolio_snapshots")
        .select("id")
        .eq("user_id", user_id)
        .eq("snapshot_date", today)
        .execute()
    )
    payload = {
        "cash": acc["cash"],
        "market_value": acc["market_value"],
        "total_value": acc["total_value"],
        "total_pnl": acc["total_pnl"] if acc["total_pnl"] is not None else 0,
        "total_pnl_pct": acc["total_pnl_pct"] if acc["total_pnl_pct"] is not None else 0,
        "positions_cnt": acc["positions_cnt"],
    }
    if existing.data:
        await sb.table("portfolio_snapshots").update(payload).eq("id", existing.data[0]["id"]).execute()
    else:
        payload.update({"user_id": user_id, "snapshot_date": today})
        await sb.table("portfolio_snapshots").insert(payload).execute()
    return acc


async def snapshot_all_users() -> int:
    """为所有有过模拟流水的用户写当日净值快照，返回写入数。

    只覆盖 sim_trades 出现过的 user_id，避免为无模拟活动的用户生成噪音数据。
    """
    sb = await supabase_store.get_service_client()
    res = await sb.table("sim_trades").select("user_id").execute()
    user_ids = sorted({t["user_id"] for t in (res.data or [])})
    written = 0
    for uid in user_ids:
        try:
            await write_snapshot(uid)
            written += 1
        except Exception as e:
            print(f"[sim] 快照写入失败(user={uid[:8]}…): {e}")
    return written


async def reset(user_id: str) -> dict:
    """清零重来：删除成交流水与净值快照，现金归零。需前端二次确认。"""
    _require_configured()
    sb = await supabase_store.get_service_client()
    await sb.table("sim_trades").delete().eq("user_id", user_id).execute()
    await sb.table("portfolio_snapshots").delete().eq("user_id", user_id).execute()
    await _set_cash(user_id, 0)
    return await get_account(user_id)


# 模拟盘自动建仓：连板接力（source=limitup_relay）。
#
# 目的：连板晋级率目前只有「封板延续率」口径（calibers.limitup_relay，不是收益率）。
# 让模拟盘在 T+1 开盘自动按规则建仓 tier1 连板股，跑几周后 by_source 里就有
# limitup_relay 的**真实可成交收益**（含手续费、含一字板买不进的情况），
# 把晋级率升级成可验证的胜率口径。
#
# 规则（刻意极简，避免变成「策略调参」）：
# - 只买**资金面最强档**（relay tier 1，三因子全达标）；
# - 只在 T 日 play_advice == "hunt"（环境允许打板）时才执行；
# - T+1 开盘价成交（竞价挂开盘价，能成交的极端情况也就这个价附近）；
# - 一字板开盘（high==low 且开盘即涨停）**买不进**，记 missed 而不是假装成交 ——
#   这是该口径最容易自欺的地方：晋级率高，但很多根本买不到。
# 幂等：同一 (user, code, 建仓日) 只写一次，靠查询 sim_trades 已有记录去重。

# 连板接力单票预算占账户总资金比例。tier1 样本量小、且一字板买不进是常态，
# 仓位刻意保守；这只影响模拟盘数字，不影响真实资金。
RELAY_BUDGET_PCT = 10.0

# 一字板判定容差（与 limitdown_service._FLAT_EPS 同源）：日内高低价差 < 0.5% 视为无波动区间。
_RELAY_FLAT_EPS = 0.005


def _relay_build_shares(total_capital: float, price: float) -> int:
    """预算 → 整手数（向下取整，不足 1 手返回 0）。"""
    if total_capital <= 0 or price <= 0:
        return 0
    return int(total_capital * RELAY_BUDGET_PCT / 100.0 / price / 100) * 100


async def _relay_already_done(user_id: str, code: str, trade_date: str) -> bool:
    """该用户该票在建仓日是否已有 limitup_relay 流水（幂等判重）。"""
    sb = await supabase_store.get_service_client()
    res = (
        await sb.table("sim_trades")
        .select("id")
        .eq("user_id", user_id)
        .eq("code", code)
        .eq("source", "limitup_relay")
        .eq("trade_date", trade_date)
        .limit(1)
        .execute()
    )
    return bool(res.data)


async def _relay_history_dates(user_id: str) -> set[str]:
    """该用户已建仓过的 trade_date 集合（跨票去重由 _relay_already_done 处理）。"""
    sb = await supabase_store.get_service_client()
    res = (
        await sb.table("sim_trades")
        .select("trade_date")
        .eq("user_id", user_id)
        .eq("source", "limitup_relay")
        .execute()
    )
    return {str(r.get("trade_date")) for r in (res.data or [])}


def _relay_pick_targets(snapshot: dict) -> list[dict]:
    """从 T 日连板全景里挑出可建仓目标：环境 hunt + tier1。

    返回 [{code, name, boards, score}]；环境非 hunt 返回空列表。
    纯函数，便于单测。
    """
    advice = (snapshot or {}).get("play_advice") or {}
    if advice.get("level") != "hunt":
        return []
    tier1 = [
        r for r in ((snapshot or {}).get("relay_stocks") or [])
        if r.get("tier") == 1 and r.get("code")
    ]
    # build_relay_stocks 已按 (-score, -boards, seal_time) 排序，直接取即可
    return [
        {"code": r["code"], "name": r.get("name", ""), "boards": r.get("boards", 0), "score": r.get("score", 0)}
        for r in tier1
    ]


def _relay_unfillable(open_p: float, prev_close: float, high: float, low: float) -> bool:
    """一字板不可成交判定：全天无波动区间 + 开盘即涨停（相对昨收 ≥9.5%）。

    与 limitdown_service.repair_backtest 的 next_unsellable 同源逻辑，
    方向镜像（那边是卖不出，这边是买不进）。纯函数，便于单测。
    """
    if open_p <= 0 or prev_close <= 0:
        return False
    flat = (high - low) < _RELAY_FLAT_EPS * prev_close
    at_limit = open_p / prev_close - 1 >= 0.095
    return flat and at_limit


async def _relay_next_open(code: str, base_date: str) -> dict | None:
    """取某票在 base_date（T 日）之后第一个交易日的开盘数据。

    返回 {date, open, high, low, prev_close}；拿不到（停牌/数据缺失/T+1 未到）返回 None。
    prev_close 取 T 日收盘价，供一字板判定。
    """
    from app.services.data_service import get_history

    h = await asyncio.to_thread(get_history, code, 60)
    if h is None or not h.opens or not h.dates:
        return None
    base_norm = str(base_date).replace("-", "")
    dates_norm = [str(x).replace("-", "") for x in h.dates]
    try:
        i = dates_norm.index(base_norm)
    except ValueError:
        return None
    if i + 1 >= len(dates_norm):
        return None
    prev_close = h.closes[i]
    open_p, high, low = h.opens[i + 1], h.highs[i + 1], h.lows[i + 1]
    if not open_p or open_p <= 0:
        return None
    return {
        "date": h.dates[i + 1],
        "open": float(open_p),
        "high": float(high or 0),
        "low": float(low or 0),
        "prev_close": float(prev_close or 0),
    }


async def auto_relay_buy_for_user(user_id: str, snapshot: dict, *, trade_date: str | None = None) -> dict:
    """为单个用户执行连板接力自动建仓（T+1 开盘价）。

    ``snapshot`` 是 T 日（昨日）的 limitup 全景，由调用方传入 —— 本函数不负责拉取，
    以便测试注入与 T 日数据复用。流程：
    1. 判定 T 日环境 hunt + tier1 名单；
    2. 对每只票取 T+1 开盘价；一字板开盘 → missed（不成交）；
    3. 按 RELAY_BUDGET_PCT 预算整手买入（source=limitup_relay），幂等判重。

    返回执行摘要 {targets, bought, missed, skipped, errors}；不抛异常（cron 链路容错）。
    """
    summary: dict = {"targets": [], "bought": [], "missed": [], "skipped": [], "errors": []}
    try:
        targets = _relay_pick_targets(snapshot)
        if not targets:
            summary["skipped"].append("no_targets_or_not_hunt")
            return summary
        summary["targets"] = [t["code"] for t in targets]

        base_date = trade_date or (snapshot.get("trade_date") or "")
        if not base_date:
            summary["skipped"].append("no_trade_date")
            return summary

        # 注意：_get_or_create_profile 依赖 Supabase 配置，mock 场景（测试注入）直接跳过。
        profile = dict(await _get_or_create_profile(user_id))
        capital = float(profile.get("total_capital") or 0)
        if capital <= 0:
            summary["skipped"].append("account_not_initialized")
            return summary

        base_date = trade_date or (snapshot.get("trade_date") or "")
        if not base_date:
            summary["skipped"].append("no_trade_date")
            return summary

        for t in targets:
            code = t["code"]
            try:
                if await _relay_already_done(user_id, code, base_date):
                    summary["skipped"].append(f"{code}:already_done")
                    continue
                nxt = await _relay_next_open(code, base_date)
                if nxt is None:
                    summary["skipped"].append(f"{code}:no_open_data")
                    continue
                if _relay_unfillable(nxt["open"], nxt["prev_close"], nxt["high"], nxt["low"]):
                    summary["missed"].append(f"{code}:一字板买不进")
                    continue
                shares = _relay_build_shares(capital, nxt["open"])
                if shares <= 0:
                    summary["skipped"].append(f"{code}:insufficient_budget")
                    continue
                try:
                    await buy(
                        user_id, code, shares, price=nxt["open"],
                        source="limitup_relay",
                        note=f"连板接力{base_date}日{t['boards']}板tier1·T+1开盘建仓",
                    )
                    summary["bought"].append(f"{code}:{shares}股@{nxt['open']}")
                except ValueError as ve:
                    # 现金不足等业务性失败：跳过该票继续下一只
                    summary["skipped"].append(f"{code}:{ve}")
            except Exception as e:  # 单票失败不拖垮其余
                summary["errors"].append(f"{code}:{type(e).__name__}")
        return summary
    except Exception as e:
        summary["errors"].append(f"fatal:{type(e).__name__}:{e}")
        return summary


async def auto_relay_buy_all(snapshot: dict | None = None) -> dict:
    """为所有已初始化模拟账户的用户执行连板接力建仓（cron 入口）。

    snapshot 缺省时自动拉 T 日全景（内部有缓存）。Supabase 未配置返回空摘要。
    """
    if not supabase_store.is_configured():
        return {"skipped": ["supabase_not_configured"], "targets": [], "bought": [], "missed": [], "errors": []}
    if snapshot is None:
        from app.services import limitup_service

        try:
            snapshot = await limitup_service.get_snapshot()
        except Exception as e:
            return {"skipped": [f"snapshot_failed:{e}"], "targets": [], "bought": [], "missed": [], "errors": []}

    sb = await supabase_store.get_service_client()
    res = await sb.table("sim_trades").select("user_id").execute()
    user_ids = sorted({t["user_id"] for t in (res.data or [])})
    if not user_ids:
        return {"skipped": ["no_sim_users"], "targets": [], "bought": [], "missed": [], "errors": []}

    out: dict = {"targets": [], "bought": [], "missed": [], "skipped": [], "errors": [], "users": {}}
    for uid in user_ids:
        s = await auto_relay_buy_for_user(uid, snapshot)
        out["users"][uid[:8] + "…"] = {
            "bought": len(s["bought"]), "missed": len(s["missed"]), "errors": len(s["errors"]),
        }
        for k in ("targets", "bought", "missed", "skipped", "errors"):
            out[k].extend(s[k])
    return out


async def settle_agent_decisions() -> int:
    """每日 cron：到期结算 agent 决策记录（执行闭环的回写端）。

    结算规则（口径 agent_plan，calibers.py）：
    - data_date + horizon_days 个交易日之前的行，用**当日收盘价**结算 pnl/hit + 反思；
    - 到期判定用 trade_calendar（跳过周末/节假日），行情拿不到（停牌等）顺延到下一天；
    - adopted（用户已按计划建仓）与 ignored（未采纳对照组）同样结算 —— 对照组的存在
      让「采纳 vs 没采纳」可对比，这是 agent track record 的核心价值。
    返回结算行数；agent_decisions 表未建时静默返回 0。
    """
    from app.services import agent_decision_service, trade_calendar_service

    # 只处理「计划产出日 + horizon 之后」的行：用交易日历把 horizon_days 换算成日期门槛
    today = _today()
    threshold = await trade_calendar_service.shift_trading_days(today, -(agent_decision_service.DEFAULT_HORIZON + 1))
    rows = await agent_decision_service.pending_settlements(threshold.isoformat())
    if not rows:
        return 0

    settled = 0
    # 按 code 去重后逐票拉收盘价：一次 get_spot_quote 批量请求，不逐只打行情源
    codes = sorted({r["code"] for r in rows})
    try:
        quotes = await asyncio.to_thread(data_service.get_spot_quote, codes)
        price_map = {q.code: q.price for q in quotes if q.price}
    except Exception as e:
        print(f"[sim] agent 结算行情拉取失败: {e}")
        return 0

    for row in rows:
        price = price_map.get(row["code"])
        if not price:
            continue  # 停牌/拿不到行情：顺延到下次 cron
        if await agent_decision_service.settle_one(row, price):
            settled += 1
    return settled
