"""胜率统计服务：预测命中率 + 推荐胜率统计与结算。"""
from __future__ import annotations

import asyncio
import datetime as dt

from app.services import backtest_service, calibers, concurrency, data_service, market_prediction, supabase_store, trade_calendar_service

def _next_close_after(history, rec_date: str) -> tuple[str, float] | None:
    """返回推荐日后的首个真实交易日收盘，禁止用 Cron 执行时现价替代。"""
    if not history:
        return None
    for date, close in zip(history.dates, history.closes):
        if str(date)[:10] > rec_date and close:
            return str(date)[:10], float(close)
    return None


def _sample_status(total: int) -> str:
    if total < 30:
        return "insufficient"
    if total < 100:
        return "developing"
    return "established"


# 推荐结算口径：扣费后对比沪深300 同区间收益，超额为正才算「赢」。
# RECO_FEE_PCT 是保守的 A 股双边成本估算（买入佣金 + 卖出佣金 + 印花税 + 滑点），
# 作为四舍五入前的净收益扣减项；未来若拿到更精确的费率可在此单点调整。
RECO_FEE_PCT = 0.15
# 结算用的基准指数（与 backtest_service.BENCHMARK 同源，避免两处各写一份）。
RECO_BENCHMARK = backtest_service.BENCHMARK


def _index_window_return(bench_hist, rec_date: str, next_date: str) -> float | None:
    """基准指数在 [推荐日收盘, 次一交易日收盘] 区间的收益率 %。

    与推荐持有期严格对齐：推荐日(rec_date)收盘买入、次一交易日(next_date)收盘卖出，
    基准做同样操作的买入持有收益。指数数据缺失时返回 None（上层静默回退到旧口径）。
    """
    if not bench_hist:
        return None
    closes = {str(d)[:10]: float(c) for d, c in zip(bench_hist.dates, bench_hist.closes)}
    rec_close = closes.get(rec_date)
    next_close = closes.get(next_date)
    if rec_close and next_close:
        return (next_close / rec_close - 1) * 100
    return None


def _reco_outcome(
    next_return: float, benchmark_return: float | None, fee_pct: float
) -> tuple[float | None, float | None, bool]:
    """把「次日收益率」换算成扣费后、对比基准的结算结论。

    返回 (net_return, excess_return, hit)：
    - 基准可得时：net = 次日收益 − 费用；excess = net − 基准；hit = excess > 0（跑赢指数才算赢）。
    - 基准不可得时（v14 迁移未跑 / 指数数据缺失）：降级为旧口径，hit = 次日收益 > 0，
      excess_return 置空，由上层用 benchmark_available 标记「未跑赢指数」不可信。
    """
    net_return = round(next_return - fee_pct, 2)
    if benchmark_return is None:
        return net_return, None, next_return > 0
    excess_return = round(net_return - benchmark_return, 2)
    return net_return, excess_return, excess_return > 0


async def _safe_reco_update(sb, row_id: int, fields: dict, bench_ok: bool) -> bool:
    """写入结算结果；新列(benchmark_return/net_return/excess_return)不存在时静默降级只写旧字段。

    返回 bench_ok：一旦发现列缺失就置 False，后续行不再尝试新列，避免每行都打一次失败请求。
    """
    if bench_ok and "benchmark_return" in fields:
        try:
            await sb.table("daily_recommendations").update(fields).eq("id", row_id).execute()
            return True
        except Exception as e:
            if "does not exist" in str(e):
                bench_ok = False
            else:
                raise
    minimal = {k: v for k, v in fields.items() if k in ("next_close", "next_return", "hit", "settled_at")}
    await sb.table("daily_recommendations").update(minimal).eq("id", row_id).execute()
    return bench_ok


