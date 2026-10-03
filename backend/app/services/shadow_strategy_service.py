"""Evaluate candidate recommendation models without changing production behavior."""
from __future__ import annotations

import math

from app.services import recommend_calibration_service, recommend_regression_service, supabase_store


def assess_shadow_candidate(
    *,
    key: str,
    label: str,
    metrics: dict | None,
    baseline: dict | None,
    windows: list[dict],
    evidence_ready: bool,
    min_oos_selections: int = 60,
    min_hit_rate_lift: float = 3.0,
) -> dict:
    metrics = metrics or {}
    baseline = baseline or {}
    selections = int(metrics.get("selections") or 0)
    hit_rate = metrics.get("hit_rate")
    baseline_hit_rate = baseline.get("hit_rate")
    avg_return = metrics.get("avg_excess_return")
    baseline_return = baseline.get("avg_excess_return")
    hit_lift = (
        round(float(hit_rate) - float(baseline_hit_rate), 2)
        if hit_rate is not None and baseline_hit_rate is not None
        else None
    )
    stable_wins = sum(bool(row.get("hit_rate_win")) and bool(row.get("return_win")) for row in windows)
    required_wins = math.ceil(len(windows) * 2 / 3) if windows else 0

    blockers: list[str] = []
    if not evidence_ready:
        blockers.append("point_in_time_evidence_not_ready")
    if selections < min_oos_selections:
        blockers.append(f"oos_selections_below_{min_oos_selections}")
    if hit_lift is None or hit_lift < min_hit_rate_lift:
        blockers.append(f"hit_rate_lift_below_{min_hit_rate_lift:g}pct")
    if avg_return is None or float(avg_return) <= 0:
        blockers.append("avg_net_excess_not_positive")
    if baseline_return is None or avg_return is None or float(avg_return) <= float(baseline_return):
        blockers.append("avg_net_excess_not_above_baseline")
    if len(windows) < 3 or stable_wins < required_wins:
        blockers.append("stable_windows_below_two_thirds")

    eligible = not blockers
    status = "eligible_for_review" if eligible else ("collecting" if not evidence_ready or selections < min_oos_selections else "rejected")
    return {
        "key": key,
        "label": label,
        "status": status,
        "promotion_eligible": eligible,
        "metrics": metrics,
        "baseline_metrics": baseline,
        "hit_rate_lift": hit_lift,
        "window_count": len(windows),
        "stable_win_windows": stable_wins,
        "required_win_windows": required_wins,
        "blockers": blockers,
    }


def _profile_windows(folds: list[dict]) -> list[dict]:
    output = []
    for fold in folds:
        candidate = fold.get("validation_metrics") or {}
        baseline = fold.get("baseline_validation_metrics") or {}
        output.append(
            {
                "hit_rate_win": candidate.get("hit_rate") is not None and baseline.get("hit_rate") is not None and candidate["hit_rate"] > baseline["hit_rate"],
                "return_win": candidate.get("avg_excess_return") is not None and baseline.get("avg_excess_return") is not None and candidate["avg_excess_return"] > baseline["avg_excess_return"],
            }
        )
    return output


def _model_pair_windows(candidate: dict | None, baseline: dict | None) -> list[dict]:
    baseline_by_start = {row.get("validation_start"): row for row in (baseline or {}).get("windows", [])}
    output = []
    for row in (candidate or {}).get("windows", []):
        peer = baseline_by_start.get(row.get("validation_start"))
        if not peer:
            continue
        candidate_metrics = row.get("regression_metrics") or {}
        baseline_metrics = peer.get("regression_metrics") or {}
        output.append(
            {
                "hit_rate_win": candidate_metrics.get("hit_rate") is not None and baseline_metrics.get("hit_rate") is not None and candidate_metrics["hit_rate"] > baseline_metrics["hit_rate"],
                "return_win": candidate_metrics.get("avg_excess_return") is not None and baseline_metrics.get("avg_excess_return") is not None and candidate_metrics["avg_excess_return"] > baseline_metrics["avg_excess_return"],
            }
        )
    return output


