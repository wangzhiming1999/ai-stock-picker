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

    return {
        "session": session,
        "is_trading_day": is_trading,
        "target_date": pred.get("date") if isinstance(pred, dict) else None,
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
        },
        "morning": {
            "stocks": morning_stocks,
            "source": rec.get("source"),
            "candidates": rec.get("candidates"),
        },
        "tail": tail,
    }


def _phase_for_session(session: str, is_trading: bool) -> str:
    """按当前时段决定首屏主卡：早盘看「买什么」、尾盘看「怎么操作」。"""
    if not is_trading:
        return "closed"
    if session in ("盘前", "集合竞价", "早盘"):
        return "morning"
    return "tail"
