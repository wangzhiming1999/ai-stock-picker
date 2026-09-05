"""今日作战简报：把分散的数据聚合成「打开就知道今天怎么干」的指令卡。

设计目标（产品定位）：从指标展示转向行动指令。
- 盘前/早盘：今天大方向（多/空/震荡）+ 建议仓位 + 今天买什么票（买点/止损/仓位）
- 午后/尾盘：持仓操作结论（卖/买）+ 具体价位 + 买多少

数据全部复用已有缓存（预测/推荐一天一次，行情有缓存），不重复跑 LLM。
"""

from __future__ import annotations

import asyncio
import datetime as dt

from app.services import (
    data_service,
    market_prediction,
    portfolio_service,
    recommend_service,
    signal_service,
    trade_calendar_service,
)

# 风险等级 → 单只最大仓位占比（与 portfolio_service 对齐）
_RISK_POS_PCT: dict[str, int] = {
    "保守": 15,
    "稳健": 20,
    "进取": 25,
    "激进": 35,
}


def _direction_to_position(direction_score: float) -> int:
    """由方向分推导建议仓位成数（0-10）。

    >7 重仓、6-7 偏多、5-6 中性偏多、4-5 中性、<4 轻仓。
    """
    if direction_score >= 7:
        return 7
    if direction_score >= 6:
        return 6
    if direction_score >= 5.5:
        return 5
    if direction_score >= 5:
        return 4
    if direction_score >= 4:
        return 3
    if direction_score >= 3:
        return 2
    return 1