async def settle_daily_recommendations() -> int:
    """结算未结算的推荐：用最近交易日收盘价对比推荐价，判断次日是否上涨。"""
    if not supabase_store.is_configured():
        return 0
    sb = await supabase_store.get_service_client()

    # 找未结算的推荐（rec_date 早于最近交易日，即已到结算时点）
    data_day = await trade_calendar_service.last_trading_day()
    res = (
        await sb.table("daily_recommendations")
        .select("id", "code", "rec_date", "recommend_price")
        .is_("settled_at", "null")
        .lt("rec_date", data_day.isoformat())
        .execute()
    )
    rows = res.data
    if not rows:
        return 0

    # 批量获取历史 K 线，精确选择推荐后的首个交易日收盘。
    codes = list({r["code"] for r in rows})
    histories = await concurrency.gather_limited(
        asyncio.to_thread(data_service.get_history, code, 200) for code in codes
    )
    history_map = dict(zip(codes, histories))
    # 基准指数历史只需拉一次，所有推荐共用同一持有期对齐方式。
    bench_hist = await data_service.get_history(RECO_BENCHMARK, 200)

    settled = 0
    settled_at = dt.datetime.now(dt.timezone.utc).isoformat()
    bench_ok = True  # 新列是否存在；一旦缺失就降级为只写旧字段
    for row in rows:
        rec_date = str(row.get("rec_date") or "")[:10]
        settled_quote = _next_close_after(history_map.get(row["code"]), rec_date)
        if not settled_quote or not row.get("recommend_price"):
            continue
        recommend_price = row["recommend_price"]
        _next_date, next_close = settled_quote
        next_return = (next_close / recommend_price - 1) * 100
        benchmark_return = (
            _index_window_return(bench_hist, rec_date, _next_date) if bench_ok else None
        )
        net_return, excess_return, hit = _reco_outcome(next_return, benchmark_return, RECO_FEE_PCT)
        fields = {
            "next_close": round(next_close, 2),
            "next_return": round(next_return, 2),
            "hit": hit,
            "settled_at": settled_at,
        }
        if benchmark_return is not None:
            fields["benchmark_return"] = round(benchmark_return, 2)
            fields["net_return"] = net_return
            fields["excess_return"] = excess_return
        bench_ok = await _safe_reco_update(sb, row["id"], fields, bench_ok)
        settled += 1

    # 结算后刷新胜率快照
    await refresh_winrate_snapshot()
    return settled


def _err_note(e: Exception) -> str:
    return f"{type(e).__name__}: {e}"


