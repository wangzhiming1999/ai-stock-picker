import pandas as pd
import pytest

from app.routes import backtest
from app.services.recommend_history_replay_service import (
    build_historical_samples,
    classify_market_regime,
    compute_point_in_time_features,
    compute_technical_strategy_scores,
    evaluate_candidate_gate_profiles,
    resolve_historical_execution,
    select_execution_profile,
    evaluate_market_regime_filter,
    evaluate_holding_periods,
    evaluate_board_budgets,
    evaluate_rolling_stability,
    evaluate_transaction_cost_sensitivity,
    evaluate_return_distribution,
    evaluate_loss_rejection_profiles,
    simulate_capacity_constrained,
    select_risk_budget,
    volatility_weight_multiplier,
    market_board,
    run_historical_calibration,
)


def _history(closes: list[float], start: str = "2025-01-01") -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame(
        {
            "date": dates,
            "open": closes,
            "high": [value * 1.01 for value in closes],
            "low": [value * 0.99 for value in closes],
            "close": closes,
            "amount": [100_000.0] * len(closes),
        }
    )


def test_technical_scores_need_61_past_bars() -> None:
    assert compute_technical_strategy_scores([100.0] * 60) is None
    assert compute_technical_strategy_scores([100.0] * 61) is not None


def test_technical_scores_reproduce_live_volume_factor_from_historical_turnover() -> None:
    closes = [100.0] * 60 + [104.0]
    turnovers = [1.0] * 60 + [3.0]

    scores = compute_technical_strategy_scores(closes, turnovers)

    # 3 points for 2%-12% turnover, 2 for a 0%-8% rise, and 2 for positive MACD.
    assert scores is not None
    assert scores["volume"] == 7.0


def test_point_in_time_features_use_signal_day_price_and_turnover_only() -> None:
    closes = [100.0] * 55 + [101.0, 102.0, 103.0, 104.0, 105.0]
    opens = [100.0] * 59 + [103.0]
    turnovers = [10.0] * 55 + [10.0, 10.0, 10.0, 10.0, 5.0]

    features = compute_point_in_time_features(closes, opens, turnovers)

    assert features["ma20_distance_pct"] == pytest.approx(4.2184, abs=0.0001)
    assert features["gap_pct"] == pytest.approx(-0.9615, abs=0.0001)
    assert features["consecutive_up_days"] == 5
    assert features["turnover_ratio_5"] == pytest.approx(0.5)
    assert features["bearish_volume_divergence"] is True


def test_progressive_trend_score_preserves_partial_confirmation() -> None:
    closes = [100.0] * 41 + [120.0 - index for index in range(20)]

    scores = compute_technical_strategy_scores(closes)

    assert scores is not None
    assert scores["trend"] == 0.0
    assert 0.0 < scores["trend_progressive"] < 10.0


def test_historical_samples_use_next_trading_day_outcome_without_future_leakage() -> None:
    base = [100 + index * 0.4 for index in range(70)]
    histories = {"A": _history(base), "B": _history([value * 1.01 for value in base])}
    benchmark = _history([100 + index * 0.1 for index in range(70)])

    before = build_historical_samples(histories, benchmark, eval_days=8)
    mutated = {**histories, "A": histories["A"].copy()}
    mutated["A"].loc[mutated["A"].index[-1], "close"] = 9999
    after = build_historical_samples(mutated, benchmark, eval_days=8)

    first_before = next(row for row in before if row["code"] == "A")
    first_after = next(row for row in after if row["code"] == "A")
    assert first_before["strategy_scores"] == first_after["strategy_scores"]
    assert first_before["point_in_time_features"] == first_after["point_in_time_features"]
    assert first_before["excess_return"] == first_after["excess_return"]
    assert first_before["excess_return"] == first_before["holding_excess_returns"]["1"]
    assert first_before["outcome_date"] > first_before["date"]


