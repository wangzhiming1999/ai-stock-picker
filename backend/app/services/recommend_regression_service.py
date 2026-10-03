"""Leakage-safe ridge-regression research for recommendation candidates."""
from __future__ import annotations

import math
from statistics import mean

import numpy as np

HISTORICAL_TECHNICAL_FEATURE_NAMES = (
    "momentum",
    "trend",
    "volume",
    "historical_volatility",
    "ma20_distance_pct",
    "gap_pct",
    "consecutive_up_days",
    "signal_strength",
)
PRODUCTION_TECHNICAL_FEATURE_NAMES = ("momentum", "trend", "value", "volume")
FULL_FACTOR_FEATURE_NAMES = (
    *PRODUCTION_TECHNICAL_FEATURE_NAMES,
    "pe",
    "pb",
    "turnover",
    "log_market_cap_yi",
    "board_chinext",
    "board_star",
)
FEATURE_NAMES = HISTORICAL_TECHNICAL_FEATURE_NAMES
_SNAPSHOT_FIELDS = ("pe", "pb", "turnover", "market_cap_yi", "market_board")


def _feature_vector(sample: dict, feature_set: str) -> list[float]:
    scores = sample.get("strategy_scores") or {}
    if feature_set == "production_technical":
        return [float(scores.get(name) or 0) for name in PRODUCTION_TECHNICAL_FEATURE_NAMES]
    if feature_set == "full_factor":
        snapshot = sample.get("feature_snapshot") or {}
        board = str(snapshot.get("market_board") or "")
        market_cap = max(0.0, float(snapshot.get("market_cap_yi") or 0))
        return [
            *[float(scores.get(name) or 0) for name in PRODUCTION_TECHNICAL_FEATURE_NAMES],
            float(snapshot.get("pe") or 0),
            float(snapshot.get("pb") or 0),
            float(snapshot.get("turnover") or 0),
            math.log1p(market_cap),
            1.0 if board == "chinext" else 0.0,
            1.0 if board == "star" else 0.0,
        ]
    point_features = sample.get("point_in_time_features") or {}
    signal = sample.get("signal") or {}
    return [
        float(scores.get("momentum") or 0),
        float(scores.get("trend") or 0),
        float(scores.get("volume") or 0),
        float(sample.get("historical_volatility") or 0),
        float(point_features.get("ma20_distance_pct") or 0),
        float(point_features.get("gap_pct") or 0),
        float(point_features.get("consecutive_up_days") or 0),
        float(signal.get("strength") or 0),
    ]


def _fit_ridge(samples: list[dict], alpha: float, feature_set: str) -> dict:
    features = np.asarray([_feature_vector(sample, feature_set) for sample in samples], dtype=float)
    targets = np.asarray([float(sample["excess_return"]) for sample in samples], dtype=float)
    means = features.mean(axis=0)
    scales = features.std(axis=0)
    scales[scales < 1e-12] = 1.0
    standardized = (features - means) / scales
    design = np.column_stack((np.ones(len(standardized)), standardized))
    penalty = np.eye(design.shape[1]) * max(0.0, float(alpha))
    penalty[0, 0] = 0.0
    coefficients = np.linalg.solve(design.T @ design + penalty, design.T @ targets)
    return {"means": means, "scales": scales, "coefficients": coefficients}


def _predict(model: dict, sample: dict, feature_set: str) -> float:
    features = np.asarray(_feature_vector(sample, feature_set), dtype=float)
    standardized = (features - model["means"]) / model["scales"]
    design = np.concatenate(([1.0], standardized))
    return float(design @ model["coefficients"])


def _metrics(samples: list[dict]) -> dict:
    values = [float(sample["excess_return"]) for sample in samples]
    return {
        "selections": len(values),
        "hit_rate": round(sum(value > 0 for value in values) / len(values) * 100, 2) if values else None,
        "avg_excess_return": round(mean(values), 4) if values else None,
    }


