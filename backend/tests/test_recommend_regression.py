from app.services.recommend_regression_service import (
    compare_production_regressions,
    evaluate_walk_forward_regression,
)


def _sample(day: int, code: str, feature: float, outcome: float) -> dict:
    return {
        "date": f"2026-01-{day:02d}",
        "outcome_date": f"2026-01-{day + 1:02d}",
        "code": code,
        "strategy_scores": {
            "momentum": 5.0 + feature,
            "trend": 5.0,
            "volume": 4.0,
        },
        "historical_volatility": 25.0,
        "signal": {"strength": 7.0, "rr_ratio": 1.0},
        "point_in_time_features": {
            "ma20_distance_pct": feature,
            "gap_pct": 0.0,
            "consecutive_up_days": 1,
        },
        "excess_return": outcome,
    }


def test_walk_forward_regression_selects_positive_outcomes_on_unseen_dates() -> None:
    samples = []
    for day in range(1, 19):
        samples.append(_sample(day, "600001", 1.0, 1.0))
        samples.append(_sample(day, "600002", -1.0, -1.0))

    result = evaluate_walk_forward_regression(
        samples,
        train_days=6,
        validation_days=3,
        top_n=2,
        min_train_samples=10,
        min_oos_selections=6,
    )

    assert result["regression_metrics"]["hit_rate"] == 100.0
    assert result["baseline_metrics"]["hit_rate"] == 50.0
    assert result["hit_rate_lift"] == 50.0
    assert result["coefficient_stability"]["momentum"]["positive_windows"] > 0
    assert result["deployment_eligible"] is True


def test_walk_forward_regression_never_trains_on_validation_outcomes() -> None:
    samples = []
    for day in range(1, 13):
        samples.append(_sample(day, "600001", 1.0, 1.0))
        samples.append(_sample(day, "600002", -1.0, -1.0))
    baseline = evaluate_walk_forward_regression(
        samples,
        train_days=6,
        validation_days=3,
        top_n=2,
        min_train_samples=10,
        min_oos_selections=3,
    )

    mutated = [dict(sample) for sample in samples]
    for sample in mutated:
        if sample["date"] >= "2026-01-07":
            sample["excess_return"] = -float(sample["excess_return"])
    changed = evaluate_walk_forward_regression(
        mutated,
        train_days=6,
        validation_days=3,
        top_n=2,
        min_train_samples=10,
        min_oos_selections=3,
    )

    assert baseline["windows"][0]["selected_codes_by_date"] == changed["windows"][0]["selected_codes_by_date"]


def test_full_factor_regression_is_compared_on_the_same_complete_snapshot_rows() -> None:
    samples = []
    for day in range(1, 19):
        for code, pe, outcome in (("600001", 10.0, 1.2), ("600002", 40.0, -1.0)):
            sample = _sample(day, code, 0.0, outcome)
            sample["strategy_scores"] = {"momentum": 6, "trend": 5, "value": 4, "volume": 4}
            sample["feature_snapshot"] = {
                "pe": pe,
                "pb": 2.0,
                "turnover": 3.0,
                "market_cap_yi": 500.0,
                "market_board": "main",
            }
            samples.append(sample)

    result = compare_production_regressions(
        samples,
        train_days=6,
        validation_days=3,
        top_n=2,
        min_train_samples=10,
        min_oos_selections=6,
    )

    assert result["complete_snapshot_rows"] == len(samples)
    assert result["technical_model"]["baseline_metrics"] == result["full_factor_model"]["baseline_metrics"]
    assert result["full_factor_model"]["regression_metrics"]["hit_rate"] == 100.0
    assert result["full_factor_vs_technical_hit_rate_lift"] == 50.0


def test_full_factor_regression_reports_missing_complete_snapshots() -> None:
    result = compare_production_regressions([_sample(1, "600001", 1.0, 1.0)])

    assert result["status"] == "insufficient_snapshot_data"
    assert result["complete_snapshot_rows"] == 0
    assert result["deployment_eligible"] is False