def build_shadow_report(
    rows: list[dict],
    *,
    train_days: int = 80,
    validation_days: int = 20,
    top_n: int = 10,
    min_oos_selections: int = 60,
) -> dict:
    samples = recommend_calibration_service.prepare_calibration_samples(rows)
    readiness = recommend_calibration_service.assess_feature_snapshot_readiness(rows)
    sample_dates = len({str(row.get("date")) for row in samples if row.get("date")})
    technical_ready = len(samples) >= min_oos_selections and sample_dates >= 30

    calibration = recommend_calibration_service.calibrate_walk_forward(
        samples,
        min_train_days=train_days,
        validation_days=validation_days,
        top_n=top_n,
        min_train_selections=60,
        min_oos_selections=min_oos_selections,
    )
    technical = recommend_regression_service.evaluate_walk_forward_regression(
        samples,
        train_days=train_days,
        validation_days=validation_days,
        top_n=top_n,
        min_train_samples=60,
        min_oos_selections=min_oos_selections,
        feature_set="production_technical",
    )
    comparison = recommend_regression_service.compare_production_regressions(
        samples,
        train_days=train_days,
        validation_days=validation_days,
        top_n=top_n,
        min_train_samples=60,
        min_oos_selections=min_oos_selections,
    )
    full_factor = comparison.get("full_factor_model") or {}
    complete_technical = comparison.get("technical_model") or {}

    candidates = [
        assess_shadow_candidate(
            key="score_profile",
            label="评分权重候选",
            metrics=calibration.get("oos_metrics"),
            baseline=calibration.get("baseline_oos_metrics"),
            windows=_profile_windows(calibration.get("folds") or []),
            evidence_ready=technical_ready,
            min_oos_selections=min_oos_selections,
        ),
        assess_shadow_candidate(
            key="technical_regression",
            label="技术因子岭回归",
            metrics=technical.get("regression_metrics"),
            baseline=technical.get("baseline_metrics"),
            windows=technical.get("windows") or [],
            evidence_ready=technical_ready,
            min_oos_selections=min_oos_selections,
        ),
        assess_shadow_candidate(
            key="full_factor_regression",
            label="技术+基本面岭回归",
            metrics=full_factor.get("regression_metrics"),
            baseline=complete_technical.get("regression_metrics"),
            windows=_model_pair_windows(full_factor, complete_technical),
            evidence_ready=bool(readiness.get("ready_for_full_factor_replay")),
            min_oos_selections=min_oos_selections,
        ),
    ]
    reviewable = [candidate["key"] for candidate in candidates if candidate["promotion_eligible"]]
    return {
        "status": "eligible_for_review" if reviewable else ("observing" if technical_ready else "collecting"),
        "mode": "shadow_only",
        "production_weights_changed": False,
        "source_rows": len(rows),
        "usable_samples": len(samples),
        "sample_dates": sample_dates,
        "snapshot_readiness": readiness,
        "promotion_requirements": {
            "min_oos_selections": min_oos_selections,
            "min_hit_rate_lift_pct": 3.0,
            "positive_avg_net_excess": True,
            "stable_win_window_ratio": "2/3",
        },
        "reviewable_candidates": reviewable,
        "candidates": candidates,
    }


async def load_production_shadow_report() -> dict:
    if not supabase_store.is_configured():
        return {"status": "storage_not_configured", "mode": "shadow_only", "production_weights_changed": False, "reviewable_candidates": [], "candidates": []}
    sb = await supabase_store.get_service_client()
    rows: list[dict] = []
    page_size = 1000
    for offset in range(0, 100_000, page_size):
        response = await (
            sb.table("daily_recommendations")
            .select("rec_date,code,strategy_scores,excess_return,execution_status,source,settled_at,feature_snapshot")
            .not_.is_("settled_at", None)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        page = response.data or []
        rows.extend(page)
        if len(page) < page_size:
            return build_shadow_report(rows)
    raise RuntimeError("shadow strategy rows exceed 100000; narrow the evaluation window")