async def _enrich_morning_stock(
    rec: dict, total_capital: float, max_pos_pct: int, risk_level: str
) -> dict:
    """给推荐票补技术信号（买点/止损/卖点）与建议仓位手数。"""
    base = {
        "code": str(rec.get("code", "")),
        "name": rec.get("name", ""),
        "price": rec.get("price"),
        "change_pct": rec.get("change_pct"),
        "reason": rec.get("reason", ""),
        "confidence": rec.get("confidence", 0),
        "id": rec.get("id"),  # 关联 daily_recommendations.id，供模拟盘回写 related_reco_id 闭合胜率环
        "buy_point": None,
        "stop_loss": None,
        "sell_point": None,
        "strength": None,
        "rr_ratio": None,
        "suggest_amount": None,
        "suggest_shares": None,
        "risk_level": risk_level,
    }
    try:
        code = base["code"]
        price = base["price"]
        if not code or not price:
            return base
        hist = await asyncio.to_thread(data_service.get_history, code, 120)
        closes = hist.closes if hist and hist.closes else None
        sig = signal_service.compute_signals(closes, float(price)) if closes else None
        if sig:
            base["buy_point"] = sig.get("buy_point")
            base["stop_loss"] = sig.get("stop_loss")
            base["sell_point"] = sig.get("sell_point")
            base["strength"] = sig.get("strength")
            base["rr_ratio"] = sig.get("rr_ratio")
        # 建议金额 = 总资金 * 单只上限；手数按 100 股一手取整
        amount = round(total_capital * max_pos_pct / 100)
        shares = int(amount // (float(price) * 100) * 100)
        base["suggest_amount"] = amount
        base["suggest_shares"] = max(shares, 0)
    except Exception as e:  # 单只失败不影响整体
        print(f"[briefing]  enrich {base.get('code')} 失败: {e}")
    return base


def _tail_summary(holdings: list[dict]) -> str:
    if not holdings:
        return "暂无持仓，尾盘无需操作"
    sell = sum(1 for h in holdings if "减仓" in (h.get("action") or ""))
    hold = sum(1 for h in holdings if (h.get("action") or "") == "持有观察")
    add = sum(1 for h in holdings if "加仓" in (h.get("action") or ""))
    parts = []
    if sell:
        parts.append(f"{sell} 只建议减仓")
    if add:
        parts.append(f"{add} 只可加仓")
    if hold:
        parts.append(f"{hold} 只持有观察")
    return "、".join(parts) if parts else "持仓均持有观察"


async def _build_review(user_id: str | None) -> dict | None:
    """当日复盘块：持仓盈亏快照 + 今日触发预警 + 操作要点（纯算法拼装，无 LLM）。

    收盘/尾盘时段最有价值；数据缺失时各项为 None，前端按需隐藏。
    """
    if not user_id:
        return None
    review: dict = {"holdings_pnl": None, "alerts_today": None, "actions": None, "summary": None}
    try:
        data = await portfolio_service.list_holdings(user_id)
        holdings = data.get("holdings", [])
        if holdings:
            best = max(holdings, key=lambda h: h.get("pnl_pct") or -1e9)
            worst = min(holdings, key=lambda h: h.get("pnl_pct") or 1e9)
            review["holdings_pnl"] = {
                "total_pnl": data.get("total_pnl"),
                "total_pnl_pct": data.get("total_pnl_pct"),
                "count": len(holdings),
                "best": {"name": best.get("name") or best.get("code"), "pnl_pct": best.get("pnl_pct")},
                "worst": {"name": worst.get("name") or worst.get("code"), "pnl_pct": worst.get("pnl_pct")},
            }
    except Exception:
        pass

    # 今日触发的预警事件（收盘后复盘「盘中发生了什么」）
    try:
        from app.services import alert_service

        events = await alert_service.list_events(user_id, limit=20)
        today = dt.date.today().isoformat()
        todays = [e for e in events if str(e.get("created_at", ""))[:10] == today]
        if todays:
            review["alerts_today"] = [
                {"title": e.get("title"), "message": e.get("message"), "severity": e.get("severity")}
                for e in todays[:5]
            ]
    except Exception:
        pass

    # 汇总一句话
    parts = []
    hp = review["holdings_pnl"]
    if hp and hp.get("total_pnl") is not None:
        sign = "+" if (hp["total_pnl"] or 0) >= 0 else ""
        parts.append(f"持仓盈亏 {sign}{hp['total_pnl']}（{sign}{hp['total_pnl_pct']}%）")
        if hp.get("best") and hp["best"].get("pnl_pct") is not None and hp["best"]["pnl_pct"] > 0:
            parts.append(f"最强 {hp['best']['name']} {sign}{hp['best']['pnl_pct']}%")
        if hp.get("worst") and hp["worst"].get("pnl_pct") is not None and hp["worst"]["pnl_pct"] < 0:
            parts.append(f"最弱 {hp['worst']['name']} {hp['worst']['pnl_pct']}%")
    if review["alerts_today"]:
        parts.append(f"盘中触发 {len(review['alerts_today'])} 条预警")
    review["summary"] = "；".join(parts) if parts else None
    return review


def _enrich_tail_holding(h: dict) -> dict:
    """补尾盘挂单价与挂单建议（算法推导，非成交价）。"""
    out = dict(h)
    out["limit_price"] = None
    out["order_action"] = None
    out["order_hint"] = "暂不操作，观望为主"
    price = h.get("price")
    if not price:
        return out
    try:
        price = float(price)
        action = h.get("action") or "持有观察"
        if "减仓" in action:
            limit = round(price * 1.005, 2)
            out["limit_price"] = limit
            out["order_action"] = "卖出"
            out["order_hint"] = f"尾盘挂单：现价上方约 0.5% 卖出（≈{limit}），优先减仓控风险"
        elif "加仓" in action:
            support = h.get("support")
            base = float(support) if support else round(price * 0.995, 2)
            limit = round(base, 2)
            out["limit_price"] = limit
            out["order_action"] = "买入"
            ref = "支撑位" if support else "现价下方约 0.5%"
            out["order_hint"] = f"尾盘挂单：回踩{ref}买入（≈{limit}）"
    except Exception as e:
        print(f"[briefing] tail enrich {h.get('code')} 失败: {e}")
    return out


async def _fetch_overseas() -> dict | None:
    """隔夜外盘（美股三大指数），供盘前预读。失败返回 None，绝不拖垮主流程。"""
    try:
        import akshare as ak

        def _pull() -> list[dict]:
            df = ak.index_us_stock_sina()
            cols = list(df.columns)
            name_col = "name" if "name" in cols else cols[1]
            price_col = "latest_price" if "latest_price" in cols else ("close" if "close" in cols else cols[2])
            chg_col = "change_pct" if "change_pct" in cols else ("pct_change" if "pct_change" in cols else None)
            wanted = ("道琼斯", "纳斯达克", "标普")
            out = []
            for _, row in df.iterrows():
                nm = str(row[name_col])
                if any(w in nm for w in wanted):
                    try:
                        out.append(
                            {
                                "name": nm,
                                "price": float(row[price_col]),
                                "change_pct": float(row[chg_col]) if chg_col else 0.0,
                            }
                        )
                    except Exception:
                        continue
            return out

        res = await asyncio.wait_for(asyncio.to_thread(_pull), timeout=6)
        return {"indices": res, "note": None} if res else None
    except Exception as e:
        print(f"[briefing] 外盘获取失败: {e}")
        return None


async def build_today(user_id: str | None = None) -> dict:
    """聚合今日作战简报。

    user_id 为 None 时仅返回公开部分（大盘 + 早盘关注），tail 标记 need_login。
    """
    session = trade_calendar_service.session_label()
    is_trading = await trade_calendar_service.is_trading_day_exact()

    # 并行拉取大盘推衍与每日推荐（均有缓存，不会重复跑 LLM）
    pred_task = market_prediction.predict_tomorrow()
    rec_task = recommend_service.generate_daily_recommendations()
    pred, rec = await asyncio.gather(pred_task, rec_task)

    summary = (pred.get("summary") or {}) if isinstance(pred, dict) else {}
    direction = market_prediction.normalize_direction(str(summary.get("direction", "震荡")))
    direction_score = float(summary.get("direction_score", 5) or 5)
    pos_pct = _direction_to_position(direction_score)

    # 早盘关注：取推荐前 6 只并补信号 + 仓位
    profile = None
    if user_id:
        try:
            profile = await portfolio_service.get_profile(user_id)
        except Exception:
            profile = None
    risk_level = (profile or {}).get("risk_level", "稳健")
    max_pos_pct = _RISK_POS_PCT.get(risk_level, 20)
    total_capital = float((profile or {}).get("total_capital", 100000) or 100000)

    recs = (rec.get("recommendations") or [])[:6]
    morning_stocks = await asyncio.gather(
        *[_enrich_morning_stock(r, total_capital, max_pos_pct, risk_level) for r in recs]
    )

    # 尾盘动作：需登录，读持仓建议
    tail: dict = {"holdings": [], "summary": None, "need_login": user_id is None}
    if user_id:
        try:
            advice = await portfolio_service.get_portfolio_advice(user_id)
            holdings = advice.get("holdings_advice") or []
            tail["holdings"] = holdings
            tail["summary"] = _tail_summary(holdings)
            tail["risk_level"] = advice.get("risk_level")
        except Exception as e:
            print(f"[briefing] 获取持仓建议失败: {e}")
            tail["summary"] = "持仓建议获取失败"

    phase = _phase_for_session(session, is_trading)
    is_premarket = session in ("盘前", "集合竞价")
    is_tail_urgent = session == "尾盘"

    # 盘前预读：隔夜外盘（仅盘前时段抓取，避免无谓延迟）
    overseas = None
    if is_premarket:
        overseas = await _fetch_overseas()

    # 尾盘持仓补挂单价
    if user_id and tail.get("holdings"):
        tail["holdings"] = [_enrich_tail_holding(h) for h in tail["holdings"]]

    # 当日复盘（登录用户；收盘/尾盘时段前端重点展示）
    review = await _build_review(user_id)

    # 目标交易日：pred 里 target_date 才是"这份简报针对哪个交易日"；
    # pred["date"] 只是行情数据的最后一根 K 线日（数据基准），不能当目标日展示
    pred_date = pred.get("date") if isinstance(pred, dict) else None
    target_date = (pred.get("target_date") if isinstance(pred, dict) else None) or pred_date

    return {
        "session": session,
        "is_trading_day": is_trading,
        "is_premarket": is_premarket,
        "is_tail_urgent": is_tail_urgent,
        # 语义修正：target_date = 要操作的交易日；data_date = 行情数据基准日
        "target_date": target_date,
        "data_date": pred_date,
        "phase": phase,  # morning | tail | closed
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "market": {
            "index": pred.get("index") if isinstance(pred, dict) else None,
            "direction": direction,
            "direction_score": direction_score,
            "position_pct": pos_pct,
            "position_suggestion": f"{pos_pct}成仓",
            "summary": summary.get("summary"),
            "trading_advice": summary.get("trading_advice"),
            "key_levels": summary.get("key_levels"),
            "pre_market": {
                "overseas": overseas["indices"] if overseas else None,
                "note": (overseas["note"] if overseas else "外盘数据暂不可用（网络受限）"),
            },
        },
        "morning": {
            "stocks": morning_stocks,
            "source": rec.get("source"),
            "candidates": rec.get("candidates"),
        },
        "tail": tail,
        "review": review,
    }


def _phase_for_session(session: str, is_trading: bool) -> str:
    """按当前时段决定首屏主卡：早盘看「买什么」、尾盘看「怎么操作」。"""
    if not is_trading:
        return "closed"
    if session in ("盘前", "集合竞价", "早盘"):
        return "morning"
    return "tail"
