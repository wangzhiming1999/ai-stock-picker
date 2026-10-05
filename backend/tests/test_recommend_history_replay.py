import pandas as pd
import pytest

from app.routes import backtest
from app.services.recommend_history_replay_service import (
    assess_backtest_caliber,
    build_historical_samples,
    classify_market_regime,
    compute_point_in_time_features,
    compute_relative_strength_features,
    compute_technical_strategy_scores,
    evaluate_candidate_gate_profiles,
    evaluate_board_specific_profiles,
    assess_board_profile_consensus,
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
    run_etf_historical_calibration,
    historical_window_days,
    evaluate_execution_cost_stress,
    evaluate_rolling_segment_profiles,
    evaluate_regime_switching_profiles,
    evaluate_rolling_regime_switching,
    compute_execution_quality_features,
    evaluate_liquidity_profiles,
    evaluate_rolling_liquidity_profiles,
    resolve_historical_execution_window,
    evaluate_order_validity_profiles,
    evaluate_rolling_order_validity,
    etf_price_limit_pct,
    etf_fee_assumptions,
    evaluate_high_win_rate_profiles,
    evaluate_rolling_high_win_rate_profiles,
    build_category_relative_benchmarks,
    _fetch_etf_history,
    evaluate_cross_sectional_factor,
    evaluate_rolling_cross_sectional_factors,
)


def test_backtest_caliber_blocks_deployment_when_execution_rules_are_missing() -> None:
    result = assess_backtest_caliber(
        instrument_type="etf",
        capabilities={
            "settlement_rule": "t_plus_1",
            "price_limit_handling": False,
            "tick_size_rounding": False,
            "fee_model_verified": False,
            "historical_tradability": False,
            "point_in_time_features": True,
            "benchmark_alignment": True,
        },
    )

    assert result["passed"] is False
    assert result["deployment_eligible"] is False
    assert result["claim_scope"] == "research_diagnostic_only"
    assert result["checks"]["settlement_rule"]["passed"] is True
    assert result["blockers"] == [
        "price_limit_handling_missing",
        "tick_size_rounding_missing",
        "fee_model_not_verified",
        "historical_tradability_missing",
    ]


def test_backtest_caliber_allows_candidate_claims_only_with_complete_coverage() -> None:
    result = assess_backtest_caliber(
        instrument_type="etf",
        capabilities={
            "settlement_rule": "t_plus_1",
            "price_limit_handling": True,
            "tick_size_rounding": True,
            "fee_model_verified": True,
            "historical_tradability": True,
            "point_in_time_features": True,
            "benchmark_alignment": True,
        },
    )

    assert result["passed"] is True
    assert result["deployment_eligible"] is True
    assert result["claim_scope"] == "candidate_win_rate"
    assert result["blockers"] == []


def _board_profile_sample(day: int, code: str, board: str, *, progressive: float, excess: float) -> dict:
    return {
        "date": f"2026-01-{day:02d}",
        "code": code,
        "market_board": board,
        "strategy_scores": {"momentum": 7, "trend": 4, "trend_progressive": progressive},
        "excess_return": excess,
        "recommend_close": 100.0,
        "next_open": 100.0,
        "next_high": 106.0,
        "next_low": 94.0,
        "next_close": 100.0 * (1 + (excess + 0.15) / 100),
        "benchmark_return": 0.0,
        "signal": {"buy_point": 95.0, "resistance": 105.0, "level_valid": True},
    }


def test_execution_quality_features_use_current_and_prior_bars_only() -> None:
    result = compute_execution_quality_features(
        highs=[101.0] * 20 + [102.0],
        lows=[99.0] * 20 + [98.0],
        closes=[100.0] * 21,
        amounts=[1000.0] * 20 + [2000.0],
    )

    assert result["amount_ratio_20"] == pytest.approx(2.0)
    assert result["amplitude_pct"] == pytest.approx(4.0)


def test_relative_strength_features_use_signal_day_and_prior_closes_only() -> None:
    result = compute_relative_strength_features(
        closes=[float(value) for value in range(100, 161)],
        benchmark_closes=[100.0] * 61,
    )

    assert result["relative_strength_20d_pct"] == pytest.approx((160 / 140 - 1) * 100)
    assert result["trend_alignment_5_20_60"] is True


def test_category_relative_benchmark_is_leave_one_out_and_segment_scoped() -> None:
    dates = pd.date_range("2026-01-01", periods=65, freq="D")

    def history(closes: list[float]) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "date": dates,
                "open": closes,
                "high": closes,
                "low": closes,
                "close": closes,
            }
        )

    histories = {
        "broad_a": history([100.0 + day * 4 for day in range(65)]),
        "broad_b": history([100.0 + day for day in range(65)]),
        "industry_a": history([100.0 - day for day in range(65)]),
    }
    segments = {
        "broad_a": "broad",
        "broad_b": "broad",
        "industry_a": "industry",
    }

    benchmarks = build_category_relative_benchmarks(histories, segments)

    assert set(benchmarks) == {"broad_a", "broad_b"}
    assert benchmarks["broad_a"]["close"].tolist() == pytest.approx(
        histories["broad_b"]["close"].tolist()
    )
    assert benchmarks["broad_b"]["close"].tolist() == pytest.approx(
        histories["broad_a"]["close"].tolist()
    )


