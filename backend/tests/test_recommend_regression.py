from app.services.recommend_regression_service import evaluate_walk_forward_regression


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