def test_historical_samples_only_use_dates_shared_with_benchmark() -> None:
    stock = _history([100 + index for index in range(65)])
    benchmark = _history([100 + index * 0.1 for index in range(65)]).drop(index=63)

    samples = build_historical_samples({"A": stock}, benchmark, eval_days=5)

    assert all(row["date"] != stock.iloc[63]["date"].date().isoformat() for row in samples)


def test_historical_samples_carry_point_in_time_turnover_into_volume_score() -> None:
    stock = _history([100.0] * 60 + [104.0, 105.0])
    stock["turnover"] = [1.0] * 60 + [3.0, 3.0]
    benchmark = _history([100.0] * 62)

    samples = build_historical_samples({"A": stock}, benchmark, eval_days=2)

    assert samples[0]["strategy_scores"]["volume"] == 7.0


def test_historical_result_only_reports_the_still_missing_value_snapshot(monkeypatch) -> None:
    stock = _history([100 + index * 0.2 for index in range(100)])
    stock["turnover"] = [3.0] * 100
    benchmark = _history([100 + index * 0.1 for index in range(100)])
    monkeypatch.setattr(
        "app.services.recommend_history_replay_service._fetch_stock_history",
        lambda _code, _days: stock,
    )
    monkeypatch.setattr(
        "app.services.recommend_history_replay_service._fetch_benchmark",
        lambda _start, _end: benchmark,
    )

    result = run_historical_calibration(codes=["A"], eval_days=40)

    assert "PE/PB" in result["deployment_reason"]
    assert "换手率" not in result["deployment_reason"]
    assert result["feature_coverage"]["volume"].startswith("production_equivalent")


def test_gate_profile_evaluation_keeps_holdout_dates_out_of_selection() -> None:
    samples = []
    for day in range(1, 11):
        samples.extend(
            [
                {
                    "date": f"2026-01-{day:02d}",
                    "code": "A",
                    "strategy_scores": {"momentum": 6, "trend": 4, "trend_progressive": 8},
                    "excess_return": 1 if day <= 6 else -2,
                },
                {
                    "date": f"2026-01-{day:02d}",
                    "code": "B",
                    "strategy_scores": {"momentum": 5, "trend": 0, "trend_progressive": 6},
                    "excess_return": -1 if day <= 6 else 3,
                },
            ]
        )

    result = evaluate_candidate_gate_profiles(samples, train_days=6, top_n=1)

    assert result["train_end"] == "2026-01-06"
    assert result["validation_start"] == "2026-01-07"
    assert result["selected_profile"] == "baseline"
    assert result["deployment_eligible"] is False


def test_pullback_execution_uses_better_open_on_gap_down() -> None:
    sample = {
        "recommend_close": 100.0,
        "next_open": 94.0,
        "next_high": 101.0,
        "next_low": 93.0,
        "next_close": 99.0,
        "benchmark_return": 0.0,
        "signal": {"buy_point": 95.0, "resistance": 105.0, "level_valid": True},
    }

    result = resolve_historical_execution(sample, "pullback")

    assert result["execution_status"] == "filled"
    assert result["entry_price"] == 94.0
    assert result["net_excess_return"] > 5


def test_breakout_execution_does_not_count_an_untriggered_plan_as_a_loss() -> None:
    sample = {
        "recommend_close": 100.0,
        "next_open": 100.0,
        "next_high": 104.0,
        "next_low": 98.0,
        "next_close": 99.0,
        "benchmark_return": 0.0,
        "signal": {"buy_point": 95.0, "resistance": 105.0, "level_valid": True},
    }

    result = resolve_historical_execution(sample, "breakout")

    assert result["execution_status"] == "not_triggered"
    assert result["net_excess_return"] is None


