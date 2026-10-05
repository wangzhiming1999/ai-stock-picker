"""Run reproducible cross-pool validation for ETF category strategies."""
from __future__ import annotations

import json
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.recommend_history_replay_service import (
    DEFAULT_ETF_GROUPS,
    run_etf_historical_calibration,
)


ETF_POOLS = {
    "sample_a": {group: codes[:2] for group, codes in DEFAULT_ETF_GROUPS.items()},
    "sample_b": {group: codes[2:] for group, codes in DEFAULT_ETF_GROUPS.items()},
}
EVAL_DAYS = 1200


def _validity_summary(row: dict) -> dict:
    fill_days = {"1": [], "2": [], "3": []}
    rejection_reasons = {}
    for window in row.get("windows", []):
        metrics = window.get("validation_metrics") or {}
        for reason, count in (metrics.get("rejection_reasons") or {}).items():
            rejection_reasons[reason] = rejection_reasons.get(reason, 0) + int(count)
        for day, values in (metrics.get("by_fill_day") or {}).items():
            if values.get("filled"):
                fill_days.setdefault(day, []).append(values)
    return {
        "window_count": row.get("window_count"),
        "passed_windows": row.get("passed_windows"),
        "required_windows": row.get("required_windows"),
        "consensus_validity_days": row.get("consensus_validity_days"),
        "matching_windows": row.get("matching_windows"),
        "fill_day_totals": {
            day: {
                "filled": sum(value["filled"] for value in values),
                "weighted_hit_rate": round(
                    sum(value["hit_rate"] * value["filled"] for value in values)
                    / sum(value["filled"] for value in values), 2
                ) if values else None,
                "weighted_avg_excess_return": round(
                    sum(value["avg_excess_return"] * value["filled"] for value in values)
                    / sum(value["filled"] for value in values), 4
                ) if values else None,
                "worst_excess_return": min(
                    (value["min_excess_return"] for value in values), default=None
                ),
            }
            for day, values in fill_days.items()
        },
        "eligible_for_review": row.get("eligible_for_review"),
        "rejection_reasons": rejection_reasons,
    }


def _cross_sectional_summary(row: dict) -> dict:
    return {
        "window_count": row.get("window_count"),
        "passed_windows": row.get("passed_windows"),
        "required_windows": row.get("required_windows"),
        "consensus_factor": row.get("consensus_factor"),
        "consensus_direction": row.get("consensus_direction"),
        "matching_windows": row.get("matching_windows"),
        "matching_factor_direction_windows": row.get("matching_factor_direction_windows"),
        "evaluation_codes": row.get("evaluation_codes"),
        "rank_reference_codes": row.get("rank_reference_codes"),
        "min_abs_train_rank_ic": row.get("min_abs_train_rank_ic"),
        "min_abs_validation_rank_ic": row.get("min_abs_validation_rank_ic"),
        "eligible_for_review": row.get("eligible_for_review"),
        "windows": [
            {
                "factor": window.get("selected_factor"),
                "direction": window.get("direction"),
                "validation_rank_ic": (
                    ((window.get("validation_diagnostics") or {}).get("horizons") or {})
                    .get("1", {})
                    .get("mean_rank_ic")
                ),
                "preferred_spread": window.get("preferred_spread"),
                "observations": (window.get("validation_diagnostics") or {}).get(
                    "observation_count"
                ),
                "rank_reference_observations": (
                    window.get("validation_diagnostics") or {}
                ).get("rank_reference_observation_count"),
                "reason": window.get("reason"),
                "passed": window.get("passed"),
            }
            for window in row.get("windows", [])
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--section", choices=("all", "factors"), default="all")
    args = parser.parse_args()
    if args.section == "factors":
        evaluation_pools = {
            name: [code for codes in groups.values() for code in codes]
            for name, groups in ETF_POOLS.items()
        }
        result = run_etf_historical_calibration(
            etf_groups=DEFAULT_ETF_GROUPS,
            cross_sectional_evaluation_pools=evaluation_pools,
            eval_days=EVAL_DAYS,
            min_train_days=240,
            validation_days=60,
        )
        reports = {
            pool_name: {
                "loaded_universe": result.get("loaded_universe"),
                "usable_samples": result.get("usable_samples"),
                "cross_sectional_factors": {
                    group: _cross_sectional_summary(row)
                    for group, row in group_rows.items()
                },
            }
            for pool_name, group_rows in result[
                "rolling_cross_sectional_pool_research"
            ].items()
        }
        print(json.dumps({"reports": reports}, ensure_ascii=False, indent=2))
        return
    reports = {}
    for name, groups in ETF_POOLS.items():
        result = run_etf_historical_calibration(
            etf_groups=groups,
            eval_days=EVAL_DAYS,
            min_train_days=240,
            validation_days=60,
        )
        reports[name] = {
            "groups": groups,
            "loaded_universe": result.get("loaded_universe"),
            "usable_samples": result.get("usable_samples"),
            "order_validity": {
                group: _validity_summary(row)
                for group, row in result["rolling_order_validity_research"].items()
            },
            "high_win_rate": {
                group: {
                    "window_count": row.get("window_count"),
                    "passed_windows": row.get("passed_windows"),
                    "required_windows": row.get("required_windows"),
                    "consensus_high_win_profile": row.get("consensus_high_win_profile"),
                    "matching_windows": row.get("matching_windows"),
                    "eligible_for_review": row.get("eligible_for_review"),
                    "windows": [
                        {
                            "profile": window.get("selected_high_win_profile"),
                            "filled": (window.get("validation_metrics") or {}).get("filled"),
                            "hit_rate": (window.get("validation_metrics") or {}).get("hit_rate"),
                            "avg_excess_return": (window.get("validation_metrics") or {}).get("avg_excess_return"),
                            "baseline_filled": (window.get("baseline_validation_metrics") or {}).get("filled"),
                            "baseline_hit_rate": (window.get("baseline_validation_metrics") or {}).get("hit_rate"),
                            "baseline_avg_excess_return": (window.get("baseline_validation_metrics") or {}).get("avg_excess_return"),
                            "hit_rate_lift": window.get("hit_rate_lift"),
                            "passed": window.get("passed"),
                        }
                        for window in row.get("windows", [])
                    ],
                }
                for group, row in result["rolling_high_win_rate_research"].items()
            },
            "cross_sectional_factors": {
                group: _cross_sectional_summary(row)
                for group, row in result["rolling_cross_sectional_factor_research"].items()
            },
        }
    print(json.dumps({"reports": reports}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
