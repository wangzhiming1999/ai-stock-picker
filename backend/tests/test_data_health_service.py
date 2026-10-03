import datetime as dt

from app.services.data_health_service import assess_data_health


UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 3, 8, 0, tzinfo=UTC)


def test_recent_heartbeat_without_overdue_rows_is_healthy():
    result = assess_data_health(
        recommendation_rows=[
            {"rec_date": "2026-10-02", "settled_at": "2026-10-03T07:00:00Z", "source": "rule", "feature_snapshot": {}},
        ],
        latest_heartbeat={"created_at": "2026-10-03T07:30:00Z", "snapshot_date": "2026-10-03"},
        latest_market_cache={"updated_at": "2026-10-03T07:40:00Z"},
        checked_at=NOW,
    )

    assert result["status"] == "healthy"
    assert result["settlement"]["pending_rows"] == 0
    assert result["settlement"]["settled_rows"] == 1
    assert result["cron"]["age_hours"] == 0.5
    assert result["issues"] == []


def test_missing_heartbeat_and_old_pending_rows_are_critical():
    result = assess_data_health(
        recommendation_rows=[
            {"rec_date": "2026-09-20", "settled_at": None, "source": "rule", "feature_snapshot": {}},
        ],
        latest_heartbeat=None,
        latest_market_cache=None,
        checked_at=NOW,
    )

    assert result["status"] == "critical"
    assert result["settlement"]["pending_rows"] == 1
    assert result["settlement"]["oldest_pending_date"] == "2026-09-20"
    assert {issue["code"] for issue in result["issues"]} >= {"cron_heartbeat_missing", "settlement_backlog"}


def test_stale_heartbeat_is_degraded_before_it_becomes_critical():
    result = assess_data_health(
        recommendation_rows=[],
        latest_heartbeat={"created_at": "2026-10-01T20:00:00Z", "snapshot_date": "2026-10-01"},
        latest_market_cache=None,
        checked_at=NOW,
    )

    assert result["status"] == "degraded"
    assert result["cron"]["age_hours"] == 36.0
    assert result["issues"][0]["code"] == "cron_heartbeat_stale"


def test_query_errors_are_reported_without_fabricating_healthy_state():
    result = assess_data_health(
        recommendation_rows=[],
        latest_heartbeat=None,
        latest_market_cache=None,
        checked_at=NOW,
        query_errors={"recommendations": "database unavailable"},
    )

    assert result["status"] == "unavailable"
    assert result["issues"][0]["code"] == "health_query_failed"
    assert result["issues"][0]["component"] == "recommendations"