def test_execution_profile_selection_rejects_sparse_high_win_rate() -> None:
    training = {
        "close": {"filled": 100, "hit_rate": 52.0, "avg_excess_return": 0.4},
        "pullback": {"filled": 12, "hit_rate": 75.0, "avg_excess_return": 1.0},
        "auto": {"filled": 50, "hit_rate": 55.0, "avg_excess_return": 0.3},
    }

    assert select_execution_profile(training, min_train_fills=30) == "auto"


def test_market_regime_uses_only_confirmed_moving_average_structure() -> None:
    assert classify_market_regime([100 + index for index in range(60)]) == "bull"
    assert classify_market_regime([160 - index for index in range(60)]) == "bear"
    assert classify_market_regime([100.0] * 60) == "sideways"


def test_regime_filter_is_selected_on_training_dates_only() -> None:
    samples = []
    for day in range(1, 11):
        for regime, excess in (("bull", 1.0), ("bear", -1.0)):
            samples.append({
                "date": f"2026-01-{day:02d}", "code": regime,
                "market_regime": regime,
                "strategy_scores": {"momentum": 6, "trend": 5},
                "excess_return": excess if day <= 6 else -excess,
            })

    result = evaluate_market_regime_filter(samples, train_days=6, top_n=10, min_train_selections=2)

    assert result["selected_regimes"] == ["bull"]
    assert result["train_end"] == "2026-01-06"
    assert result["validation_start"] == "2026-01-07"
    assert result["deployment_eligible"] is False


def test_holding_period_selection_uses_training_dates_only() -> None:
    samples = []
    for day in range(1, 11):
        samples.append({
            "date": f"2026-01-{day:02d}", "code": "A",
            "strategy_scores": {"momentum": 6, "trend": 5},
            "holding_excess_returns": {"1": 1.0, "3": 2.0 if day <= 6 else -2.0, "5": 0.5},
        })
    result = evaluate_holding_periods(samples, train_days=6, top_n=10, min_train_selections=2)
    assert result["selected_horizon"] == 3
    assert result["validation_start"] == "2026-01-07"
    assert result["deployment_eligible"] is False


def test_capacity_constraint_blocks_new_positions_until_slot_is_released() -> None:
    samples = [
        {"date": "2026-01-01", "code": "A", "strategy_scores": {"momentum": 7, "trend": 5}, "holding_excess_returns": {"3": 3.0}, "holding_outcome_dates": {"3": "2026-01-03"}},
        {"date": "2026-01-02", "code": "B", "strategy_scores": {"momentum": 8, "trend": 5}, "holding_excess_returns": {"3": 9.0}, "holding_outcome_dates": {"3": "2026-01-04"}},
        {"date": "2026-01-03", "code": "C", "strategy_scores": {"momentum": 6, "trend": 5}, "holding_excess_returns": {"3": 1.0}, "holding_outcome_dates": {"3": "2026-01-06"}},
    ]
    result = simulate_capacity_constrained(samples, horizon=3, max_positions=1, top_n=10)
    assert result["trades"] == 2
    assert result["skipped_for_capacity"] == 1
    assert result["total_excess_return"] == 4.0


def test_risk_budget_selection_prefers_return_per_drawdown() -> None:
    training = {
        5: {"trades": 100, "total_excess_return": 20.0, "max_realized_drawdown_pct": -10.0},
        10: {"trades": 100, "total_excess_return": 18.0, "max_realized_drawdown_pct": -6.0},
    }
    assert select_risk_budget(training, min_trades=30) == 10


def test_volatility_weight_only_scales_down_high_risk_positions() -> None:
    assert volatility_weight_multiplier(40.0, 20.0) == 0.5
    assert volatility_weight_multiplier(10.0, 20.0) == 1.0


def test_market_board_is_stable_from_stock_code() -> None:
    assert market_board("300750") == "chinext"
    assert market_board("688981") == "star"
    assert market_board("600519") == "main"


