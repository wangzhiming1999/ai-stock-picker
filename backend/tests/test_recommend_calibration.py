import unittest

import pytest

from app.routes import backtest
from app.services.recommend_calibration_service import (
    BASELINE_PROFILE,
    SCORING_PROFILES,
    calibrate_walk_forward,
    prepare_calibration_samples,
    score_strategy_components,
)


def _sample(day: int, code: str, momentum: float, trend: float, excess: float) -> dict:
    return {
        "date": f"2026-01-{day:02d}",
        "code": code,
        "strategy_scores": {
            "momentum": momentum,
            "trend": trend,
            "value": 4.2,
            "volume": 4.1,
        },
        "excess_return": excess,
    }


class RecommendCalibrationTests(unittest.TestCase):
    def test_preparation_excludes_unfilled_and_unscored_rows(self) -> None:
        rows = [
            {"rec_date": "2026-01-01", "code": "A", "strategy_scores": {"momentum": 6}, "excess_return": 1, "source": "rule", "execution_status": "filled"},
            {"rec_date": "2026-01-01", "code": "B", "strategy_scores": {"momentum": 6}, "excess_return": 2, "source": "watch", "execution_status": "not_triggered"},
            {"rec_date": "2026-01-01", "code": "C", "strategy_scores": {}, "excess_return": 3, "source": "rule", "execution_status": "filled"},
            {"rec_date": "2026-01-01", "code": "D", "strategy_scores": {"momentum": 6}, "excess_return": 4, "source": "quad", "execution_status": "filled"},
            {"rec_date": "2026-01-01", "code": "E", "strategy_scores": {"momentum": 7}, "excess_return": 5, "source": "calibration", "execution_status": "filled"},
        ]

        samples = prepare_calibration_samples(rows)

        self.assertEqual([sample["code"] for sample in samples], ["A", "E"])

    def test_baseline_score_matches_production_formula(self) -> None:
        score = score_strategy_components(
            {"momentum": 6, "trend": 5, "value": 4, "volume": 4},
            BASELINE_PROFILE,
        )

        self.assertEqual(score, 6 * 0.7 + 5 * 0.3 + 0.5)

    def test_walk_forward_never_trains_on_validation_or_future_dates(self) -> None:
        samples = []
        for day in range(1, 13):
            samples.extend(
                [
                    _sample(day, "M", 8, 4, 2 if day <= 8 else -2),
                    _sample(day, "T", 4, 8, -1 if day <= 8 else 3),
                ]
            )

        result = calibrate_walk_forward(
            samples,
            profiles=SCORING_PROFILES,
            min_train_days=4,
            validation_days=2,
            top_n=1,
            min_oos_selections=99,
            min_train_selections=4,
        )

        self.assertGreaterEqual(len(result["folds"]), 4)
        for fold in result["folds"]:
            self.assertLess(fold["train_end"], fold["validation_start"])
        # 最后阶段市场风格反转也不能回头改变第一折当时的选择。
        self.assertEqual(result["folds"][0]["selected_profile"], "baseline")
        self.assertIn(result["recommended_profile"], {profile.key for profile in SCORING_PROFILES})

    def test_small_sample_never_becomes_deployable(self) -> None:
        samples = [
            row
            for day in range(1, 9)
            for row in (
                _sample(day, "A", 8, 5, 1),
                _sample(day, "B", 5, 8, -1),
            )
        ]

        result = calibrate_walk_forward(
            samples,
            min_train_days=4,
            validation_days=2,
            top_n=1,
            min_oos_selections=30,
            min_train_selections=4,
        )

        self.assertEqual(result["status"], "insufficient_oos_sample")
        self.assertFalse(result["deployment_eligible"])
        self.assertIn("样本", result["deployment_reason"])

    def test_sparse_training_windows_do_not_produce_false_validation(self) -> None:
        samples = [_sample(1, "A", 8, 5, 1), _sample(6, "B", 5, 8, -1)]

        result = calibrate_walk_forward(
            samples,
            min_train_days=1,
            validation_days=1,
            min_train_selections=5,
        )

        self.assertEqual(result["folds"], [])
        self.assertEqual(result["status"], "insufficient_training_sample")

class TestRecommendCalibrationEndpoint:
    @pytest.mark.asyncio
    async def test_unconfigured_storage_returns_non_deployable_status(self, monkeypatch) -> None:
        monkeypatch.setattr(backtest.supabase_store, "is_configured", lambda: False)

        result = await backtest.recommend_calibration_endpoint(backtest.RecommendCalibrationRequest())

        assert result["status"] == "storage_not_configured"
        assert result["deployment_eligible"] is False

    @pytest.mark.asyncio
    async def test_missing_feature_migration_is_reported_without_500(self, monkeypatch) -> None:
        class _Query:
            def select(self, *_args):
                return self

            @property
            def not_(self):
                return self

            def is_(self, *_args):
                return self

            async def execute(self):
                raise RuntimeError("column daily_recommendations.strategy_scores does not exist")

        class _Client:
            def table(self, _name):
                return _Query()

        async def _client():
            return _Client()

        monkeypatch.setattr(backtest.supabase_store, "is_configured", lambda: True)
        monkeypatch.setattr(backtest.supabase_store, "get_service_client", _client)

        result = await backtest.recommend_calibration_endpoint(backtest.RecommendCalibrationRequest())

        assert result["status"] == "migration_required"
        assert "v17" in result["deployment_reason"]


if __name__ == "__main__":
    unittest.main()