def evaluate_walk_forward_regression(
    samples: list[dict],
    *,
    train_days: int = 80,
    validation_days: int = 20,
    top_n: int = 10,
    alpha: float = 10.0,
    min_train_samples: int = 60,
    min_oos_selections: int = 30,
    feature_set: str = "historical_technical",
) -> dict:
    """Refit ridge regression on prior outcomes and abstain below zero predicted excess."""
    feature_names = {
        "historical_technical": HISTORICAL_TECHNICAL_FEATURE_NAMES,
        "production_technical": PRODUCTION_TECHNICAL_FEATURE_NAMES,
        "full_factor": FULL_FACTOR_FEATURE_NAMES,
    }.get(feature_set)
    if feature_names is None:
        raise ValueError(f"unknown feature_set: {feature_set}")
    dates = sorted({str(sample["date"]) for sample in samples})
    if len(dates) <= train_days:
        return {"status": "insufficient_dates", "deployment_eligible": False, "windows": []}

    windows = []
    all_baseline: list[dict] = []
    all_selected: list[dict] = []
    for start_index in range(train_days, len(dates), validation_days):
        validation_dates = dates[start_index : start_index + validation_days]
        if not validation_dates:
            continue
        train_date_floor = dates[max(0, start_index - train_days)]
        validation_start = validation_dates[0]
        training = [
            sample
            for sample in samples
            if train_date_floor <= str(sample["date"]) < validation_start
            and str(sample.get("outcome_date") or sample["date"]) < validation_start
        ]
        validation_set = set(validation_dates)
        baseline = [sample for sample in samples if str(sample["date"]) in validation_set]
        if len(training) < min_train_samples or not baseline:
            continue

        model = _fit_ridge(training, alpha, feature_set)
        by_date: dict[str, list[tuple[float, dict]]] = {}
        for sample in baseline:
            prediction = _predict(model, sample, feature_set)
            if prediction > 0:
                by_date.setdefault(str(sample["date"]), []).append((prediction, sample))
        selected: list[dict] = []
        selected_codes_by_date: dict[str, list[str]] = {}
        for day in validation_dates:
            ranked = sorted(
                by_date.get(day, []),
                key=lambda item: (-item[0], str(item[1].get("code") or "")),
            )[:top_n]
            selected.extend(sample for _, sample in ranked)
            selected_codes_by_date[day] = [str(sample.get("code") or "") for _, sample in ranked]

        baseline_metrics = _metrics(baseline)
        regression_metrics = _metrics(selected)
        hit_win = (
            regression_metrics["hit_rate"] is not None
            and baseline_metrics["hit_rate"] is not None
            and regression_metrics["hit_rate"] > baseline_metrics["hit_rate"]
        )
        return_win = (
            regression_metrics["avg_excess_return"] is not None
            and baseline_metrics["avg_excess_return"] is not None
            and regression_metrics["avg_excess_return"] > baseline_metrics["avg_excess_return"]
        )
        windows.append(
            {
                "train_start": train_date_floor,
                "train_end": max(str(sample["date"]) for sample in training),
                "validation_start": validation_start,
                "validation_end": validation_dates[-1],
                "train_samples": len(training),
                "baseline_metrics": baseline_metrics,
                "regression_metrics": regression_metrics,
                "hit_rate_win": hit_win,
                "return_win": return_win,
                "selected_codes_by_date": selected_codes_by_date,
                "coefficients": {
                    name: round(float(value), 6)
                    for name, value in zip(feature_names, model["coefficients"][1:])
                },
            }
        )
        all_baseline.extend(baseline)
        all_selected.extend(selected)

    baseline_metrics = _metrics(all_baseline)
    regression_metrics = _metrics(all_selected)
    hit_lift = None
    if regression_metrics["hit_rate"] is not None and baseline_metrics["hit_rate"] is not None:
        hit_lift = round(regression_metrics["hit_rate"] - baseline_metrics["hit_rate"], 2)
    required_win_windows = math.ceil(len(windows) * 2 / 3) if windows else 0
    hit_win_windows = sum(window["hit_rate_win"] for window in windows)
    return_win_windows = sum(window["return_win"] for window in windows)
    coefficient_stability = {}
    for name in feature_names:
        values = [float(window["coefficients"][name]) for window in windows]
        coefficient_stability[name] = {
            "mean_coefficient": round(mean(values), 6) if values else None,
            "positive_windows": sum(value > 0 for value in values),
            "negative_windows": sum(value < 0 for value in values),
            "zero_windows": sum(value == 0 for value in values),
        }
    eligible = (
        len(windows) >= 3
        and regression_metrics["selections"] >= min_oos_selections
        and hit_lift is not None
        and hit_lift >= 3
        and (regression_metrics["avg_excess_return"] or 0) > (baseline_metrics["avg_excess_return"] or 0)
        and hit_win_windows >= required_win_windows
        and return_win_windows >= required_win_windows
    )
    return {
        "status": "eligible_for_review" if eligible else "no_stable_improvement",
        "deployment_eligible": eligible,
        "feature_names": list(feature_names),
        "feature_set": feature_set,
        "alpha": alpha,
        "prediction_threshold": 0.0,
        "baseline_metrics": baseline_metrics,
        "regression_metrics": regression_metrics,
        "hit_rate_lift": hit_lift,
        "window_count": len(windows),
        "required_win_windows": required_win_windows,
        "hit_rate_win_windows": hit_win_windows,
        "return_win_windows": return_win_windows,
        "coefficient_stability": coefficient_stability,
        "windows": windows,
        "caliber": "rolling_standardized_ridge_prior_outcomes_only_positive_predicted_net_excess",
    }


