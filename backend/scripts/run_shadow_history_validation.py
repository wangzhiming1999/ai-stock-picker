"""Run reproducible real-history validation for shadow recommendation candidates."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.backtest_service import STRATEGY_BACKTEST_POOL
from app.services.recommend_history_replay_service import run_historical_calibration
from app.services.shadow_strategy_service import _profile_windows, assess_shadow_candidate


def _candidate(result: dict, kind: str) -> dict:
    if kind == "score":
        candidate = assess_shadow_candidate(
            key="score_profile",
            label="评分权重候选",
            metrics=result.get("oos_metrics"),
            baseline=result.get("baseline_oos_metrics"),
            windows=_profile_windows(result.get("folds") or []),
            evidence_ready=True,
        )
    else:
        regression = result.get("regression_research") or {}
        candidate = assess_shadow_candidate(
            key="technical_regression",
            label="技术因子岭回归",
            metrics=regression.get("regression_metrics"),
            baseline=regression.get("baseline_metrics"),
            windows=regression.get("windows") or [],
            evidence_ready=True,
        )
    return {
        "metrics": candidate["metrics"],
        "hit_rate_lift": candidate["hit_rate_lift"],
        "stable_windows": f'{candidate["stable_win_windows"]}/{candidate["window_count"]}',
        "promotion_eligible": candidate["promotion_eligible"],
        "blockers": candidate["blockers"],
    }


def main() -> None:
    pools = {
        "core_1": STRATEGY_BACKTEST_POOL[:6],
        "core_2": STRATEGY_BACKTEST_POOL[6:12],
        "core_3": STRATEGY_BACKTEST_POOL[12:18],
    }
    reports = []
    for name, codes in pools.items():
        result = run_historical_calibration(
            codes=codes,
            eval_days=300,
            top_n=6,
            min_train_days=80,
            validation_days=20,
        )
        reports.append(
            {
                "pool": name,
                "codes": codes,
                "loaded_universe": result.get("loaded_universe"),
                "usable_samples": result.get("usable_samples"),
                "validation_scope": result.get("validation_scope"),
                "score_profile": _candidate(result, "score"),
                "technical_regression": _candidate(result, "regression"),
            }
        )
    print(json.dumps(reports, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