def test_board_budget_selection_is_fit_on_training_period_only() -> None:
    samples = []
    for day in range(1, 13):
        for code in ("300001", "300002", "600001"):
            samples.append({
                "date": f"2026-01-{day:02d}",
                "code": code,
                "strategy_scores": {"momentum": 7, "trend": 5},
                "holding_excess_returns": {"1": 0.2, "3": 1.0},
                "holding_outcome_dates": {"1": f"2026-01-{day + 1:02d}", "3": f"2026-01-{day + 3:02d}"},
            })
    result = evaluate_board_budgets(samples, train_days=6, top_n=10, max_positions=3)
    assert result["selected_max_per_board"] in (1, 2, 3)
    assert result["validation_metrics"]["max_per_board"] == result["selected_max_per_board"]
    assert result["unconstrained_validation_metrics"]["max_per_board"] is None


def test_rolling_stability_reports_each_unseen_time_window() -> None:
    samples = []
    dates = pd.bdate_range("2026-01-01", periods=18)
    for index, date in enumerate(dates):
        samples.append({
            "date": date.strftime("%Y-%m-%d"),
            "code": "600001",
            "strategy_scores": {"momentum": 7, "trend": 5},
            "holding_excess_returns": {"1": 0.1, "3": 0.5},
            "holding_outcome_dates": {
                "1": (date + pd.offsets.BDay(1)).strftime("%Y-%m-%d"),
                "3": (date + pd.offsets.BDay(3)).strftime("%Y-%m-%d"),
            },
        })
    result = evaluate_rolling_stability(samples, train_days=6, window_days=4, max_positions=3)
    assert result["window_count"] == 3
    assert [window["start"] for window in result["windows"]] == [
        dates[6].strftime("%Y-%m-%d"), dates[10].strftime("%Y-%m-%d"), dates[14].strftime("%Y-%m-%d")
    ]
    assert result["return_win_windows"] == 3


def test_transaction_cost_sensitivity_reprices_from_base_cost() -> None:
    samples = [
        {"date": "2026-01-01", "code": "600001", "strategy_scores": {"momentum": 7, "trend": 5}, "holding_excess_returns": {"1": 0.2}},
        {"date": "2026-01-02", "code": "600002", "strategy_scores": {"momentum": 7, "trend": 5}, "holding_excess_returns": {"1": 0.1}},
    ]

    result = evaluate_transaction_cost_sensitivity(samples, horizon=1, costs=(0.15, 0.30, 0.50))

    assert result["cost_scenarios"]["0.15"]["hit_rate"] == 100.0
    assert result["cost_scenarios"]["0.30"]["hit_rate"] == 50.0
    assert result["cost_scenarios"]["0.50"]["hit_rate"] == 0.0


def test_return_distribution_exposes_tail_profit_concentration() -> None:
    samples = [
        {"date": f"2026-01-{index:02d}", "code": f"60000{index}", "strategy_scores": {"momentum": 7, "trend": 5}, "holding_excess_returns": {"1": value}}
        for index, value in enumerate((-1.0, -1.0, -1.0, 1.0, 8.0), 1)
    ]

    result = evaluate_return_distribution(samples, horizon=1)

    assert result["hit_rate"] == 40.0
    assert result["median_excess_return"] == -1.0
    assert result["top_decile_profit_share_pct"] == 88.89


def test_loss_rejection_profile_must_improve_hit_rate_and_return_out_of_sample() -> None:
    samples = []
    for day in range(1, 9):
        is_validation = day > 4
        for code, volatility, strength, result in (
            ("600001", 16.0, 8.5, 1.0),
            ("600002", 45.0, 7.0, -1.0),
        ):
            samples.append(
                {
                    "date": f"2026-01-{day:02d}",
                    "code": code,
                    "strategy_scores": {"momentum": 7, "trend": 5},
                    "historical_volatility": volatility,
                    "signal": {"strength": strength},
                    "excess_return": result if not is_validation else result * 1.2,
                }
            )

    result = evaluate_loss_rejection_profiles(
        samples, train_days=4, top_n=10, min_train_selections=4, min_validation_selections=4
    )

    assert result["selected_profile"] == "volatility_22"
    assert result["validation_metrics"]["hit_rate"] == 100.0
    assert result["baseline_validation_metrics"]["hit_rate"] == 50.0
    assert result["deployment_eligible"] is True