def compare_production_regressions(
    samples: list[dict],
    **kwargs,
) -> dict:
    """Compare technical-only and full-factor ridge models on identical complete snapshots."""
    complete = [
        sample
        for sample in samples
        if all((sample.get("feature_snapshot") or {}).get(field) is not None for field in _SNAPSHOT_FIELDS)
    ]
    if not complete:
        return {
            "status": "insufficient_snapshot_data",
            "deployment_eligible": False,
            "source_rows": len(samples),
            "complete_snapshot_rows": 0,
            "technical_model": None,
            "full_factor_model": None,
            "full_factor_vs_technical_hit_rate_lift": None,
            "caliber": "same_complete_production_snapshot_rows_technical_vs_full_factor",
        }
    technical = evaluate_walk_forward_regression(
        complete,
        feature_set="production_technical",
        **kwargs,
    )
    full_factor = evaluate_walk_forward_regression(
        complete,
        feature_set="full_factor",
        **kwargs,
    )
    technical_hit = (technical.get("regression_metrics") or {}).get("hit_rate")
    full_factor_hit = (full_factor.get("regression_metrics") or {}).get("hit_rate")
    hit_lift = None
    if technical_hit is not None and full_factor_hit is not None:
        hit_lift = round(full_factor_hit - technical_hit, 2)
    technical_return = (technical.get("regression_metrics") or {}).get("avg_excess_return")
    full_factor_return = (full_factor.get("regression_metrics") or {}).get("avg_excess_return")
    eligible = (
        full_factor.get("deployment_eligible") is True
        and hit_lift is not None
        and hit_lift >= 3
        and full_factor_return is not None
        and technical_return is not None
        and full_factor_return > technical_return
    )
    return {
        "status": "eligible_for_review" if eligible else "no_stable_improvement",
        "deployment_eligible": eligible,
        "source_rows": len(samples),
        "complete_snapshot_rows": len(complete),
        "technical_model": technical,
        "full_factor_model": full_factor,
        "full_factor_vs_technical_hit_rate_lift": hit_lift,
        "caliber": "same_complete_production_snapshot_rows_technical_vs_full_factor",
    }
