"""Leakage-safe calibration for the production recommendation scoring formula.

The calibrator deliberately consumes logged component scores instead of
recomputing a similar-looking historical indicator model.  This keeps offline
validation and the live ranker on exactly the same feature contract.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import mean


@dataclass(frozen=True)
class ScoringProfile:
    key: str
    momentum_weight: float
    trend_weight: float
    momentum_min: float = 4.0
    trend_min: float = 3.5
    confirmation_min: float = 4.0
    confirmation_bonus: float = 0.25

    def to_dict(self) -> dict:
        return asdict(self)


BASELINE_PROFILE = ScoringProfile("baseline", 0.7, 0.3)
SCORING_PROFILES = (
    BASELINE_PROFILE,
    ScoringProfile("balanced", 0.6, 0.4),
    ScoringProfile("trend_tilt", 0.5, 0.5),
    ScoringProfile("strict_momentum", 0.75, 0.25, momentum_min=4.5),
)


def prepare_calibration_samples(rows: list[dict]) -> list[dict]:
    """Normalize settled production rows and reject incomparable observations."""
    samples: list[dict] = []
    for row in rows:
        if row.get("source") not in ("rule", "watch"):
            continue
        if row.get("execution_status") in ("not_triggered", "unverifiable"):
            continue
        scores = row.get("strategy_scores")
        if not isinstance(scores, dict) or not scores or row.get("excess_return") is None:
            continue
        if not row.get("rec_date") or not row.get("code"):
            continue
        samples.append(
            {
                "date": str(row["rec_date"]),
                "code": str(row["code"]),
                "strategy_scores": scores,
                "excess_return": float(row["excess_return"]),
            }
        )
    return samples


def score_strategy_components(scores: dict, profile: ScoringProfile = BASELINE_PROFILE) -> float | None:
    """Apply the live recommendation gates and score for one candidate."""
    momentum = float(scores.get("momentum") or 0)
    trend = float(scores.get("trend") or 0)
    if momentum < profile.momentum_min or trend < profile.trend_min:
        return None
    confirmations = sum(
        1
        for name in ("value", "volume")
        if float(scores.get(name) or 0) >= profile.confirmation_min
    )
    return min(
        10.0,
        momentum * profile.momentum_weight
        + trend * profile.trend_weight
        + confirmations * profile.confirmation_bonus,
    )


def _select(samples: list[dict], profile: ScoringProfile, top_n: int) -> list[dict]:
    by_date: dict[str, list[tuple[float, dict]]] = {}
    for sample in samples:
        if sample.get("excess_return") is None:
            continue
        score = score_strategy_components(sample.get("strategy_scores") or {}, profile)
        if score is None:
            continue
        by_date.setdefault(str(sample["date"]), []).append((score, sample))

    selected: list[dict] = []
    for rows in by_date.values():
        rows.sort(key=lambda item: (-item[0], str(item[1].get("code") or "")))
        selected.extend(sample for _, sample in rows[:top_n])
    return selected


def _metrics(samples: list[dict]) -> dict:
    returns = [float(sample["excess_return"]) for sample in samples]
    return {
        "selections": len(returns),
        "hit_rate": round(sum(value > 0 for value in returns) / len(returns) * 100, 2) if returns else None,
        "avg_excess_return": round(mean(returns), 4) if returns else None,
    }


def _training_key(metrics: dict, profile_index: int) -> tuple:
    """Prefer hit rate, then excess return; stable order wins exact ties."""
    return (
        metrics["hit_rate"] if metrics["hit_rate"] is not None else -1,
        metrics["avg_excess_return"] if metrics["avg_excess_return"] is not None else -999,
        metrics["selections"],
        -profile_index,
    )


def calibrate_walk_forward(
    samples: list[dict],
    *,
    profiles: tuple[ScoringProfile, ...] = SCORING_PROFILES,
    min_train_days: int = 20,
    validation_days: int = 5,
    top_n: int = 10,
    min_train_selections: int = 30,
    min_oos_selections: int = 60,
    min_hit_rate_lift: float = 3.0,
) -> dict:
    """Expanding-window selection with untouched next-window validation."""
    if not profiles:
        raise ValueError("profiles must not be empty")
    if min_train_days < 1 or validation_days < 1 or top_n < 1 or min_train_selections < 1:
        raise ValueError("window sizes and top_n must be positive")

    usable = [
        sample
        for sample in samples
        if sample.get("date") and sample.get("strategy_scores") and sample.get("excess_return") is not None
    ]
    dates = sorted({str(sample["date"]) for sample in usable})
    folds: list[dict] = []
    adaptive_oos: list[dict] = []
    baseline_oos: list[dict] = []
    skipped_training_windows = 0

    train_size = min_train_days
    while train_size + validation_days <= len(dates):
        train_dates = set(dates[:train_size])
        validation_slice = dates[train_size : train_size + validation_days]
        validation_dates = set(validation_slice)
        train_rows = [sample for sample in usable if str(sample["date"]) in train_dates]
        validation_rows = [sample for sample in usable if str(sample["date"]) in validation_dates]

        training_results = []
        for index, profile in enumerate(profiles):
            metrics = _metrics(_select(train_rows, profile, top_n))
            training_results.append((profile, metrics, index))
        if max(item[1]["selections"] for item in training_results) < min_train_selections:
            skipped_training_windows += 1
            train_size += validation_days
            continue
        selected_profile, train_metrics, _ = max(
            training_results,
            key=lambda item: _training_key(item[1], item[2]),
        )

        selected_validation = _select(validation_rows, selected_profile, top_n)
        baseline_validation = _select(validation_rows, BASELINE_PROFILE, top_n)
        adaptive_oos.extend(selected_validation)
        baseline_oos.extend(baseline_validation)
        folds.append(
            {
                "train_start": dates[0],
                "train_end": dates[train_size - 1],
                "validation_start": validation_slice[0],
                "validation_end": validation_slice[-1],
                "selected_profile": selected_profile.key,
                "train_metrics": train_metrics,
                "validation_metrics": _metrics(selected_validation),
                "baseline_validation_metrics": _metrics(baseline_validation),
            }
        )
        train_size += validation_days

    adaptive_metrics = _metrics(adaptive_oos)
    baseline_metrics = _metrics(baseline_oos)
    selections = adaptive_metrics["selections"]
    hit_lift = None
    if adaptive_metrics["hit_rate"] is not None and baseline_metrics["hit_rate"] is not None:
        hit_lift = round(adaptive_metrics["hit_rate"] - baseline_metrics["hit_rate"], 2)

    eligible = (
        len(folds) >= 3
        and selections >= min_oos_selections
        and hit_lift is not None
        and hit_lift >= min_hit_rate_lift
        and (adaptive_metrics["avg_excess_return"] or 0) > 0
        and (adaptive_metrics["avg_excess_return"] or 0) > (baseline_metrics["avg_excess_return"] or 0)
    )
    if not folds and len(dates) >= min_train_days + validation_days:
        status = "insufficient_training_sample"
        reason = f"训练窗口有效记录不足，每折至少需要 {min_train_selections} 条"
    elif not folds:
        status = "insufficient_dates"
        reason = f"至少需要 {min_train_days + validation_days} 个有效交易日"
    elif selections < min_oos_selections:
        status = "insufficient_oos_sample"
        reason = f"样本外仅 {selections} 条，至少需要 {min_oos_selections} 条"
    elif not eligible:
        status = "no_stable_improvement"
        reason = "样本外胜率和超额收益未同时稳定优于基线"
    else:
        status = "eligible_for_review"
        reason = "达到样本外门槛，可进入人工复核；不会自动上线"

    profile_counts: dict[str, int] = {}
    for fold in folds:
        key = fold["selected_profile"]
        profile_counts[key] = profile_counts.get(key, 0) + 1
    recommended_profile = max(
        profiles,
        key=lambda profile: (profile_counts.get(profile.key, 0), -profiles.index(profile)),
    ).key

    return {
        "status": status,
        "deployment_eligible": eligible,
        "deployment_reason": reason,
        "sample_dates": len(dates),
        "usable_samples": len(usable),
        "folds": folds,
        "skipped_training_windows": skipped_training_windows,
        "oos_metrics": adaptive_metrics,
        "baseline_oos_metrics": baseline_metrics,
        "hit_rate_lift": hit_lift,
        "profile_selection_counts": profile_counts,
        "recommended_profile": recommended_profile,
        "profiles": [profile.to_dict() for profile in profiles],
        "method": "expanding_window_train_then_next_window_validate",
    }