def test_etf_history_retries_transient_provider_failure(monkeypatch) -> None:
    attempts = 0
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=3, freq="D"),
            "open": [1.0, 1.1, 1.2],
            "high": [1.1, 1.2, 1.3],
            "low": [0.9, 1.0, 1.1],
            "close": [1.0, 1.1, 1.2],
            "amount": [100.0, 110.0, 120.0],
        }
    )

    def flaky_call(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise TimeoutError("temporary provider timeout")
        return frame

    monkeypatch.setattr(
        "app.services.recommend_history_replay_service.akshare_guard.call",
        flaky_call,
    )

    result = _fetch_etf_history("510300", 3)

    assert attempts == 3
    assert result["close"].tolist() == [1.0, 1.1, 1.2]


def test_cross_sectional_factor_reports_rank_ic_and_monotonic_quantiles() -> None:
    samples = []
    for day in range(1, 7):
        for rank in range(5):
            samples.append(
                {
                    "date": f"2026-01-{day:02d}",
                    "code": f"etf-{rank}",
                    "market_board": "broad",
                    "point_in_time_features": {
                        "relative_strength_20d_pct": float(rank),
                    },
                    "holding_excess_returns": {
                        "1": float(rank - 2),
                        "3": float((rank - 2) * 2),
                        "5": float((rank - 2) * 3),
                    },
                }
            )

    result = evaluate_cross_sectional_factor(
        samples,
        segment="broad",
        factor_key="relative_strength_20d_pct",
        factor_source="point_in_time_features",
        quantile_count=3,
    )

    assert result["date_count"] == 6
    assert result["observation_count"] == 30
    assert result["horizons"]["1"]["mean_rank_ic"] == pytest.approx(1.0)
    assert result["horizons"]["1"]["high_minus_low"] > 0
    assert result["horizons"]["1"]["quantile_returns"]["1"] < result["horizons"]["1"]["quantile_returns"]["3"]
    assert result["horizons"]["1"]["monotonic"] is True


def test_cross_sectional_factor_uses_observed_extreme_quantiles_for_two_assets() -> None:
    samples = []
    for day in range(1, 5):
        for code, factor, excess in (("low", 1.0, -1.0), ("high", 2.0, 1.0)):
            samples.append(
                {
                    "date": f"2026-01-{day:02d}",
                    "code": code,
                    "market_board": "broad",
                    "point_in_time_features": {"relative_strength_20d_pct": factor},
                    "holding_excess_returns": {"1": excess},
                }
            )

    result = evaluate_cross_sectional_factor(
        samples,
        segment="broad",
        factor_key="relative_strength_20d_pct",
        quantile_count=3,
        horizons=(1,),
    )

    assert result["horizons"]["1"]["quantile_returns"] == {"1": -1.0, "2": 1.0}
    assert result["horizons"]["1"]["high_minus_low"] == 2.0
    assert result["horizons"]["1"]["monotonic"] is True


def test_cross_sectional_factor_assigns_quantiles_from_full_reference_universe() -> None:
    reference_samples = []
    evaluation_samples = []
    for day in range(1, 5):
        for rank in range(5):
            row = {
                "date": f"2026-01-{day:02d}",
                "code": f"etf-{rank}",
                "market_board": "broad",
                "point_in_time_features": {
                    "relative_strength_20d_pct": float(rank),
                },
                "holding_excess_returns": {"1": float(rank)},
            }
            reference_samples.append(row)
            if rank < 2:
                evaluation_samples.append(row)

    result = evaluate_cross_sectional_factor(
        evaluation_samples,
        rank_reference_samples=reference_samples,
        segment="broad",
        factor_key="relative_strength_20d_pct",
        horizons=(1,),
        quantile_count=3,
    )

    assert result["observation_count"] == 8
    assert result["rank_reference_observation_count"] == 20
    assert result["horizons"]["1"]["quantile_returns"] == {"1": 0.5}
    assert result["horizons"]["1"]["high_minus_low"] is None


def test_rolling_cross_sectional_factor_selects_on_training_only() -> None:
    samples = []
    for day in range(1, 19):
        for rank in range(5):
            samples.append(
                {
                    "date": f"2026-01-{day:02d}",
                    "code": f"etf-{rank}",
                    "market_board": "broad",
                    "point_in_time_features": {
                        "relative_strength_20d_pct": float(rank),
                        "amplitude_pct": float((rank + day) % 5),
                    },
                    "holding_excess_returns": {
                        "1": float(rank - 2),
                        "3": float((rank - 2) * 2),
                        "5": float((rank - 2) * 3),
                    },
                }
            )

    result = evaluate_rolling_cross_sectional_factors(
        samples,
        segment="broad",
        factor_specs=(
            ("relative_strength_20d_pct", "point_in_time_features"),
            ("amplitude_pct", "point_in_time_features"),
        ),
        train_days=6,
        validation_days=4,
        min_train_observations=20,
        min_validation_observations=10,
        quantile_count=3,
    )

    assert result["window_count"] == 3
    assert result["consensus_factor"] == "relative_strength_20d_pct"
    assert result["consensus_direction"] == "higher"
    assert result["matching_windows"] == 3
    assert result["matching_factor_direction_windows"] == 3
    assert result["passed_windows"] == 3
    assert result["eligible_for_review"] is True
    assert result["deployment_eligible"] is False
    assert all(window["train_end"] < window["validation_start"] for window in result["windows"])


def test_rolling_cross_sectional_factor_rejects_weak_training_ic() -> None:
    samples = []
    for day in range(1, 13):
        for rank, excess in ((0, -1.0), (1, 1.0), (2, 0.0)):
            samples.append(
                {
                    "date": f"2026-01-{day:02d}",
                    "code": f"etf-{rank}",
                    "market_board": "broad",
                    "point_in_time_features": {"relative_strength_20d_pct": float(rank)},
                    "holding_excess_returns": {"1": excess},
                }
            )

    result = evaluate_rolling_cross_sectional_factors(
        samples,
        segment="broad",
        factor_specs=(("relative_strength_20d_pct", "point_in_time_features"),),
        train_days=6,
        validation_days=3,
        min_train_observations=12,
        min_validation_observations=6,
        min_abs_train_rank_ic=0.6,
    )

    assert result["window_count"] == 2
    assert result["passed_windows"] == 0
    assert result["eligible_for_review"] is False
    assert all(window["reason"] == "no_stable_training_factor" for window in result["windows"])




def test_liquidity_profiles_are_selected_on_training_dates_only() -> None:
    samples = []
    for day in range(1, 13):
        for code, amount_ratio, training_excess, validation_excess in (
            ("liquid", 1.2, 1.0, -1.0),
            ("thin", 0.5, -1.0, 2.0),
        ):
            row = _board_profile_sample(
                day,
                code,
                "broad",
                progressive=8.0,
                excess=training_excess if day <= 6 else validation_excess,
            )
            row["point_in_time_features"] = {
                "amount_ratio_20": amount_ratio,
                "amplitude_pct": 1.0,
            }
            samples.append(row)

    result = evaluate_liquidity_profiles(
        samples,
        segment="broad",
        train_days=6,
        top_n=20,
        min_train_fills=4,
        min_validation_fills=4,
        setups=("close",),
    )

    assert result["selected_liquidity_profile"] == "amount_ratio_1_0"
    assert result["train_end"] == "2026-01-06"
    assert result["validation_start"] == "2026-01-07"
    assert result["validation_metrics"]["filled"] == 6
    assert result["baseline_validation_metrics"]["filled"] == 12
    assert result["deployment_eligible"] is False


def test_rolling_liquidity_profiles_retrain_before_forward_windows() -> None:
    samples = []
    for day in range(1, 19):
        for code, amount_ratio, excess in (
            ("liquid", 1.2, 1.0),
            ("thin", 0.5, -1.0),
        ):
            row = _board_profile_sample(day, code, "broad", progressive=8.0, excess=excess)
            row["point_in_time_features"] = {
                "amount_ratio_20": amount_ratio,
                "amplitude_pct": 1.0,
            }
            samples.append(row)

    result = evaluate_rolling_liquidity_profiles(
        samples,
        segment="broad",
        train_days=6,
        validation_days=4,
        top_n=20,
        min_train_fills=4,
        min_validation_fills=4,
        setups=("close",),
    )

    assert result["window_count"] == 3
    assert result["consensus_liquidity_profile"] == "amount_ratio_1_0"
    assert all(window["train_end"] < window["validation_start"] for window in result["windows"])
    assert result["deployment_eligible"] is False


def test_high_win_rate_profile_selects_relative_strength_trend_on_training_only() -> None:
    samples = []
    for day in range(1, 13):
        for code, relative_strength, aligned, excess in (
            ("strong", 3.0, True, 1.0),
            ("weak", -2.0, False, -1.0),
        ):
            row = _board_profile_sample(day, code, "broad", progressive=8.0, excess=excess)
            row["instrument_type"] = "etf"
            row["point_in_time_features"] = {
                "relative_strength_20d_pct": relative_strength,
                "trend_alignment_5_20_60": aligned,
            }
            row["future_bars"] = [
                {"date": f"2026-02-{day:02d}", "open": 96.0, "high": 97.0, "low": 94.0, "close": 96.0, "amount": 1000.0, "benchmark_return": 0.0},
                {"date": f"2026-03-{day:02d}", "open": 96.0, "high": 98.0, "low": 93.0, "close": 94.0 if excess < 0 else 98.0, "amount": 1000.0, "benchmark_return": 0.0},
                {"date": f"2026-04-{day:02d}", "open": 96.0, "high": 98.0, "low": 95.0, "close": 97.0, "amount": 1000.0, "benchmark_return": 0.0},
                {"date": f"2026-05-{day:02d}", "open": 97.0, "high": 99.0, "low": 96.0, "close": 98.0, "amount": 1000.0, "benchmark_return": 0.0},
            ]
            samples.append(row)

    result = evaluate_high_win_rate_profiles(
        samples,
        segment="broad",
        train_days=6,
        top_n=20,
        min_train_fills=4,
        min_validation_fills=4,
    )

    assert result["selected_high_win_profile"] == "relative_strength_2_trend"
    assert result["validation_metrics"]["hit_rate"] == 100.0
    assert result["baseline_validation_metrics"]["hit_rate"] == 50.0
    assert result["hit_rate_lift"] == 50.0


def test_rolling_high_win_rate_profiles_require_consensus_across_windows() -> None:
    samples = []
    for day in range(1, 19):
        for code, relative_strength, aligned, excess in (
            ("strong", 3.0, True, 1.0),
            ("weak", -2.0, False, -1.0),
        ):
            row = _board_profile_sample(day, code, "broad", progressive=8.0, excess=excess)
            row["instrument_type"] = "etf"
            row["point_in_time_features"] = {
                "relative_strength_20d_pct": relative_strength,
                "trend_alignment_5_20_60": aligned,
            }
            row["future_bars"] = [
                {"date": f"2026-02-{day:02d}", "open": 96.0, "high": 97.0, "low": 94.0, "close": 96.0, "amount": 1000.0, "benchmark_return": 0.0},
                {"date": f"2026-03-{day:02d}", "open": 96.0, "high": 98.0, "low": 95.0, "close": 98.0 if excess > 0 else 94.0, "amount": 1000.0, "benchmark_return": 0.0},
                {"date": f"2026-04-{day:02d}", "open": 97.0, "high": 99.0, "low": 96.0, "close": 98.0, "amount": 1000.0, "benchmark_return": 0.0},
                {"date": f"2026-05-{day:02d}", "open": 98.0, "high": 100.0, "low": 97.0, "close": 99.0, "amount": 1000.0, "benchmark_return": 0.0},
            ]
            samples.append(row)

    result = evaluate_rolling_high_win_rate_profiles(
        samples,
        segment="broad",
        train_days=6,
        validation_days=4,
        top_n=20,
        min_train_fills=4,
        min_validation_fills=4,
    )

    assert result["window_count"] == 3
    assert result["consensus_high_win_profile"] == "relative_strength_2_trend"
    assert result["matching_windows"] == 3
    assert all(window["train_end"] < window["validation_start"] for window in result["windows"])


def test_execution_window_uses_first_trigger_and_t1_exit_without_later_entry_price() -> None:
    sample = {
        "recommend_close": 100.0,
        "signal": {"buy_point": 95.0, "resistance": 105.0, "level_valid": True},
        "future_bars": [
            {"date": "2026-01-02", "open": 100.0, "high": 102.0, "low": 98.0, "close": 101.0, "benchmark_return": 0.5},
            {"date": "2026-01-03", "open": 96.0, "high": 100.0, "low": 94.0, "close": 99.0, "benchmark_return": 1.0},
            {"date": "2026-01-04", "open": 90.0, "high": 95.0, "low": 89.0, "close": 94.0, "benchmark_return": -1.0},
        ],
    }

    result = resolve_historical_execution_window(sample, "pullback", validity_days=3)

    assert result["execution_status"] == "filled"
    assert result["fill_day"] == 2
    assert result["entry_price"] == 95.0
    assert result["exit_price"] == 94.0
    assert result["net_excess_return"] == pytest.approx((94 / 95 - 1) * 100 - 0.15 - (-1.0))


def test_execution_window_cancels_an_unfilled_order_at_expiry() -> None:
    sample = {
        "recommend_close": 100.0,
        "signal": {"buy_point": 95.0, "resistance": 105.0, "level_valid": True},
        "future_bars": [
            {"date": "2026-01-02", "open": 100.0, "high": 102.0, "low": 98.0, "close": 101.0, "benchmark_return": 0.5},
            {"date": "2026-01-03", "open": 99.0, "high": 101.0, "low": 97.0, "close": 100.0, "benchmark_return": 0.4},
        ],
    }

    result = resolve_historical_execution_window(sample, "pullback", validity_days=2)

    assert result["execution_status"] == "expired"
    assert result["net_excess_return"] is None


def test_execution_window_rounds_etf_order_price_to_mill_tick() -> None:
    sample = {
        "recommend_close": 100.0,
        "instrument_type": "etf",
        "signal": {"buy_point": 95.0006, "resistance": 105.0, "level_valid": True},
        "future_bars": [
            {"date": "2026-01-02", "open": 96.0, "high": 97.0, "low": 95.0008, "close": 96.0, "amount": 1000.0, "benchmark_return": 0.0},
            {"date": "2026-01-03", "open": 96.0, "high": 98.0, "low": 95.0, "close": 97.0, "amount": 1000.0, "benchmark_return": 0.0},
        ],
    }

    result = resolve_historical_execution_window(sample, "pullback", validity_days=1)

    assert result["execution_status"] == "filled"
    assert result["entry_price"] == 95.001
    assert result["price_tick"] == 0.001


def test_execution_window_does_not_fill_on_zero_amount_bar() -> None:
    sample = {
        "recommend_close": 100.0,
        "instrument_type": "etf",
        "signal": {"buy_point": 95.0, "resistance": 105.0, "level_valid": True},
        "future_bars": [
            {"date": "2026-01-02", "open": 96.0, "high": 97.0, "low": 94.0, "close": 95.0, "amount": 0.0, "benchmark_return": 0.0},
            {"date": "2026-01-03", "open": 96.0, "high": 97.0, "low": 94.0, "close": 96.0, "amount": 1000.0, "benchmark_return": 0.0},
            {"date": "2026-01-04", "open": 96.0, "high": 98.0, "low": 95.0, "close": 97.0, "amount": 1000.0, "benchmark_return": 0.0},
        ],
    }

    result = resolve_historical_execution_window(sample, "pullback", validity_days=2)

    assert result["execution_status"] == "filled"
    assert result["fill_day"] == 2
    assert result["fill_date"] == "2026-01-03"


def test_execution_window_is_unverifiable_when_t1_exit_bar_has_zero_amount() -> None:
    sample = {
        "recommend_close": 100.0,
        "instrument_type": "etf",
        "signal": {"buy_point": 95.0, "resistance": 105.0, "level_valid": True},
        "future_bars": [
            {"date": "2026-01-02", "open": 96.0, "high": 97.0, "low": 94.0, "close": 95.0, "amount": 1000.0, "benchmark_return": 0.0},
            {"date": "2026-01-03", "open": 95.0, "high": 95.0, "low": 95.0, "close": 95.0, "amount": 0.0, "benchmark_return": 0.0},
        ],
    }

    result = resolve_historical_execution_window(sample, "pullback", validity_days=1)

    assert result["execution_status"] == "unverifiable"
    assert result["reason"] == "t1_exit_not_tradable"
    assert result["net_excess_return"] is None


def test_etf_price_limit_metadata_tracks_2020_08_24_rule_change() -> None:
    assert etf_price_limit_pct("159915", "2020-08-21") == 10.0
    assert etf_price_limit_pct("159915", "2020-08-24") == 20.0
    assert etf_price_limit_pct("159949", "2026-01-01") == 20.0
    assert etf_price_limit_pct("159967", "2026-01-01") == 20.0
    assert etf_price_limit_pct("588000", "2026-01-01") == 20.0
    assert etf_price_limit_pct("510300", "2026-01-01") == 10.0
    assert etf_price_limit_pct("unknown", "2026-01-01") is None


def test_etf_fee_assumptions_separate_verified_exchange_fees_from_broker_costs() -> None:
    result = etf_fee_assumptions()

    assert result["exchange_handling_fee_each_side_pct"] == 0.004
    assert result["stamp_tax_pct"] == 0.0
    assert result["broker_commission_verified"] is False
    assert result["backtest_total_cost_pct"] == 0.15


def test_breakout_cannot_fill_on_one_price_limit_up_bar() -> None:
    sample = {
        "code": "510300",
        "recommend_close": 1.0,
        "instrument_type": "etf",
        "signal": {"buy_point": 0.95, "resistance": 1.1, "level_valid": True},
        "future_bars": [
            {"date": "2026-01-02", "previous_close": 1.0, "open": 1.1, "high": 1.1, "low": 1.1, "close": 1.1, "amount": 1000.0, "benchmark_return": 0.0},
            {"date": "2026-01-03", "previous_close": 1.1, "open": 1.1, "high": 1.12, "low": 1.08, "close": 1.11, "amount": 1000.0, "benchmark_return": 0.0},
        ],
    }

    result = resolve_historical_execution_window(sample, "breakout", validity_days=1)

    assert result["execution_status"] == "expired"
    assert result["reason"] == "one_price_limit_up"


def test_t1_exit_is_unverifiable_on_one_price_limit_down_bar() -> None:
    sample = {
        "code": "510300",
        "recommend_close": 1.0,
        "instrument_type": "etf",
        "signal": {"buy_point": 0.98, "resistance": 1.1, "level_valid": True},
        "future_bars": [
            {"date": "2026-01-02", "previous_close": 1.0, "open": 0.99, "high": 1.0, "low": 0.97, "close": 1.0, "amount": 1000.0, "benchmark_return": 0.0},
            {"date": "2026-01-03", "previous_close": 1.0, "open": 0.9, "high": 0.9, "low": 0.9, "close": 0.9, "amount": 1000.0, "benchmark_return": -1.0},
        ],
    }

    result = resolve_historical_execution_window(sample, "pullback", validity_days=1)

    assert result["execution_status"] == "unverifiable"
    assert result["reason"] == "t1_exit_one_price_limit_down"
    assert result["net_excess_return"] is None


def test_order_validity_is_selected_on_training_dates_only() -> None:
    samples = []
    for day in range(1, 13):
        row = _board_profile_sample(day, f"etf-{day}", "broad", progressive=8.0, excess=0.0)
        if day <= 6:
            if day % 2:
                row["future_bars"] = [
                    {"date": f"2026-02-{day:02d}", "open": 96.0, "high": 97.0, "low": 94.0, "close": 94.0, "benchmark_return": 0.0},
                    {"date": f"2026-03-{day:02d}", "open": 94.0, "high": 95.0, "low": 93.0, "close": 94.0, "benchmark_return": 0.0},
                ]
            else:
                row["future_bars"] = [
                    {"date": f"2026-02-{day:02d}", "open": 100.0, "high": 101.0, "low": 98.0, "close": 99.0, "benchmark_return": 0.0},
                    {"date": f"2026-03-{day:02d}", "open": 96.0, "high": 101.0, "low": 94.0, "close": 100.0, "benchmark_return": 0.0},
                    {"date": f"2026-04-{day:02d}", "open": 100.0, "high": 102.0, "low": 99.0, "close": 100.0, "benchmark_return": 0.0},
                ]
        else:
            row["future_bars"] = [
                {"date": f"2026-04-{day:02d}", "open": 100.0, "high": 101.0, "low": 98.0, "close": 99.0, "benchmark_return": 0.0},
                {"date": f"2026-05-{day:02d}", "open": 96.0, "high": 97.0, "low": 94.0, "close": 93.0, "benchmark_return": 0.0},
                {"date": f"2026-06-{day:02d}", "open": 93.0, "high": 94.0, "low": 92.0, "close": 93.0, "benchmark_return": 0.0},
            ]
        samples.append(row)

    result = evaluate_order_validity_profiles(
        samples,
        segment="broad",
        train_days=6,
        top_n=20,
        min_train_fills=4,
        min_validation_fills=4,
    )

    assert result["selected_validity_days"] == 2
    assert result["training_candidates"][2]["by_fill_day"]["2"]["filled"] == 3
    assert result["training_candidates"][2]["by_fill_day"]["2"]["min_excess_return"] > 0
    assert result["train_end"] == "2026-01-06"
    assert result["validation_start"] == "2026-01-07"
    assert result["deployment_eligible"] is False


def test_rolling_order_validity_retrains_before_each_window() -> None:
    samples = []
    for day in range(1, 19):
        row = _board_profile_sample(day, f"etf-{day}", "broad", progressive=8.0, excess=0.0)
        row["future_bars"] = [
            {"date": f"2026-02-{day:02d}", "open": 100.0, "high": 101.0, "low": 98.0, "close": 99.0, "benchmark_return": 0.0},
            {"date": f"2026-03-{day:02d}", "open": 96.0, "high": 101.0, "low": 94.0, "close": 100.0, "benchmark_return": 0.0},
            {"date": f"2026-04-{day:02d}", "open": 100.0, "high": 102.0, "low": 99.0, "close": 100.0, "benchmark_return": 0.0},
        ]
        samples.append(row)

    result = evaluate_rolling_order_validity(
        samples,
        segment="broad",
        train_days=6,
        validation_days=4,
        top_n=20,
        min_train_fills=4,
        min_validation_fills=4,
    )

    assert result["window_count"] == 3
    assert result["consensus_validity_days"] == 2
    assert all(window["train_end"] < window["validation_start"] for window in result["windows"])
    assert result["deployment_eligible"] is False


def test_board_specific_profiles_select_different_training_winners_without_leakage() -> None:
    samples = []
    for day in range(1, 9):
        validation = day > 4
        samples.extend(
            [
                _board_profile_sample(day, "600001", "main", progressive=8, excess=1.0),
                _board_profile_sample(day, "600002", "main", progressive=5, excess=2.0),
                _board_profile_sample(day, "300001", "chinext", progressive=8, excess=2.0 if not validation else -2.0),
                _board_profile_sample(day, "300002", "chinext", progressive=5, excess=-1.0 if not validation else 3.0),
            ]
        )

    result = evaluate_board_specific_profiles(
        samples,
        train_days=4,
        top_n=10,
        min_train_fills=4,
        min_validation_fills=4,
        setups=("close",),
    )

    assert result["boards"]["main"]["selected_profile"] == "baseline"
    assert result["boards"]["chinext"]["selected_profile"] == "progressive_strict"
    assert result["boards"]["chinext"]["hit_rate_lift"] < 0
    assert result["boards"]["chinext"]["required_stable_windows"] >= 1
    assert set(result["boards"]["chinext"]["regime_validation_metrics"]) == {"bull", "sideways", "bear"}
    assert result["boards"]["chinext"]["cost_stress"]["0.25"]["total_cost_pct"] == 0.4
    assert result["boards"]["chinext"]["deployment_eligible"] is False


def test_board_specific_profiles_keep_sparse_boards_in_collecting_state() -> None:
    samples = [
        _board_profile_sample(day, "688001", "star", progressive=8, excess=1.0)
        for day in range(1, 7)
    ]

    result = evaluate_board_specific_profiles(
        samples,
        train_days=4,
        top_n=10,
        min_train_fills=4,
        min_validation_fills=3,
        setups=("close",),
    )

    assert result["boards"]["star"]["status"] == "collecting"
    assert result["boards"]["star"]["deployment_eligible"] is False


def test_board_profile_consensus_requires_same_scheme_across_multiple_samples() -> None:
    runs = [
        {"selected_profile": "baseline", "selected_setup": "auto", "deployment_eligible": True, "validation_metrics": {"filled": 40, "avg_excess_return": 0.4}, "baseline_validation_metrics": {"avg_excess_return": 0.0}, "hit_rate_lift": 5.0},
        {"selected_profile": "baseline", "selected_setup": "auto", "deployment_eligible": True, "validation_metrics": {"filled": 35, "avg_excess_return": 0.3}, "baseline_validation_metrics": {"avg_excess_return": 0.1}, "hit_rate_lift": 4.0},
        {"selected_profile": "progressive_strict", "selected_setup": "close", "deployment_eligible": False, "validation_metrics": {"filled": 50, "avg_excess_return": -0.1}, "baseline_validation_metrics": {"avg_excess_return": 0.0}, "hit_rate_lift": -2.0},
    ]

    result = assess_board_profile_consensus(runs)

    assert result["consensus_profile"] == "baseline"
    assert result["consensus_setup"] == "auto"
    assert result["matching_runs"] == 2
    assert result["total_validation_fills"] == 75
    assert result["eligible_for_review"] is True


def test_board_profile_consensus_rejects_a_single_sample_winner() -> None:
    runs = [
        {"selected_profile": "baseline", "selected_setup": "auto", "deployment_eligible": True, "validation_metrics": {"filled": 40, "avg_excess_return": 0.4}, "baseline_validation_metrics": {"avg_excess_return": 0.0}, "hit_rate_lift": 5.0},
        {"selected_profile": "progressive_strict", "selected_setup": "close", "deployment_eligible": False, "validation_metrics": {"filled": 60, "avg_excess_return": 0.1}, "baseline_validation_metrics": {"avg_excess_return": 0.0}, "hit_rate_lift": 1.0},
        {"selected_profile": "progressive_balanced", "selected_setup": "pullback", "deployment_eligible": False, "validation_metrics": {"filled": 50, "avg_excess_return": 0.2}, "baseline_validation_metrics": {"avg_excess_return": 0.0}, "hit_rate_lift": 2.0},
    ]

    result = assess_board_profile_consensus(runs)

    assert result["eligible_for_review"] is False
    assert "matching_runs_below_2" in result["blockers"]


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


def test_etf_samples_use_explicit_category_instead_of_stock_code_board() -> None:
    stock = _history([100 + index * 0.2 for index in range(70)])
    benchmark = _history([100 + index * 0.1 for index in range(70)])

    samples = build_historical_samples(
        {"510300": stock},
        benchmark,
        eval_days=5,
        segment_by_code={"510300": "broad"},
    )

    assert {row["market_board"] for row in samples} == {"broad"}


def test_etf_calibration_keeps_etf_categories_research_only(monkeypatch) -> None:
    stock = _history([100 + index * 0.2 for index in range(100)])
    benchmark = _history([100 + index * 0.1 for index in range(100)])
    monkeypatch.setattr(
        "app.services.recommend_history_replay_service._fetch_etf_history",
        lambda _code, _days: stock,
    )
    monkeypatch.setattr(
        "app.services.recommend_history_replay_service._fetch_benchmark",
        lambda _start, _end: benchmark,
    )

    result = run_etf_historical_calibration(
        etf_groups={"broad": ["510300"], "industry": [], "style": []},
        eval_days=40,
    )

    assert result["instrument_type"] == "etf"
    assert "ETF" in result["deployment_reason"]
    assert result["board_specific_research"]["mode"] == "research_only"
    assert "broad" in result["board_specific_research"]["boards"]
    assert "broad" in result["rolling_segment_research"]
    assert "broad" in result["rolling_regime_switching_research"]
    assert "broad" in result["rolling_liquidity_research"]
    assert "broad" in result["rolling_order_validity_research"]
    assert "broad" in result["rolling_high_win_rate_research"]
    assert "broad" in result["rolling_cross_sectional_factor_research"]
    assert result["backtest_caliber_audit"]["passed"] is False
    assert result["backtest_caliber_audit"]["deployment_eligible"] is False
    assert result["backtest_caliber_audit"]["checks"]["tick_size_rounding"]["passed"] is True
    assert result["backtest_caliber_audit"]["checks"]["price_limit_handling"]["passed"] is True
    assert result["fee_assumptions"]["broker_commission_verified"] is False
    assert "tick_size_rounding_missing" not in result["backtest_caliber_audit"]["blockers"]
    assert result["result_claim_scope"] == "research_diagnostic_only"
    assert result["deployment_eligible"] is False


def test_etf_calibration_keeps_pool_outcomes_separate_from_full_rank_universe(monkeypatch) -> None:
    stock = _history([100 + index * 0.2 for index in range(100)])
    benchmark = _history([100 + index * 0.1 for index in range(100)])
    monkeypatch.setattr(
        "app.services.recommend_history_replay_service._fetch_etf_history",
        lambda _code, _days: stock,
    )
    monkeypatch.setattr(
        "app.services.recommend_history_replay_service._fetch_benchmark",
        lambda _start, _end: benchmark,
    )

    result = run_etf_historical_calibration(
        etf_groups={"broad": ["a1", "a2", "b1", "b2"]},
        cross_sectional_evaluation_pools={
            "sample_a": ["a1", "a2"],
            "sample_b": ["b1", "b2"],
        },
        eval_days=40,
    )

    pool_research = result["rolling_cross_sectional_pool_research"]
    assert set(pool_research) == {"sample_a", "sample_b"}
    assert set(pool_research["sample_a"]) == {"broad"}
    assert set(pool_research["sample_b"]) == {"broad"}
    assert pool_research["sample_a"]["broad"]["evaluation_codes"] == ["a1", "a2"]
    assert pool_research["sample_a"]["broad"]["rank_reference_codes"] == 4


def test_etf_history_window_supports_five_year_replay() -> None:
    assert historical_window_days(1200, "etf") == 1300
    assert historical_window_days(1200, "stock") == 640


def test_execution_cost_stress_deducts_extra_slippage_from_filled_returns() -> None:
    sample = _board_profile_sample(1, "510300", "broad", progressive=8, excess=1.0)

    result = evaluate_execution_cost_stress(
        [sample],
        setup="close",
        extra_slippage_costs=(0.0, 0.1, 0.25),
    )

    assert result["0.00"]["avg_excess_return"] == pytest.approx(1.0)
    assert result["0.10"]["avg_excess_return"] == pytest.approx(0.9)
    assert result["0.25"]["avg_excess_return"] == pytest.approx(0.75)


def test_rolling_segment_profiles_use_only_prior_dates_for_each_window() -> None:
    samples = []
    for day in range(1, 19):
        for code, progressive, excess in (
            ("510300", 8.0, 1.0 if day <= 10 else -1.0),
            ("510500", 5.0, -0.5 if day <= 10 else 1.5),
        ):
            row = _board_profile_sample(day, code, "broad", progressive=progressive, excess=excess)
            row["market_regime"] = "bull" if day <= 9 else "bear"
            samples.append(row)

    result = evaluate_rolling_segment_profiles(
        samples,
        segment="broad",
        train_days=6,
        validation_days=4,
        top_n=5,
        min_train_fills=4,
        min_validation_fills=4,
        setups=("close",),
    )

    assert result["window_count"] == 3
    assert all(window["train_end"] < window["validation_start"] for window in result["windows"])
    assert [window["validation_start"] for window in result["windows"]] == [
        "2026-01-07", "2026-01-11", "2026-01-15"
    ]
    assert result["deployment_eligible"] is False


def test_regime_switching_profiles_choose_enabled_regimes_from_training_only() -> None:
    samples = []
    for day in range(1, 13):
        for regime, training_excess, validation_excess in (
            ("bull", 1.0, -1.0),
            ("bear", -1.0, 2.0),
        ):
            row = _board_profile_sample(
                day,
                f"{regime}-{day}",
                "broad",
                progressive=8.0,
                excess=training_excess if day <= 6 else validation_excess,
            )
            row["market_regime"] = regime
            samples.append(row)

    result = evaluate_regime_switching_profiles(
        samples,
        segment="broad",
        train_days=6,
        top_n=20,
        min_train_fills_per_regime=4,
        min_validation_fills=4,
        setups=("close",),
    )

    assert result["selected_regimes"] == ["bull"]
    assert result["train_end"] == "2026-01-06"
    assert result["validation_start"] == "2026-01-07"
    assert result["validation_metrics"]["filled"] == 6
    assert result["baseline_validation_metrics"]["filled"] == 12
    assert result["deployment_eligible"] is False


def test_rolling_regime_switching_retrains_before_each_forward_window() -> None:
    samples = []
    for day in range(1, 19):
        for regime, excess in (("bull", 1.0), ("bear", -1.0)):
            row = _board_profile_sample(
                day,
                f"{regime}-{day}",
                "broad",
                progressive=8.0,
                excess=excess,
            )
            row["market_regime"] = regime
            samples.append(row)

    result = evaluate_rolling_regime_switching(
        samples,
        segment="broad",
        train_days=6,
        validation_days=4,
        top_n=20,
        min_train_fills_per_regime=4,
        min_validation_fills=4,
        setups=("close",),
    )

    assert result["window_count"] == 3
    assert [window["validation_start"] for window in result["windows"]] == [
        "2026-01-07", "2026-01-11", "2026-01-15"
    ]
    assert all(window["selected_regimes"] == ["bull"] for window in result["windows"])
    assert all(window["train_end"] < window["validation_start"] for window in result["windows"])
    assert result["deployment_eligible"] is False


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
    assert result["regression_research"]["deployment_eligible"] is False
    assert result["board_specific_research"]["mode"] == "research_only"


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


def test_pullback_execution_uses_better_open_then_exits_on_following_trading_day() -> None:
    sample = {
        "recommend_close": 100.0,
        "instrument_type": "etf",
        "next_open": 94.0,
        "next_high": 101.0,
        "next_low": 93.0,
        "next_close": 99.0,
        "benchmark_return": 0.0,
        "signal": {"buy_point": 95.0, "resistance": 105.0, "level_valid": True},
        "future_bars": [
            {"date": "2026-01-02", "open": 94.0, "high": 101.0, "low": 93.0, "close": 99.0, "amount": 1000.0, "benchmark_return": 0.0},
            {"date": "2026-01-03", "open": 99.0, "high": 101.0, "low": 98.0, "close": 100.0, "amount": 1000.0, "benchmark_return": 0.0},
        ],
    }

    result = resolve_historical_execution(sample, "pullback")

    assert result["execution_status"] == "filled"
    assert result["entry_price"] == 94.0
    assert result["exit_date"] == "2026-01-03"
    assert result["net_excess_return"] == pytest.approx((100 / 94 - 1) * 100 - 0.15)


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