def test_loss_rejection_profile_rejects_training_only_improvement() -> None:
    samples = []
    for day in range(1, 9):
        for code, volatility, train_result, validation_result in (
            ("600001", 16.0, 1.0, -1.0),
            ("600002", 45.0, -1.0, 1.0),
        ):
            samples.append(
                {
                    "date": f"2026-01-{day:02d}",
                    "code": code,
                    "strategy_scores": {"momentum": 7, "trend": 5},
                    "historical_volatility": volatility,
                    "signal": {"strength": 8.0},
                    "excess_return": train_result if day <= 4 else validation_result,
                }
            )

    result = evaluate_loss_rejection_profiles(
        samples, train_days=4, top_n=10, min_train_selections=4, min_validation_selections=4
    )

    assert result["selected_profile"] == "volatility_22"
    assert result["hit_rate_lift"] == -50.0
    assert result["deployment_eligible"] is False


def test_loss_rejection_profiles_can_reject_overextended_price_action() -> None:
    samples = []
    for day in range(1, 9):
        for code, distance, result in (
            ("600001", 3.0, 1.0),
            ("600002", 12.0, -1.0),
        ):
            samples.append(
                {
                    "date": f"2026-01-{day:02d}",
                    "code": code,
                    "strategy_scores": {"momentum": 7, "trend": 5},
                    "historical_volatility": 25.0,
                    "signal": {"strength": 7.0},
                    "point_in_time_features": {
                        "ma20_distance_pct": distance,
                        "gap_pct": 0.5,
                        "consecutive_up_days": 2,
                        "bearish_volume_divergence": False,
                    },
                    "excess_return": result,
                }
            )

    result = evaluate_loss_rejection_profiles(
        samples, train_days=4, top_n=10, min_train_selections=4, min_validation_selections=4
    )

    assert result["selected_profile"] == "ma20_extension_5"
    assert result["validation_metrics"]["hit_rate"] == 100.0
    assert next(
        profile for profile in result["validation_profiles"] if profile["profile"] == "ma20_extension_5"
    )["hit_rate_lift"] == 50.0
    assert result["deployment_eligible"] is True


def test_loss_rejection_profiles_ignore_tiny_training_slices() -> None:
    samples = []
    for day in range(1, 9):
        for code_index in range(2):
            is_only_extended_survivor = day == 1 and code_index == 0
            samples.append(
                {
                    "date": f"2026-01-{day:02d}",
                    "code": f"60000{code_index}",
                    "strategy_scores": {"momentum": 7, "trend": 5},
                    "historical_volatility": 45.0,
                    "signal": {"strength": 7.0},
                    "point_in_time_features": {
                        "ma20_distance_pct": 3.0 if is_only_extended_survivor else 12.0,
                    },
                    "excess_return": 1.0 if code_index == 0 else -1.0,
                }
            )

    result = evaluate_loss_rejection_profiles(
        samples, train_days=4, top_n=10, min_train_selections=4, min_validation_selections=4
    )

    assert result["selected_profile"] == "baseline"


@pytest.mark.asyncio
async def test_history_endpoint_is_always_research_only(monkeypatch) -> None:
    monkeypatch.setattr(
        backtest.recommend_history_replay_service,
        "run_historical_calibration",
        lambda **_kwargs: {
            "status": "eligible_for_review",
            "deployment_eligible": True,
            "usable_samples": 120,
        },
    )

    result = await backtest.recommend_history_calibration_endpoint(
        backtest.RecommendHistoryCalibrationRequest(eval_days=80)
    )

    assert result["deployment_eligible"] is False
    assert result["validation_scope"] == "research_only_technical_factors"
