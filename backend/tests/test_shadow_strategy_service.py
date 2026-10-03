from app.services.shadow_strategy_service import assess_shadow_candidate, build_shadow_report


def _window(hit: bool = True, ret: bool = True) -> dict:
    return {"hit_rate_win": hit, "return_win": ret}


def test_candidate_reaches_review_only_when_every_gate_passes():
    result = assess_shadow_candidate(
        key="technical_regression",
        label="技术因子岭回归",
        metrics={"selections": 90, "hit_rate": 56.0, "avg_excess_return": 0.42},
        baseline={"selections": 120, "hit_rate": 51.0, "avg_excess_return": 0.10},
        windows=[_window(), _window(), _window(False, False)],
        evidence_ready=True,
    )

    assert result["status"] == "eligible_for_review"
    assert result["promotion_eligible"] is True
    assert result["hit_rate_lift"] == 5.0
    assert result["blockers"] == []


def test_candidate_is_blocked_when_hit_rate_lift_is_too_small():
    result = assess_shadow_candidate(
        key="score_profile",
        label="评分权重候选",
        metrics={"selections": 100, "hit_rate": 52.0, "avg_excess_return": 0.5},
        baseline={"selections": 100, "hit_rate": 50.0, "avg_excess_return": 0.1},
        windows=[_window(), _window(), _window()],
        evidence_ready=True,
    )

    assert result["promotion_eligible"] is False
    assert "hit_rate_lift_below_3pct" in result["blockers"]


def test_candidate_is_blocked_when_improvement_is_not_stable_across_windows():
    result = assess_shadow_candidate(
        key="technical_regression",
        label="技术因子岭回归",
        metrics={"selections": 90, "hit_rate": 60.0, "avg_excess_return": 0.5},
        baseline={"selections": 120, "hit_rate": 50.0, "avg_excess_return": 0.1},
        windows=[_window(), _window(False, True), _window(True, False)],
        evidence_ready=True,
    )

    assert result["promotion_eligible"] is False
    assert "stable_windows_below_two_thirds" in result["blockers"]


def test_candidate_never_promotes_when_point_in_time_evidence_is_not_ready():
    result = assess_shadow_candidate(
        key="full_factor_regression",
        label="技术+基本面岭回归",
        metrics={"selections": 120, "hit_rate": 60.0, "avg_excess_return": 0.8},
        baseline={"selections": 120, "hit_rate": 50.0, "avg_excess_return": 0.1},
        windows=[_window(), _window(), _window()],
        evidence_ready=False,
    )

    assert result["status"] == "collecting"
    assert "point_in_time_evidence_not_ready" in result["blockers"]


def test_empty_production_sample_returns_collecting_report_without_changing_weights():
    result = build_shadow_report([])

    assert result["status"] == "collecting"
    assert result["mode"] == "shadow_only"
    assert result["production_weights_changed"] is False
    assert [candidate["key"] for candidate in result["candidates"]] == [
        "score_profile",
        "technical_regression",
        "full_factor_regression",
    ]
