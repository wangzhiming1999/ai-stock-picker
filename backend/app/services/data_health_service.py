"""Operational health summary for the recommendation + prediction data loops.

两条结算链路是独立代码路径（``winrate_service`` 结算推荐、``market_prediction`` 结算大盘预测），
历史上只覆盖前者 —— 10-07 生产巡检发现预测侧单轮 0 条 PATCH 却没有任何监控能看见。
本模块因此对两条链路分别出结算块与积压告警，避免「推荐正常」掩盖「预测没在结算」。
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from app.services import recommend_calibration_service, supabase_store

UTC = dt.timezone.utc


def _parse_time(value: Any) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _issue(code: str, severity: str, message: str, component: str) -> dict:
    return {"code": code, "severity": severity, "message": message, "component": component}


def _settlement_block(rows: list[dict], date_field: str) -> dict:
    """Summarize one settlement loop from its raw rows.

    ``date_field`` is the row's own due date (``rec_date`` for recommendations,
    ``target_date`` for predictions) —— 用它而不是 ``settled_at`` 判断积压，
    否则「跑过 cron 但更早的还没结算」会算不出来。
    """
    settled = [row for row in rows if row.get("settled_at")]
    pending = [row for row in rows if not row.get("settled_at")]
    pending_dates = sorted(str(row.get(date_field))[:10] for row in pending if row.get(date_field))
    settled_times = [_parse_time(row.get("settled_at")) for row in settled]
    latest_settled = max((value for value in settled_times if value), default=None)
    return {
        "eligible_rows": len(rows),
        "settled_rows": len(settled),
        "pending_rows": len(pending),
        "oldest_pending_date": pending_dates[0] if pending_dates else None,
        "latest_settled_at": latest_settled.isoformat() if latest_settled else None,
        "_pending_dates": pending_dates,
    }


def _pending_age_days(now: dt.datetime, pending_dates: list[str]) -> int | None:
    if not pending_dates:
        return None
    try:
        return (now.date() - dt.date.fromisoformat(pending_dates[0])).days
    except ValueError:
        return None


def assess_data_health(
    *,
    recommendation_rows: list[dict],
    latest_heartbeat: dict | None,
    latest_market_cache: dict | None,
    prediction_rows: list[dict] | None = None,
    checked_at: dt.datetime | None = None,
    query_errors: dict[str, str] | None = None,
    write_degradations: dict[str, dict] | None = None,
) -> dict:
    """Build a deterministic health result from already-fetched observations.

    ``write_degradations`` 是推荐落库可选列降级事件（recommend_service.rec_column_degradations），
    由调用方注入以保持本函数纯度。
    """
    now = (checked_at or dt.datetime.now(UTC)).astimezone(UTC)
    errors = query_errors or {}
    issues = [
        _issue("health_query_failed", "critical", message, component)
        for component, message in errors.items()
    ]

    settlement = _settlement_block(recommendation_rows, "rec_date")
    pending_dates = settlement.pop("_pending_dates")

    heartbeat_at = _parse_time((latest_heartbeat or {}).get("created_at"))
    heartbeat_age = round((now - heartbeat_at).total_seconds() / 3600, 1) if heartbeat_at else None
    if "heartbeat" not in errors:
        if heartbeat_at is None:
            issues.append(_issue("cron_heartbeat_missing", "critical", "尚未发现成功的每日结算心跳", "cron"))
        elif heartbeat_age is not None and heartbeat_age >= 72:
            issues.append(_issue("cron_heartbeat_expired", "critical", "每日结算心跳已超过72小时", "cron"))
        elif heartbeat_age is not None and heartbeat_age >= 36:
            issues.append(_issue("cron_heartbeat_stale", "warning", "每日结算心跳已超过36小时", "cron"))

    if "recommendations" not in errors and (_pending_age_days(now, pending_dates) or 0) >= 3:
        issues.append(_issue("settlement_backlog", "critical", "存在超过3天仍未结算的推荐", "settlement"))

    prediction_settlement = None
    if prediction_rows is not None:
        prediction_settlement = _settlement_block(prediction_rows, "target_date")
        prediction_pending_dates = prediction_settlement.pop("_pending_dates")
        if "predictions" not in errors and (_pending_age_days(now, prediction_pending_dates) or 0) >= 3:
            issues.append(
                _issue(
                    "prediction_settlement_backlog",
                    "critical",
                    "存在超过3天仍未结算的大盘预测",
                    "prediction_settlement",
                )
            )

    market_at = _parse_time((latest_market_cache or {}).get("updated_at"))
    market_age = round((now - market_at).total_seconds() / 3600, 1) if market_at else None
    readiness = recommend_calibration_service.assess_feature_snapshot_readiness(recommendation_rows)
    # 前瞻指标：覆盖率是历史包袱的函数，这里抓「正在发生的漏写」（新行缺快照）
    recent_gap = recommend_calibration_service.assess_recent_snapshot_gap(
        recommendation_rows, checked_at=now
    )
    if recent_gap["recent_rows_without_snapshot"] > 0:
        issues.append(
            _issue(
                "recent_snapshot_missing",
                "warning",
                f"近{recent_gap['window_days']}日新写 {recent_gap['recent_rows']} 行中 "
                f"{recent_gap['recent_rows_without_snapshot']} 行缺 feature_snapshot"
                f"（{recent_gap['missing_rate_pct']}%）—— 快照正在漏写",
                "snapshot_writer",
            )
        )
    degradations = write_degradations or {}
    for column, event in sorted(degradations.items()):
        severity = "critical" if column in ("feature_snapshot", "strategy_scores") else "warning"
        issues.append(
            _issue(
                f"optional_column_degraded_{column}",
                severity,
                f"daily_recommendations.{column} 列缺失降级写入 {event.get('count', 0)} 次"
                f"（最近错误: {str(event.get('last_error', ''))[:80]}）",
                "snapshot_writer",
            )
        )

    if errors:
        status = "unavailable"
    elif any(issue["severity"] == "critical" for issue in issues):
        status = "critical"
    elif issues:
        status = "degraded"
    else:
        status = "healthy"

    return {
        "status": status,
        "checked_at": now.isoformat(),
        "cron": {
            "last_success_at": heartbeat_at.isoformat() if heartbeat_at else None,
            "snapshot_date": (latest_heartbeat or {}).get("snapshot_date"),
            "age_hours": heartbeat_age,
        },
        "settlement": settlement,
        "prediction_settlement": prediction_settlement,
        "market_cache": {
            "updated_at": market_at.isoformat() if market_at else None,
            "age_hours": market_age,
        },
        "snapshot_readiness": readiness,
        "recent_snapshot_gap": recent_gap,
        "write_degradations": degradations,
        "issues": issues,
    }


async def _recommendation_rows(sb, page_size: int = 1000) -> list[dict]:
    rows: list[dict] = []
    start = 0
    while True:
        response = await (
            sb.table("daily_recommendations")
            .select("rec_date,source,settled_at,feature_snapshot")
            .range(start, start + page_size - 1)
            .execute()
        )
        page = response.data or []
        rows.extend(page)
        if len(page) < page_size:
            return rows
        start += page_size


async def _prediction_rows(sb, page_size: int = 1000) -> list[dict]:
    """预测侧只需要判定积压的字段 —— 不拉全表列，避免把大表读成健康检查瓶颈。"""
    rows: list[dict] = []
    start = 0
    while True:
        response = await (
            sb.table("prediction_records")
            .select("target_date,settled_at")
            .range(start, start + page_size - 1)
            .execute()
        )
        page = response.data or []
        rows.extend(page)
        if len(page) < page_size:
            return rows
        start += page_size


async def get_data_health() -> dict:
    if not supabase_store.is_configured():
        return {
            "status": "unavailable",
            "checked_at": dt.datetime.now(UTC).isoformat(),
            "cron": {"last_success_at": None, "snapshot_date": None, "age_hours": None},
            "settlement": None,
            "prediction_settlement": None,
            "market_cache": None,
            "snapshot_readiness": None,
            "recent_snapshot_gap": None,
            "write_degradations": {},
            "issues": [_issue("storage_not_configured", "critical", "Supabase未配置", "storage")],
        }

    sb = await supabase_store.get_service_client()
    errors: dict[str, str] = {}
    rows: list[dict] = []
    prediction_rows: list[dict] = []
    heartbeat: dict | None = None
    market_cache: dict | None = None
    try:
        rows = await _recommendation_rows(sb)
    except Exception as exc:
        errors["recommendations"] = f"{type(exc).__name__}: {exc}"
    try:
        prediction_rows = await _prediction_rows(sb)
    except Exception as exc:
        errors["predictions"] = f"{type(exc).__name__}: {exc}"
    try:
        response = await sb.table("winrate_snapshot").select("created_at,snapshot_date").order("created_at", desc=True).limit(1).execute()
        heartbeat = (response.data or [None])[0]
    except Exception as exc:
        errors["heartbeat"] = f"{type(exc).__name__}: {exc}"
    try:
        response = await sb.table("market_spot_cache").select("updated_at").order("updated_at", desc=True).limit(1).execute()
        market_cache = (response.data or [None])[0]
    except Exception as exc:
        errors["market_cache"] = f"{type(exc).__name__}: {exc}"
    # 延迟导入：recommend_service 依赖 app.routes.market，模块级互引会成环
    from app.services import recommend_service

    return assess_data_health(
        recommendation_rows=rows,
        prediction_rows=prediction_rows if "predictions" not in errors else None,
        latest_heartbeat=heartbeat,
        latest_market_cache=market_cache,
        query_errors=errors,
        write_degradations=recommend_service.rec_column_degradations(),
    )