async def get_winrate_stats() -> dict:
    """胜率统计：预测命中率 + 推荐胜率。表未创建时返回空。

    每个统计块都带上 `caliber`（口径定义，见 `calibers`）——
    这两个命中率的标的/持有期/分类数都不同，`caliber_note` 明确声明不可比较。
    前端只展示，不自己解释口径。

    DB 查询失败会返回 `error` 与各块 `error`，避免把「取数炸了」显示成「今天还没数据」。
    """
    if not supabase_store.is_configured():
        return {
            "prediction": None,
            "recommendation": None,
            "snapshot": None,
            "error": "supabase_not_configured",
            "caliber_note": calibers.note(),
        }

    sb = await supabase_store.get_service_client()

    # 预测统计
    pred_rows: list[dict] = []
    pred_error: str | None = None
    try:
        pred_res = (
            await sb.table("prediction_records")
            .select("direction", "hit")
            .not_.is_("settled_at", None)
            .execute()
        )
        pred_rows = pred_res.data or []
    except Exception as e:
        pred_error = _err_note(e)
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

    # 推荐统计（带 source 细分）
    # 口径纪律：'quad'（四维榜 Top10）与 'llm'/'rule'（每日推荐）的入选机制完全不同，
    # 命中率不可相加比较 —— 主口径只算推荐链路，quad/watch 单列。
    rec_rows: list[dict] = []
    rec_error: str | None = None
    try:
        rec_res = (
            await sb.table("daily_recommendations")
            .select("hit", "source", "excess_return")
            .not_.is_("settled_at", None)
            .execute()
        )
        rec_rows = rec_res.data or []
    except Exception as e:
        # v14 迁移未跑时 excess_return 列不存在 → 静默降级为只取旧字段，
        # 避免「列不存在」被显示成「推荐记录查询失败」、把整个推荐块打空。
        if "excess_return" in str(e):
            try:
                rec_res = (
                    await sb.table("daily_recommendations")
                    .select("hit", "source")
                    .not_.is_("settled_at", None)
                    .execute()
                )
                rec_rows = rec_res.data or []
            except Exception as e2:
                rec_error = f"daily_recommendations: {_err_note(e2)}"
        else:
            rec_error = f"daily_recommendations: {_err_note(e)}"

    def _is_reco_source(src) -> bool:
        return src not in ("quad", "watch")

    reco_rows = [r for r in rec_rows if _is_reco_source(r.get("source"))]
    quad_rows = [r for r in rec_rows if r.get("source") == "quad"]
    watch_rows = [r for r in rec_rows if r.get("source") == "watch"]
    rec_total = len(reco_rows)
    rec_hit = sum(1 for r in reco_rows if r.get("hit"))

    # 超额口径（主口径）：只有带 excess_return 的行才参与，避免把旧口径的 hit 混进来。
    # 全部缺 excess_return（v14 迁移未跑 / 老数据）时 benchmark_available=False，
    # 前端据此标注「未跑赢指数」不可信，并回退展示旧次日胜率。
    excess_rows = [r for r in reco_rows if r.get("excess_return") is not None]
    benchmark_available = len(excess_rows) > 0
    excess_hit = sum(1 for r in excess_rows if r["excess_return"] > 0)
    avg_excess_return = (
        round(sum(r["excess_return"] for r in excess_rows) / len(excess_rows), 2)
        if excess_rows
        else None
    )
    excess_hit_rate = (
        round(excess_hit / len(excess_rows) * 100, 1) if excess_rows else None
    )

    def _block(rows: list[dict]) -> dict:
        total = len(rows)
        hit = sum(1 for r in rows if r.get("hit"))
        return {
            "total": total,
            "hit": hit,
            "hit_rate": round(hit / total * 100, 1) if total else None,
            "sample_status": _sample_status(total),
        }

    # 最新快照
    snapshot = None
    snap_error: str | None = None
    try:
        snap_res = (
            await sb.table("winrate_snapshot")
            .select("*")
            .order("id", desc=True)
            .limit(1)
            .execute()
        )
        snapshot = snap_res.data[0] if snap_res.data else None
    except Exception as e:
        snap_error = f"winrate_snapshot: {_err_note(e)}"

    top_error = " / ".join(filter(None, [pred_error, rec_error, snap_error])) or None

    return {
        "prediction": {
            "total": pred_total,
            "hit": pred_hit,
            "hit_rate": round(pred_hit / pred_total * 100, 1) if pred_total else None,
            "by_direction": by_dir,
            "sample_status": _sample_status(pred_total),
            "caliber": calibers.describe("prediction"),
            "error": pred_error,
        },
        "recommendation": {
            "total": rec_total,
            "hit": rec_hit,
            "hit_rate": round(rec_hit / rec_total * 100, 1) if rec_total else None,
            "sample_status": _sample_status(rec_total),
            "caliber": calibers.describe("recommendation"),
            "by_source": {
                "quad": _block(quad_rows),
                "watch": _block(watch_rows),
            },
            # 超额口径（主口径）：扣费后跑赢沪深300 才算赢。
            "benchmark_available": benchmark_available,
            "excess_hit": excess_hit,
            "excess_hit_rate": excess_hit_rate,
            "avg_excess_return": avg_excess_return,
            "error": rec_error,
        },
        "snapshot": snapshot,
        "snapshot_error": snap_error,
        "error": top_error,
        "caliber_note": calibers.note(),
    }


async def refresh_winrate_snapshot() -> None:
    """写入胜率快照（供看板快速加载）。"""
    if not supabase_store.is_configured():
        return
    stats = await get_winrate_stats()
    # 查询侧已报错时，不要把「0 命中」污染进历史快照
    if stats.get("error"):
        return
    p = stats.get("prediction") or {}
    r = stats.get("recommendation") or {}
    sb = await supabase_store.get_service_client()
    row = {
        "snapshot_date": dt.date.today().isoformat(),
        "prediction_total": p.get("total", 0),
        "prediction_hit": p.get("hit", 0),
        "prediction_rate": p.get("hit_rate"),
        "recommend_total": r.get("total", 0),
        "recommend_hit": r.get("hit", 0),
        "recommend_rate": r.get("hit_rate"),
        # 超额口径快照（v14 新增列）；列不存在时静默降级只写旧字段。
        "recommend_benchmark_available": r.get("benchmark_available"),
        "recommend_excess_rate": r.get("excess_hit_rate"),
        "recommend_avg_excess": r.get("avg_excess_return"),
    }
    try:
        await sb.table("winrate_snapshot").insert(row).execute()
    except Exception as e:
        if "does not exist" in str(e):
            minimal = {
                k: v
                for k, v in row.items()
                if k
                in (
                    "snapshot_date",
                    "prediction_total",
                    "prediction_hit",
                    "prediction_rate",
                    "recommend_total",
                    "recommend_hit",
                    "recommend_rate",
                )
            }
            await sb.table("winrate_snapshot").insert(minimal).execute()
        else:
            raise


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
