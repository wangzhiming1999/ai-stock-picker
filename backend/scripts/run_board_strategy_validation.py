"""Cross-sample validation for board-specific gate and execution schemes."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.recommend_history_replay_service import (
    assess_board_profile_consensus,
    run_historical_calibration,
)


POOLS = {
    "sample_1": ["600519", "000858", "601318", "300750", "300059", "300015", "688981", "688111", "688008"],
    "sample_2": ["600036", "000333", "601012", "300124", "300014", "300122", "688012", "688036", "688396"],
    "sample_3": ["002594", "600030", "601888", "300274", "300308", "301269", "688599", "688256", "688169"],
}


def _summary(result: dict) -> dict:
    boards = (result.get("board_specific_research") or {}).get("boards") or {}
    return {
        "loaded_universe": result.get("loaded_universe"),
        "usable_samples": result.get("usable_samples"),
        "boards": {
            board: {
                key: row.get(key)
                for key in (
                    "status",
                    "selected_profile",
                    "selected_setup",
                    "validation_metrics",
                    "baseline_validation_metrics",
                    "hit_rate_lift",
                    "stable_win_windows",
                    "required_stable_windows",
                    "deployment_eligible",
                    "blockers",
                )
            }
            for board, row in boards.items()
        },
    }


def main() -> None:
    reports = {}
    for name, codes in POOLS.items():
        reports[name] = _summary(
            run_historical_calibration(
                codes=codes,
                eval_days=300,
                top_n=6,
                min_train_days=80,
                validation_days=20,
            )
        )
    consensus = {
        board: assess_board_profile_consensus(
            [report["boards"][board] for report in reports.values()]
        )
        for board in ("main", "chinext", "star")
    }
    print(json.dumps({"reports": reports, "consensus": consensus}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
