"""胜率统计服务：预测命中率 + 推荐胜率统计与结算。"""
from __future__ import annotations

import datetime as dt

from app.services import data_service, market_prediction, supabase_store


async def settle_daily_recommendations() -> int:
    """结算未结算的推荐：用最近交易日收盘价对比推荐价，判断次日是否上涨。"""
    if not supabase_store.is_configured():
        return 0
    sb = await supabase_store.get_service_client()

    # 找未结算的推荐（排除今天刚生成的）
    today = dt.date.today().isoformat()
    res = (
        await sb.table("daily_recommendations")
        .select("id", "code", "recommend_price")
        .is_("settled_at", "null")
        .lt("rec_date", today)
        .execute()
    )
    rows = res.data
    if not rows:
        return 0

    # 批量获取当前行情（腾讯接口，一次多只）
    codes = list({r["code"] for r in rows})
    quotes = await data_service.get_spot_quote(codes)
    quote_map = {q.code: q for q in quotes}

    settled = 0
    for row in rows:
        q = quote_map.get(row["code"])
        if not q or not q.price or not row.get("recommend_price"):
            continue
        recommend_price = row["recommend_price"]
        next_close = q.price
        next_return = (next_close / recommend_price - 1) * 100
        hit = next_return > 0
        await (
            sb.table("daily_recommendations")
            .update(
                {
                    "next_close": round(next_close, 2),
                    "next_return": round(next_return, 2),
                    "hit": hit,
                    "settled_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                }
            )
            .eq("id", row["id"])
            .execute()
        )
        settled += 1

    # 结算后刷新胜率快照
    await refresh_winrate_snapshot()
    return settled


async def get_winrate_stats() -> dict:
    """胜率统计：预测命中率 + 推荐胜率。表未创建时返回空。"""
    if not supabase_store.is_configured():
        return {"prediction": None, "recommendation": None, "snapshot": None}

    sb = await supabase_store.get_service_client()

    # 预测统计
    pred_rows = []
    try:
        pred_res = (
            await sb.table("prediction_records")
            .select("direction", "hit")
            .is_("settled_at", "not.null")
            .execute()
        )
        pred_rows = pred_res.data or []
    except Exception:
        pass
    pred_total = len(pred_rows)
    pred_hit = sum(1 for r in pred_rows if r.get("hit"))
    by_dir: dict = {}
    for r in pred_rows:
        d = r.get("direction", "未知")
        b = by_dir.setdefault(d, {"total": 0, "hit": 0})
        b["total"] += 1
        if r.get("hit"):
            b["hit"] += 1
    for d, b in by_dir.items():
        b["hit_rate"] = round(b["hit"] / b["total"] * 100, 1) if b["total"] else None

    # 推荐统计
    rec_rows = []
    try:
        rec_res = (
            await sb.table("daily_recommendations")
            .select("hit")
            .is_("settled_at", "not.null")
            .execute()
        )
        rec_rows = rec_res.data or []
    except Exception:
        pass
    rec_total = len(rec_rows)
    rec_hit = sum(1 for r in rec_rows if r.get("hit"))

    # 最新快照
    snapshot = None
    try:
        snap_res = (
            await sb.table("winrate_snapshot")
            .select("*")
            .order("id", desc=True)
            .limit(1)
            .execute()
        )
        snapshot = snap_res.data[0] if snap_res.data else None
    except Exception:
        pass

    return {
        "prediction": {
            "total": pred_total,
            "hit": pred_hit,
            "hit_rate": round(pred_hit / pred_total * 100, 1) if pred_total else None,
            "by_direction": by_dir,
        },
        "recommendation": {
            "total": rec_total,
            "hit": rec_hit,
            "hit_rate": round(rec_hit / rec_total * 100, 1) if rec_total else None,
        },
        "snapshot": snapshot,
    }


async def refresh_winrate_snapshot() -> None:
    """写入胜率快照（供看板快速加载）。"""
    if not supabase_store.is_configured():
        return
    stats = await get_winrate_stats()
    p = stats.get("prediction") or {}
    r = stats.get("recommendation") or {}
    sb = await supabase_store.get_service_client()
    await sb.table("winrate_snapshot").insert(
        {
            "snapshot_date": dt.date.today().isoformat(),
            "prediction_total": p.get("total", 0),
            "prediction_hit": p.get("hit", 0),
            "prediction_rate": p.get("hit_rate"),
            "recommend_total": r.get("total", 0),
            "recommend_hit": r.get("hit", 0),
            "recommend_rate": r.get("hit_rate"),
        }
    ).execute()


async def run_daily_cron() -> dict:
    """每日收盘 Cron 任务：结算预测 + 结算推荐 + 刷新胜率快照。"""
    settled_pred = await market_prediction.settle_predictions()
    settled_rec = await settle_daily_recommendations()
    stats = await get_winrate_stats()
    return {
        "settled_predictions": settled_pred,
        "settled_recommendations": settled_rec,
        "stats": stats,
    }
