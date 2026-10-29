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


def test_prediction_settlement_is_absent_when_not_observed():
    """未传入预测行时必须保持 None —— 不能凭空列表冒充「预测零积压」。"""
    result = assess_data_health(
        recommendation_rows=[{"rec_date": "2026-10-02", "settled_at": "2026-10-03T07:00:00Z"}],
        latest_heartbeat={"created_at": "2026-10-03T07:30:00Z", "snapshot_date": "2026-10-03"},
        latest_market_cache=None,
        checked_at=NOW,
    )

    assert result["prediction_settlement"] is None
    assert result["status"] == "healthy"


def test_settled_predictions_are_summarized_by_target_date():
    result = assess_data_health(
        recommendation_rows=[],
        prediction_rows=[
            {"target_date": "2026-10-02", "settled_at": "2026-10-03T07:00:00Z"},
            {"target_date": "2026-10-03", "settled_at": None},
        ],
        latest_heartbeat={"created_at": "2026-10-03T07:30:00Z", "snapshot_date": "2026-10-03"},
        latest_market_cache=None,
        checked_at=NOW,
    )

    block = result["prediction_settlement"]
    assert block["eligible_rows"] == 2
    assert block["settled_rows"] == 1
    assert block["pending_rows"] == 1
    assert block["oldest_pending_date"] == "2026-10-03"
    assert block["latest_settled_at"] == "2026-10-03T07:00:00+00:00"
    assert result["issues"] == []


def test_prediction_backlog_is_reported_without_hiding_recommendation_health():
    """推荐侧完全健康时，预测侧积压仍必须单独报出来 —— 这正是 10-07 漏掉的那条。"""
    result = assess_data_health(
        recommendation_rows=[
            {"rec_date": "2026-10-02", "settled_at": "2026-10-03T07:00:00Z", "source": "rule", "feature_snapshot": {}},
        ],
        prediction_rows=[{"target_date": "2026-09-20", "settled_at": None}],
        latest_heartbeat={"created_at": "2026-10-03T07:30:00Z", "snapshot_date": "2026-10-03"},
        latest_market_cache=None,
        checked_at=NOW,
    )

    codes = {issue["code"] for issue in result["issues"]}
    assert "prediction_settlement_backlog" in codes
    assert "settlement_backlog" not in codes
    assert result["status"] == "critical"


def test_prediction_query_error_is_not_reported_as_backlog():
    result = assess_data_health(
        recommendation_rows=[],
        latest_heartbeat={"created_at": "2026-10-03T07:30:00Z", "snapshot_date": "2026-10-03"},
        latest_market_cache=None,
        checked_at=NOW,
        query_errors={"predictions": "relation does not exist"},
    )

    assert result["prediction_settlement"] is None
    codes = {issue["code"] for issue in result["issues"]}
    assert codes == {"health_query_failed"}
    assert result["issues"][0]["component"] == "predictions"
    assert result["status"] == "unavailable"


def test_recent_rows_without_snapshot_raise_issue():
    """前瞻指标：v18 后新行缺快照 = 正在漏写 → 必须亮灯（不再是历史包袱里的无声数字）。"""
    result = assess_data_health(
        recommendation_rows=[
            # 旧行缺快照：既定事实，不算漏写
            {"rec_date": "2026-10-02", "settled_at": "2026-10-03T07:00:00Z", "source": "rule", "feature_snapshot": {}},
            # 新行缺快照：正在漏写
            {"rec_date": "2026-10-03", "settled_at": "2026-10-04T07:00:00Z", "source": "rule", "feature_snapshot": {}},
            # 新行有快照：正常
            {"rec_date": "2026-10-03", "settled_at": "2026-10-04T07:00:00Z", "source": "rule",
             "feature_snapshot": {"pe": 12, "pb": 2, "turnover": 1, "market_cap_yi": 500, "market_board": "main"}},
        ],
        latest_heartbeat={"created_at": "2026-10-03T07:30:00Z", "snapshot_date": "2026-10-03"},
        latest_market_cache={"updated_at": "2026-10-03T07:40:00Z"},
        checked_at=NOW,
    )

    codes = {issue["code"] for issue in result["issues"]}
    assert "recent_snapshot_missing" in codes
    assert result["recent_snapshot_gap"]["recent_rows"] == 2
    assert result["recent_snapshot_gap"]["recent_rows_without_snapshot"] == 1
    assert result["status"] == "degraded"


def test_write_degradations_surface_as_issues():
    """可选列降级事件（如 feature_snapshot 列缺失）必须进 data-health，不许只躺日志。"""
    result = assess_data_health(
        recommendation_rows=[],
        latest_heartbeat={"created_at": "2026-10-03T07:30:00Z", "snapshot_date": "2026-10-03"},
        latest_market_cache=None,
        checked_at=NOW,
        write_degradations={
            "feature_snapshot": {"count": 2, "last_error": 'column "feature_snapshot" does not exist', "last_at": "2026-10-03T07:00:00"},
        },
    )

    issue = next(i for i in result["issues"] if i["code"] == "optional_column_degraded_feature_snapshot")
    assert issue["severity"] == "critical"
    assert issue["component"] == "snapshot_writer"
    assert result["write_degradations"]["feature_snapshot"]["count"] == 2
    assert result["status"] == "critical"
