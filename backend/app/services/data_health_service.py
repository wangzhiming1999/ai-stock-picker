"""Operational health summary for the recommendation data loop."""
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


def assess_data_health(
    *,
    recommendation_rows: list[dict],
    latest_heartbeat: dict | None,
    latest_market_cache: dict | None,
    checked_at: dt.datetime | None = None,
    query_errors: dict[str, str] | None = None,
) -> dict:
    """Build a deterministic health result from already-fetched observations."""
    now = (checked_at or dt.datetime.now(UTC)).astimezone(UTC)
    errors = query_errors or {}
    issues = [
        _issue("health_query_failed", "critical", message, component)
        for component, message in errors.items()
    ]

    settled = [row for row in recommendation_rows if row.get("settled_at")]
    pending = [row for row in recommendation_rows if not row.get("settled_at")]
    pending_dates = sorted(str(row.get("rec_date"))[:10] for row in pending if row.get("rec_date"))
    settled_times = [_parse_time(row.get("settled_at")) for row in settled]
    latest_settled = max((value for value in settled_times if value), default=None)

    heartbeat_at = _parse_time((latest_heartbeat or {}).get("created_at"))
    heartbeat_age = round((now - heartbeat_at).total_seconds() / 3600, 1) if heartbeat_at else None
    if "heartbeat" not in errors:
        if heartbeat_at is None:
            issues.append(_issue("cron_heartbeat_missing", "critical", "尚未发现成功的每日结算心跳", "cron"))
        elif heartbeat_age is not None and heartbeat_age >= 72:
            issues.append(_issue("cron_heartbeat_expired", "critical", "每日结算心跳已超过72小时", "cron"))
        elif heartbeat_age is not None and heartbeat_age >= 36:
            issues.append(_issue("cron_heartbeat_stale", "warning", "每日结算心跳已超过36小时", "cron"))

    oldest_pending_age = None
    if pending_dates:
        try:
            oldest_pending_age = (now.date() - dt.date.fromisoformat(pending_dates[0])).days
        except ValueError:
            pass
    if "recommendations" not in errors and oldest_pending_age is not None and oldest_pending_age >= 3:
        issues.append(_issue("settlement_backlog", "critical", "存在超过3天仍未结算的推荐", "settlement"))

    market_at = _parse_time((latest_market_cache or {}).get("updated_at"))
    market_age = round((now - market_at).total_seconds() / 3600, 1) if market_at else None
    readiness = recommend_calibration_service.assess_feature_snapshot_readiness(recommendation_rows)

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
        "settlement": {
            "eligible_rows": len(recommendation_rows),
            "settled_rows": len(settled),
            "pending_rows": len(pending),
            "oldest_pending_date": pending_dates[0] if pending_dates else None,
            "latest_settled_at": latest_settled.isoformat() if latest_settled else None,
        },
        "market_cache": {
            "updated_at": market_at.isoformat() if market_at else None,
            "age_hours": market_age,
        },
        "snapshot_readiness": readiness,
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


async def get_data_health() -> dict:
    if not supabase_store.is_configured():
        return {
            "status": "unavailable",
            "checked_at": dt.datetime.now(UTC).isoformat(),
            "cron": {"last_success_at": None, "snapshot_date": None, "age_hours": None},
            "settlement": None,
            "market_cache": None,
            "snapshot_readiness": None,
            "issues": [_issue("storage_not_configured", "critical", "Supabase未配置", "storage")],
        }

    sb = await supabase_store.get_service_client()
    errors: dict[str, str] = {}
    rows: list[dict] = []
    heartbeat: dict | None = None
    market_cache: dict | None = None
    try:
        rows = await _recommendation_rows(sb)
    except Exception as exc:
        errors["recommendations"] = f"{type(exc).__name__}: {exc}"
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
    return assess_data_health(
        recommendation_rows=rows,
        latest_heartbeat=heartbeat,
        latest_market_cache=market_cache,
        query_errors=errors,
    )
