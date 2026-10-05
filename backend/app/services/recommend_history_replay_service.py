"""Point-in-time historical replay for recommendation technical factors.

This intentionally does not fabricate historical PE/PB/turnover snapshots.
Results are research evidence only and cannot directly change live parameters.
"""
from __future__ import annotations

import datetime as dt
import math
from decimal import Decimal, ROUND_HALF_UP
from statistics import mean, median, pstdev

import akshare as ak
import pandas as pd

from app.services import akshare_guard, data_service, signal_service
from app.services.backtest_service import BENCHMARK, STRATEGY_BACKTEST_POOL
from app.services.recommend_calibration_service import calibrate_walk_forward
from app.services.recommend_regression_service import evaluate_walk_forward_regression

BASE_TRANSACTION_COST_PCT = 0.15
ETF_20_PCT_FROM_2020_08_24 = {"159915", "159949", "159967"}
ETF_20_PCT_FROM_LISTING = {"588000"}
ETF_10_PCT_CODES = {
    "510300", "510500", "510050", "512480", "512010", "512800",
    "515030", "515790", "510880", "512100", "515180",
}
KNOWN_ETF_PRICE_LIMIT_CODES = (
    ETF_20_PCT_FROM_2020_08_24 | ETF_20_PCT_FROM_LISTING | ETF_10_PCT_CODES
)


def _price_tick(instrument_type: str) -> float:
    return 0.001 if instrument_type == "etf" else 0.01


def _round_to_price_tick(price: float, instrument_type: str) -> float:
    tick = Decimal(str(_price_tick(instrument_type)))
    return float(Decimal(str(price)).quantize(tick, rounding=ROUND_HALF_UP))


def _bar_is_tradable(bar: dict) -> bool:
    amount = bar.get("amount")
    return amount is None or float(amount) > 0


def etf_price_limit_pct(code: str, trade_date: str) -> float | None:
    """Return verified ETF daily price-limit metadata for the research universe."""
    normalized = str(code).strip()
    if normalized in ETF_20_PCT_FROM_2020_08_24:
        return 20.0 if str(trade_date) >= "2020-08-24" else 10.0
    if normalized in ETF_20_PCT_FROM_LISTING:
        return 20.0
    if normalized in ETF_10_PCT_CODES:
        return 10.0
    return None


def etf_fee_assumptions() -> dict:
    """Separate verified exchange charges from account-specific broker costs."""
    return {
        "exchange_handling_fee_each_side_pct": 0.004,
        "stamp_tax_pct": 0.0,
        "broker_commission_verified": False,
        "minimum_commission_verified": False,
        "backtest_total_cost_pct": BASE_TRANSACTION_COST_PCT,
        "backtest_cost_mode": "conservative_all_in_pct",
    }


def _price_limit_bounds(bar: dict, instrument_type: str) -> tuple[float, float] | None:
    previous_close = bar.get("previous_close")
    limit_pct = bar.get("price_limit_pct")
    if previous_close is None or limit_pct is None:
        return None
    factor = float(limit_pct) / 100
    return (
        _round_to_price_tick(float(previous_close) * (1 - factor), instrument_type),
        _round_to_price_tick(float(previous_close) * (1 + factor), instrument_type),
    )


def _is_one_price_limit(bar: dict, instrument_type: str, *, side: str) -> bool:
    bounds = _price_limit_bounds(bar, instrument_type)
    if bounds is None:
        return False
    target = bounds[1] if side == "up" else bounds[0]
    prices = [float(bar[key]) for key in ("open", "high", "low", "close")]
    return all(_round_to_price_tick(price, instrument_type) == target for price in prices)


def assess_backtest_caliber(*, instrument_type: str, capabilities: dict) -> dict:
    """Audit whether a replay is detailed enough to support win-rate claims."""
    expected_settlement = "t_plus_1" if instrument_type in {"stock", "etf"} else None
    checks = {
        "settlement_rule": {
            "passed": capabilities.get("settlement_rule") == expected_settlement,
            "actual": capabilities.get("settlement_rule"),
            "expected": expected_settlement,
        },
        "price_limit_handling": {"passed": capabilities.get("price_limit_handling") is True},
        "tick_size_rounding": {"passed": capabilities.get("tick_size_rounding") is True},
        "fee_model_verified": {"passed": capabilities.get("fee_model_verified") is True},
        "historical_tradability": {"passed": capabilities.get("historical_tradability") is True},
        "point_in_time_features": {"passed": capabilities.get("point_in_time_features") is True},
        "benchmark_alignment": {"passed": capabilities.get("benchmark_alignment") is True},
    }
    blocker_by_check = {
        "settlement_rule": "settlement_rule_mismatch",
        "price_limit_handling": "price_limit_handling_missing",
        "tick_size_rounding": "tick_size_rounding_missing",
        "fee_model_verified": "fee_model_not_verified",
        "historical_tradability": "historical_tradability_missing",
        "point_in_time_features": "point_in_time_features_missing",
        "benchmark_alignment": "benchmark_alignment_missing",
    }
    blockers = [blocker_by_check[name] for name, check in checks.items() if not check["passed"]]
    passed = not blockers
    return {
        "status": "passed" if passed else "blocked",
        "passed": passed,
        "deployment_eligible": passed,
        "claim_scope": "candidate_win_rate" if passed else "research_diagnostic_only",
        "checks": checks,
        "blockers": blockers,
    }


def compute_execution_quality_features(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    amounts: list[float | None] | None = None,
) -> dict[str, float | None]:
    """Derive point-in-time ETF liquidity proxies from the signal bar and prior bars."""
    close = float(closes[-1])
    amplitude_pct = (float(highs[-1]) - float(lows[-1])) / close * 100 if close else None
    amount_ratio_20 = None
    if amounts and len(amounts) >= len(closes) and len(closes) >= 21:
        current = amounts[len(closes) - 1]
        previous = [
            float(value)
            for value in amounts[len(closes) - 21 : len(closes) - 1]
            if value is not None and float(value) > 0
        ]
        if current is not None and len(previous) == 20 and median(previous) > 0:
            amount_ratio_20 = float(current) / median(previous)
    return {
        "amount_ratio_20": round(amount_ratio_20, 6) if amount_ratio_20 is not None else None,
        "amplitude_pct": round(amplitude_pct, 6) if amplitude_pct is not None else None,
    }


def compute_point_in_time_features(
    closes: list[float],
    opens: list[float],
    turnovers: list[float | None] | None = None,
) -> dict[str, float | int | bool | None]:
    """Derive loss-rejection features from bars available at the signal close."""
    values = [float(value) for value in closes]
    open_values = [float(value) for value in opens]
    price = values[-1]
    ma20 = mean(values[-20:])
    previous_close = values[-2]
    gap_pct = (open_values[-1] / previous_close - 1) * 100 if previous_close else 0.0

    consecutive_up_days = 0
    for index in range(len(values) - 1, 0, -1):
        if values[index] <= values[index - 1]:
            break
        consecutive_up_days += 1

    turnover_ratio_5 = None
    if turnovers and len(turnovers) >= len(values):
        current_turnover = turnovers[len(values) - 1]
        previous_turnovers = [
            float(value)
            for value in turnovers[len(values) - 6 : len(values) - 1]
            if value is not None
        ]
        if current_turnover is not None and len(previous_turnovers) == 5 and mean(previous_turnovers) > 0:
            turnover_ratio_5 = float(current_turnover) / mean(previous_turnovers)
    five_day_return = (price / values[-6] - 1) * 100 if values[-6] else 0.0
    bearish_volume_divergence = (
        turnover_ratio_5 is not None and five_day_return > 0 and turnover_ratio_5 < 0.8
    )
    return {
        "ma20_distance_pct": round((price / ma20 - 1) * 100, 6) if ma20 else None,
        "gap_pct": round(gap_pct, 6),
        "consecutive_up_days": consecutive_up_days,
        "turnover_ratio_5": round(turnover_ratio_5, 6) if turnover_ratio_5 is not None else None,
        "bearish_volume_divergence": bearish_volume_divergence,
    }


def compute_relative_strength_features(
    closes: list[float], benchmark_closes: list[float] | None
) -> dict[str, float | bool | None]:
    """Compute signal-time trend alignment and 20-day benchmark-relative return."""
    values = [float(value) for value in closes]
    if len(values) < 60:
        return {
            "relative_strength_20d_pct": None,
            "trend_alignment_5_20_60": False,
        }
    ma5 = mean(values[-5:])
    ma20 = mean(values[-20:])
    ma60 = mean(values[-60:])
    relative_strength = None
    if benchmark_closes and len(benchmark_closes) >= 21:
        benchmark_values = [float(value) for value in benchmark_closes]
        stock_return = (values[-1] / values[-21] - 1) * 100 if values[-21] else 0.0
        benchmark_return = (
            (benchmark_values[-1] / benchmark_values[-21] - 1) * 100
            if benchmark_values[-21]
            else 0.0
        )
        relative_strength = stock_return - benchmark_return
    return {
        "relative_strength_20d_pct": (
            round(relative_strength, 6) if relative_strength is not None else None
        ),
        "trend_alignment_5_20_60": values[-1] > ma5 > ma20 > ma60,
    }


def _cross_sectional_factor_value(row: dict, factor_key: str, factor_source: str) -> float | None:
    source = row if factor_source == "sample" else row.get(factor_source) or {}
    value = source.get(factor_key)
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def evaluate_cross_sectional_factor(
    samples: list[dict],
    *,
    segment: str,
    factor_key: str,
    factor_source: str = "point_in_time_features",
    rank_reference_samples: list[dict] | None = None,
    horizons: tuple[int, ...] = (1, 3, 5),
    quantile_count: int = 3,
) -> dict:
    """Evaluate one factor by same-day ranks without using future data as a feature."""
    if quantile_count < 2:
        raise ValueError("quantile_count must be at least 2")
    rows = []
    for sample in samples:
        if sample.get("market_board") != segment:
            continue
        factor_value = _cross_sectional_factor_value(sample, factor_key, factor_source)
        if factor_value is None:
            continue
        returns = sample.get("holding_excess_returns") or {}
        rows.append(
            {
                "date": str(sample["date"]),
                "code": str(sample.get("code") or ""),
                **{
                    f"return_{horizon}": (
                        float(returns[str(horizon)])
                        if str(horizon) in returns and returns[str(horizon)] is not None
                        else None
                    )
                    for horizon in horizons
                },
            }
        )
    rank_rows = []
    for sample in rank_reference_samples if rank_reference_samples is not None else samples:
        if sample.get("market_board") != segment:
            continue
        factor_value = _cross_sectional_factor_value(sample, factor_key, factor_source)
        if factor_value is None:
            continue
        rank_rows.append(
            {
                "date": str(sample["date"]),
                "code": str(sample.get("code") or ""),
                "factor": factor_value,
            }
        )
    frame = pd.DataFrame(rows)
    rank_frame = pd.DataFrame(rank_rows).drop_duplicates(subset=["date", "code"], keep="last")
    horizon_results: dict[str, dict] = {}
    if frame.empty or rank_frame.empty:
        return {
            "factor": factor_key,
            "factor_source": factor_source,
            "segment": segment,
            "date_count": 0,
            "observation_count": 0,
            "rank_reference_observation_count": len(rank_frame),
            "horizons": horizon_results,
        }
    rank_frame["factor_percentile"] = rank_frame.groupby("date")["factor"].rank(
        method="average", pct=True
    )
    rank_frame["factor_order"] = rank_frame.groupby("date")["factor"].rank(method="first")
    group_sizes = rank_frame.groupby("date")["factor"].transform("count")
    rank_frame["quantile"] = (
        ((rank_frame["factor_order"] - 1) * quantile_count // group_sizes) + 1
    ).astype(int).clip(upper=quantile_count)
    frame = frame.merge(
        rank_frame[["date", "code", "factor", "factor_percentile", "quantile"]],
        on=["date", "code"],
        how="inner",
        validate="many_to_one",
    )
    for horizon in horizons:
        return_key = f"return_{horizon}"
        usable = frame.dropna(subset=[return_key]).copy()
        daily_ics = []
        for _date, group in usable.groupby("date"):
            if len(group) < 2 or group["factor"].nunique() < 2 or group[return_key].nunique() < 2:
                continue
            correlation = group["factor"].corr(group[return_key], method="spearman")
            if pd.notna(correlation):
                daily_ics.append(float(correlation))
        quantile_returns = {
            str(int(quantile)): round(float(value), 6)
            for quantile, value in usable.groupby("quantile")[return_key].mean().items()
        }
        ordered_returns = [
            quantile_returns[str(quantile)]
            for quantile in sorted(int(key) for key in quantile_returns)
        ]
        monotonic = all(
            left <= right
            for left, right in zip(ordered_returns, ordered_returns[1:])
        ) and len(ordered_returns) >= 2
        mean_ic = mean(daily_ics) if daily_ics else None
        ic_std = pstdev(daily_ics) if len(daily_ics) >= 2 else None
        horizon_results[str(horizon)] = {
            "observation_count": len(usable),
            "ic_date_count": len(daily_ics),
            "mean_rank_ic": round(mean_ic, 6) if mean_ic is not None else None,
            "rank_ic_ir": (
                round(mean_ic / ic_std, 6)
                if mean_ic is not None and ic_std is not None and ic_std > 0
                else None
            ),
            "quantile_returns": quantile_returns,
            "high_minus_low": (
                round(ordered_returns[-1] - ordered_returns[0], 6)
                if len(ordered_returns) >= 2
                else None
            ),
            "monotonic": monotonic,
        }
    return {
        "factor": factor_key,
        "factor_source": factor_source,
        "segment": segment,
        "date_count": int(frame["date"].nunique()),
        "observation_count": len(frame),
        "rank_reference_observation_count": len(rank_frame),
        "horizons": horizon_results,
    }


DEFAULT_CROSS_SECTIONAL_FACTOR_SPECS = (
    ("relative_strength_20d_pct", "point_in_time_features"),
    ("ma20_distance_pct", "point_in_time_features"),
    ("amount_ratio_20", "point_in_time_features"),
    ("amplitude_pct", "point_in_time_features"),
    ("trend_progressive", "strategy_scores"),
    ("historical_volatility", "sample"),
)


def evaluate_rolling_cross_sectional_factors(
    samples: list[dict],
    *,
    segment: str,
    rank_reference_samples: list[dict] | None = None,
    factor_specs: tuple[tuple[str, str], ...] = DEFAULT_CROSS_SECTIONAL_FACTOR_SPECS,
    train_days: int = 240,
    validation_days: int = 60,
    min_train_observations: int = 100,
    min_validation_observations: int = 30,
    min_abs_train_rank_ic: float = 0.02,
    min_abs_validation_rank_ic: float = 0.02,
    quantile_count: int = 3,
) -> dict:
    """Select a factor and its direction on expanding training data, then test forward."""
    segment_rows = [row for row in samples if row.get("market_board") == segment]
    reference_segment_rows = [
        row
        for row in (rank_reference_samples if rank_reference_samples is not None else samples)
        if row.get("market_board") == segment
    ]
    dates = sorted({str(row["date"]) for row in segment_rows})
    windows = []
    for validation_start in range(train_days, len(dates), validation_days):
        validation_dates_list = dates[validation_start : validation_start + validation_days]
        if not validation_dates_list:
            break
        train_dates = set(dates[:validation_start])
        validation_dates = set(validation_dates_list)
        training_rows = [row for row in segment_rows if str(row["date"]) in train_dates]
        validation_rows = [row for row in segment_rows if str(row["date"]) in validation_dates]
        training_reference_rows = [
            row for row in reference_segment_rows if str(row["date"]) in train_dates
        ]
        validation_reference_rows = [
            row for row in reference_segment_rows if str(row["date"]) in validation_dates
        ]
        training_candidates = []
        for factor_key, factor_source in factor_specs:
            diagnostics = evaluate_cross_sectional_factor(
                training_rows,
                segment=segment,
                factor_key=factor_key,
                factor_source=factor_source,
                rank_reference_samples=training_reference_rows,
                horizons=(1,),
                quantile_count=quantile_count,
            )
            metrics = diagnostics["horizons"].get("1") or {}
            if (
                diagnostics["observation_count"] >= min_train_observations
                and metrics.get("mean_rank_ic") is not None
                and abs(float(metrics["mean_rank_ic"])) >= min_abs_train_rank_ic
            ):
                training_candidates.append((factor_key, factor_source, diagnostics))
        selected = max(
            training_candidates,
            key=lambda candidate: (
                abs(float(candidate[2]["horizons"]["1"]["mean_rank_ic"])),
                -factor_specs.index((candidate[0], candidate[1])),
            ),
            default=None,
        )
        if selected is None:
            windows.append(
                {
                    "train_end": dates[validation_start - 1],
                    "validation_start": validation_dates_list[0],
                    "validation_end": validation_dates_list[-1],
                    "selected_factor": None,
                    "passed": False,
                    "reason": "no_stable_training_factor",
                }
            )
            continue
        factor_key, factor_source, training_diagnostics = selected
        train_ic = float(training_diagnostics["horizons"]["1"]["mean_rank_ic"])
        validation_diagnostics = evaluate_cross_sectional_factor(
            validation_rows,
            segment=segment,
            factor_key=factor_key,
            factor_source=factor_source,
            rank_reference_samples=validation_reference_rows,
            horizons=(1, 3, 5),
            quantile_count=quantile_count,
        )
        validation_metrics = validation_diagnostics["horizons"].get("1") or {}
        validation_ic = validation_metrics.get("mean_rank_ic")
        high_minus_low = validation_metrics.get("high_minus_low")
        direction = "higher" if train_ic >= 0 else "lower"
        preferred_spread = (
            high_minus_low
            if direction == "higher" or high_minus_low is None
            else -float(high_minus_low)
        )
        passed = (
            validation_diagnostics["observation_count"] >= min_validation_observations
            and validation_ic is not None
            and abs(float(validation_ic)) >= min_abs_validation_rank_ic
            and float(validation_ic) * train_ic > 0
            and preferred_spread is not None
            and float(preferred_spread) > 0
        )
        windows.append(
            {
                "train_end": dates[validation_start - 1],
                "validation_start": validation_dates_list[0],
                "validation_end": validation_dates_list[-1],
                "selected_factor": factor_key,
                "selected_factor_source": factor_source,
                "direction": direction,
                "training_diagnostics": training_diagnostics,
                "validation_diagnostics": validation_diagnostics,
                "preferred_spread": (
                    round(float(preferred_spread), 6) if preferred_spread is not None else None
                ),
                "passed": passed,
            }
        )
    factor_counts = {}
    for window in windows:
        factor = window.get("selected_factor")
        if factor:
            factor_counts[factor] = factor_counts.get(factor, 0) + 1
    consensus_factor = max(factor_counts, key=factor_counts.get, default=None)
    matching_windows = factor_counts.get(consensus_factor, 0) if consensus_factor else 0
    factor_direction_counts = {}
    for window in windows:
        factor = window.get("selected_factor")
        direction = window.get("direction")
        if factor and direction:
            key = (factor, direction)
            factor_direction_counts[key] = factor_direction_counts.get(key, 0) + 1
    consensus_factor_direction = max(
        factor_direction_counts,
        key=factor_direction_counts.get,
        default=None,
    )
    consensus_direction = (
        consensus_factor_direction[1] if consensus_factor_direction is not None else None
    )
    matching_factor_direction_windows = (
        factor_direction_counts.get(consensus_factor_direction, 0)
        if consensus_factor_direction is not None
        else 0
    )
    passed_windows = sum(bool(window.get("passed")) for window in windows)
    required_windows = math.ceil(len(windows) * 2 / 3) if windows else 0
    eligible_for_review = (
        bool(windows)
        and consensus_factor is not None
        and matching_windows >= required_windows
        and matching_factor_direction_windows >= required_windows
        and passed_windows >= required_windows
    )
    return {
        "segment": segment,
        "window_count": len(windows),
        "passed_windows": passed_windows,
        "required_windows": required_windows,
        "consensus_factor": consensus_factor,
        "consensus_direction": consensus_direction,
        "matching_windows": matching_windows,
        "matching_factor_direction_windows": matching_factor_direction_windows,
        "eligible_for_review": eligible_for_review,
        "deployment_eligible": False,
        "windows": windows,
        "caliber": "expanding_train_cross_sectional_rank_ic_forward_validation",
        "min_abs_train_rank_ic": min_abs_train_rank_ic,
        "min_abs_validation_rank_ic": min_abs_validation_rank_ic,
    }


def compute_technical_strategy_scores(
    closes: list[float],
    turnovers: list[float | None] | None = None,
) -> dict[str, float] | None:
    """Reproduce the live momentum/trend components using only past closes."""
    if len(closes) < 61:
        return None
    values = [float(value) for value in closes]
    price = values[-1]
    ma5 = sum(values[-5:]) / 5
    ma20 = sum(values[-20:]) / 20
    ma60 = sum(values[-60:]) / 60

    ema12 = ema26 = values[0]
    difs: list[float] = []
    for value in values:
        ema12 += (value - ema12) * 2 / 13
        ema26 += (value - ema26) * 2 / 27
        difs.append(ema12 - ema26)
    dea = sum(difs[-9:]) / 9
    macd = (difs[-1] - dea) * 2

    changes = [values[index] - values[index - 1] for index in range(len(values) - 14, len(values))]
    avg_gain = sum(max(change, 0) for change in changes) / 14
    avg_loss = sum(max(-change, 0) for change in changes) / 14
    rsi = 100 - 100 / (1 + avg_gain / avg_loss) if avg_loss > 0 else 100
    pct_from_high = (price / max(values) - 1) * 100
    change_pct = (price / values[-2] - 1) * 100 if values[-2] else 0

    momentum = 0.0
    momentum += 2 if price > ma5 else 0
    momentum += 2 if macd > 0 else 0
    momentum += 2 if 50 <= rsi <= 75 else 0
    momentum += 2 if pct_from_high > -10 else 0
    momentum += max(0.0, change_pct) * 0.3

    trend = 0.0
    if ma5 > ma20 > ma60 and price > ma5:
        trend = 5 + min(3.0, pct_from_high * 0.15)
    progressive_trend = 0.0
    progressive_trend += 2 if price > ma5 else 0
    progressive_trend += 3 if ma5 > ma20 else 0
    progressive_trend += 3 if ma20 > ma60 else 0
    progressive_trend += 2 if price > ma60 else 0

    turnover = None
    if turnovers and len(turnovers) >= len(values):
        raw_turnover = turnovers[len(values) - 1]
        turnover = float(raw_turnover) if raw_turnover is not None else None
    volume = 0.0
    if turnover is not None and 2 <= turnover <= 12:
        volume += 3
    if 0 < change_pct <= 8:
        volume += 2
    if macd > 0:
        volume += 2

    return {
        "momentum": round(momentum, 6),
        "trend": round(trend, 6),
        "trend_progressive": round(progressive_trend, 6),
        "value": 0.0,
        "volume": round(volume, 6),
    }


def _indexed(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["date"] = pd.to_datetime(result["date"])
    return result.sort_values("date").drop_duplicates("date").set_index("date")


def build_category_relative_benchmarks(
    histories: dict[str, pd.DataFrame],
    segment_by_code: dict[str, str],
) -> dict[str, pd.DataFrame]:
    """Build point-in-time, leave-one-out category benchmarks for ETF features."""
    indexed_closes = {
        code: _indexed(frame)["close"].astype(float)
        for code, frame in histories.items()
        if frame is not None and not frame.empty and "close" in frame.columns
    }
    benchmarks: dict[str, pd.DataFrame] = {}
    for code in indexed_closes:
        segment = segment_by_code.get(code)
        peers = [
            series.rename(peer_code)
            for peer_code, series in indexed_closes.items()
            if peer_code != code and segment_by_code.get(peer_code) == segment
        ]
        if not peers:
            continue
        if len(peers) == 1:
            benchmark_close = peers[0].rename("close")
        else:
            peer_closes = pd.concat(peers, axis=1, join="inner").dropna()
            peer_returns = peer_closes.pct_change(fill_method=None)
            equal_weight_return = peer_returns.mean(axis=1)
            benchmark_close = (1 + equal_weight_return.fillna(0.0)).cumprod() * 100.0
            benchmark_close.name = "close"
        benchmarks[code] = benchmark_close.rename_axis("date").reset_index()
    return benchmarks


def classify_market_regime(closes: list[float]) -> str:
    if len(closes) < 60:
        return "unknown"
    ma20 = mean(float(value) for value in closes[-20:])
    ma60 = mean(float(value) for value in closes[-60:])
    current = float(closes[-1])
    if current > ma60 and ma20 > ma60:
        return "bull"
    if current < ma60 and ma20 < ma60:
        return "bear"
    return "sideways"


def market_board(code: str) -> str:
    if str(code).startswith(("300", "301")):
        return "chinext"
    if str(code).startswith(("688", "689")):
        return "star"
    return "main"


def build_historical_samples(
    histories: dict[str, pd.DataFrame],
    benchmark: pd.DataFrame,
    *,
    eval_days: int = 120,
    segment_by_code: dict[str, str] | None = None,
    instrument_type: str = "stock",
    relative_benchmarks_by_code: dict[str, pd.DataFrame] | None = None,
) -> list[dict]:
    """Build T-close signals and T+1 close excess returns without look-ahead."""
    if benchmark is None or benchmark.empty:
        return []
    benchmark_indexed = _indexed(benchmark)
    samples: list[dict] = []
    for code, raw in histories.items():
        if raw is None or raw.empty:
            continue
        frame = _indexed(raw)
        relative_benchmark = (relative_benchmarks_by_code or {}).get(code)
        relative_benchmark_indexed = (
            _indexed(relative_benchmark)
            if relative_benchmark is not None and not relative_benchmark.empty
            else benchmark_indexed
        )
        shared = frame.index.intersection(benchmark_indexed.index).sort_values()
        eligible_dates = [
            day
            for day in shared
            if frame.index.get_loc(day) >= 60
            and frame.index.get_loc(day) + 1 < len(frame)
            and frame.index[frame.index.get_loc(day) + 1] in benchmark_indexed.index
        ][-eval_days:]
        for day in eligible_dates:
            position = frame.index.get_loc(day)
            outcome_day = frame.index[position + 1]
            closes = frame.iloc[: position + 1]["close"].astype(float).tolist()
            opens = frame.iloc[: position + 1]["open"].astype(float).tolist()
            turnovers = (
                frame.iloc[: position + 1]["turnover"].tolist()
                if "turnover" in frame.columns
                else None
            )
            amounts = (
                frame.iloc[: position + 1]["amount"].tolist()
                if "amount" in frame.columns
                else None
            )
            scores = compute_technical_strategy_scores(closes, turnovers)
            if scores is None:
                continue
            point_in_time_features = compute_point_in_time_features(closes, opens, turnovers)
            relative_dates = list(frame.index[max(0, position - 60) : position + 1])
            benchmark_closes = (
                [float(relative_benchmark_indexed.loc[index, "close"]) for index in relative_dates]
                if all(index in relative_benchmark_indexed.index for index in relative_dates)
                else None
            )
            point_in_time_features.update(
                compute_relative_strength_features(closes, benchmark_closes)
            )
            point_in_time_features.update(
                compute_execution_quality_features(
                    frame.iloc[: position + 1]["high"].astype(float).tolist(),
                    frame.iloc[: position + 1]["low"].astype(float).tolist(),
                    closes,
                    amounts,
                )
            )
            signal = signal_service.compute_signals(
                closes,
                float(frame.loc[day, "close"]),
                highs=frame.iloc[: position + 1]["high"].astype(float).tolist(),
                lows=frame.iloc[: position + 1]["low"].astype(float).tolist(),
            )
            daily_returns = [(closes[i] / closes[i - 1] - 1) for i in range(len(closes) - 20, len(closes)) if closes[i - 1]]
            historical_volatility = pstdev(daily_returns) * math.sqrt(252) * 100 if len(daily_returns) >= 2 else None
            stock_return = (float(frame.loc[outcome_day, "close"]) / float(frame.loc[day, "close"]) - 1) * 100
            benchmark_return = (
                float(benchmark_indexed.loc[outcome_day, "close"])
                / float(benchmark_indexed.loc[day, "close"])
                - 1
            ) * 100
            holding_returns: dict[str, float] = {}
            holding_dates: dict[str, str] = {}
            future_bars: list[dict] = []
            for horizon in (1, 3, 5):
                future_position = position + horizon
                if future_position >= len(frame):
                    continue
                future_day = frame.index[future_position]
                if future_day not in benchmark_indexed.index:
                    continue
                stock_h = (float(frame.iloc[future_position]["close"]) / float(frame.loc[day, "close"]) - 1) * 100
                bench_h = (float(benchmark_indexed.loc[future_day, "close"]) / float(benchmark_indexed.loc[day, "close"]) - 1) * 100
                holding_returns[str(horizon)] = round(stock_h - bench_h - BASE_TRANSACTION_COST_PCT, 6)
                holding_dates[str(horizon)] = future_day.date().isoformat()
            for offset in range(1, 5):
                future_position = position + offset
                if future_position >= len(frame):
                    break
                future_day = frame.index[future_position]
                if future_day not in benchmark_indexed.index:
                    break
                cumulative_benchmark_return = (
                    float(benchmark_indexed.loc[future_day, "close"])
                    / float(benchmark_indexed.loc[day, "close"])
                    - 1
                ) * 100
                future_bars.append(
                    {
                        "date": future_day.date().isoformat(),
                        "open": float(frame.iloc[future_position]["open"]),
                        "high": float(frame.iloc[future_position]["high"]),
                        "low": float(frame.iloc[future_position]["low"]),
                        "close": float(frame.iloc[future_position]["close"]),
                        "previous_close": float(frame.iloc[future_position - 1]["close"]),
                        "price_limit_pct": (
                            etf_price_limit_pct(code, future_day.date().isoformat())
                            if instrument_type == "etf"
                            else None
                        ),
                        "amount": (
                            float(frame.iloc[future_position]["amount"])
                            if "amount" in frame.columns
                            and pd.notna(frame.iloc[future_position]["amount"])
                            else None
                        ),
                        "benchmark_return": round(cumulative_benchmark_return, 6),
                    }
                )
            samples.append(
                {
                    "date": day.date().isoformat(),
                    "outcome_date": outcome_day.date().isoformat(),
                    "code": code,
                    "instrument_type": instrument_type,
                    "strategy_scores": scores,
                    "excess_return": round(stock_return - benchmark_return - BASE_TRANSACTION_COST_PCT, 6),
                    "benchmark_return": round(benchmark_return, 6),
                    "recommend_close": float(frame.loc[day, "close"]),
                    "next_open": float(frame.loc[outcome_day, "open"]),
                    "next_high": float(frame.loc[outcome_day, "high"]),
                    "next_low": float(frame.loc[outcome_day, "low"]),
                    "next_close": float(frame.loc[outcome_day, "close"]),
                    "signal": signal,
                    "market_regime": classify_market_regime(
                        benchmark_indexed.loc[:day, "close"].astype(float).tolist()
                    ),
                    "holding_excess_returns": holding_returns,
                    "holding_outcome_dates": holding_dates,
                    "future_bars": future_bars,
                    "market_board": (segment_by_code or {}).get(code, market_board(code)),
                    "historical_volatility": round(historical_volatility, 4) if historical_volatility is not None else None,
                    "point_in_time_features": point_in_time_features,
                }
            )
    return samples


def resolve_historical_execution(sample: dict, setup: str) -> dict:
    """Resolve a T+1 execution from real OHLC; unfilled plans stay out of returns."""
    if setup != "close":
        result = resolve_historical_execution_window(sample, setup, validity_days=1)
        if result.get("execution_status") == "expired":
            result["execution_status"] = "not_triggered"
        return result
    close = float(sample["recommend_close"])
    exit_price = float(sample["next_close"])
    instrument_type = str(sample.get("instrument_type") or "stock")
    entry = _round_to_price_tick(close, instrument_type)
    net = (exit_price / entry - 1) * 100 - 0.15 - float(sample.get("benchmark_return") or 0)
    return {
        "execution_status": "filled",
        "entry_price": entry,
        "exit_price": exit_price,
        "price_tick": _price_tick(instrument_type),
        "net_excess_return": round(net, 6),
    }


def resolve_historical_execution_window(
    sample: dict, setup: str, *, validity_days: int
) -> dict:
    """Resolve the first real trigger within an order-validity window."""
    if validity_days < 1:
        raise ValueError("validity_days must be at least 1")
    close = float(sample["recommend_close"])
    signal = sample.get("signal") or {}
    expected = signal_service.expected_price_from_levels(close, signal, setup=setup)
    if not expected or not signal.get("level_valid"):
        return {
            "execution_status": "unverifiable",
            "fill_day": None,
            "entry_price": None,
            "net_excess_return": None,
        }
    is_pullback = expected["setup"] == "pullback"
    instrument_type = str(sample.get("instrument_type") or "stock")
    structure_key = "buy_point" if is_pullback else "resistance"
    raw_trigger = signal.get(structure_key, expected["price"])
    trigger = _round_to_price_tick(float(raw_trigger), instrument_type)
    future_bars = list(sample.get("future_bars") or [])
    rejection_reason = None
    for fill_day, raw_bar in enumerate(future_bars[:validity_days], start=1):
        bar = dict(raw_bar)
        if instrument_type == "etf" and bar.get("price_limit_pct") is None:
            bar["price_limit_pct"] = etf_price_limit_pct(
                str(sample.get("code") or ""), str(bar.get("date") or "")
            )
        if not _bar_is_tradable(bar):
            continue
        if not is_pullback and _is_one_price_limit(bar, instrument_type, side="up"):
            rejection_reason = "one_price_limit_up"
            continue
        bounds = _price_limit_bounds(bar, instrument_type)
        if bounds is not None and not bounds[0] <= trigger <= bounds[1]:
            rejection_reason = "order_price_outside_daily_limit"
            continue
        open_price = float(bar["open"])
        filled = float(bar["low"]) <= trigger if is_pullback else float(bar["high"]) >= trigger
        if not filled:
            continue
        if fill_day >= len(future_bars):
            return {
                "execution_status": "unverifiable",
                "fill_day": fill_day,
                "entry_price": None,
                "net_excess_return": None,
            }
        exit_bar = dict(future_bars[fill_day])
        if instrument_type == "etf" and exit_bar.get("price_limit_pct") is None:
            exit_bar["price_limit_pct"] = etf_price_limit_pct(
                str(sample.get("code") or ""), str(exit_bar.get("date") or "")
            )
        if not _bar_is_tradable(exit_bar):
            return {
                "execution_status": "unverifiable",
                "reason": "t1_exit_not_tradable",
                "fill_day": fill_day,
                "fill_date": bar.get("date"),
                "exit_date": exit_bar.get("date"),
                "entry_price": None,
                "net_excess_return": None,
            }
        if _is_one_price_limit(exit_bar, instrument_type, side="down"):
            return {
                "execution_status": "unverifiable",
                "reason": "t1_exit_one_price_limit_down",
                "fill_day": fill_day,
                "fill_date": bar.get("date"),
                "exit_date": exit_bar.get("date"),
                "entry_price": None,
                "net_excess_return": None,
            }
        entry = min(trigger, open_price) if is_pullback else max(trigger, open_price)
        exit_price = float(exit_bar["close"])
        net = (
            (exit_price / entry - 1) * 100
            - BASE_TRANSACTION_COST_PCT
            - float(exit_bar.get("benchmark_return") or 0)
        )
        return {
            "execution_status": "filled",
            "fill_day": fill_day,
            "fill_date": bar.get("date"),
            "exit_date": exit_bar.get("date"),
            "entry_price": _round_to_price_tick(entry, instrument_type),
            "price_tick": _price_tick(instrument_type),
            "exit_price": exit_price,
            "net_excess_return": net,
        }
    return {
        "execution_status": "expired",
        **({"reason": rejection_reason} if rejection_reason else {}),
        "fill_day": None,
        "entry_price": None,
        "net_excess_return": None,
    }


def _execution_metrics(samples: list[dict], setup: str) -> dict:
    outcomes = [resolve_historical_execution(sample, setup) for sample in samples]
    returns = [row["net_excess_return"] for row in outcomes if row["net_excess_return"] is not None]
    return {
        "plans": len(outcomes),
        "filled": len(returns),
        "fill_rate": round(len(returns) / len(outcomes) * 100, 2) if outcomes else None,
        "hit_rate": round(sum(value > 0 for value in returns) / len(returns) * 100, 2) if returns else None,
        "avg_excess_return": round(mean(returns), 4) if returns else None,
    }


def evaluate_execution_cost_stress(
    samples: list[dict],
    *,
    setup: str,
    extra_slippage_costs: tuple[float, ...] = (0.0, 0.10, 0.25),
) -> dict:
    outcomes = [resolve_historical_execution(sample, setup) for sample in samples]
    base_returns = [float(row["net_excess_return"]) for row in outcomes if row["net_excess_return"] is not None]
    return {
        f"{extra_cost:.2f}": {
            "filled": len(base_returns),
            "hit_rate": round(sum(value - extra_cost > 0 for value in base_returns) / len(base_returns) * 100, 2)
            if base_returns else None,
            "avg_excess_return": round(mean(value - extra_cost for value in base_returns), 4)
            if base_returns else None,
            "total_cost_pct": round(BASE_TRANSACTION_COST_PCT + extra_cost, 2),
        }
        for extra_cost in extra_slippage_costs
    }


def select_execution_profile(training: dict[str, dict], *, min_train_fills: int = 30) -> str:
    eligible = [key for key, metrics in training.items() if int(metrics.get("filled") or 0) >= min_train_fills]
    if not eligible:
        return "close"
    order = tuple(training)
    return max(
        eligible,
        key=lambda setup: (
            training[setup]["hit_rate"] if training[setup]["hit_rate"] is not None else -1,
            training[setup]["avg_excess_return"] if training[setup]["avg_excess_return"] is not None else -999,
            -order.index(setup),
        ),
    )


def evaluate_execution_profiles(samples: list[dict], *, train_days: int = 80, top_n: int = 10) -> dict:
    dates = sorted({str(sample["date"]) for sample in samples})
    if len(dates) <= train_days:
        return {"status": "insufficient_dates", "deployment_eligible": False}
    selected, _ = _gate_profile_rows(samples, _GATE_PROFILES[0], top_n)
    train = [sample for sample in selected if str(sample["date"]) <= dates[train_days - 1]]
    validation = [sample for sample in selected if str(sample["date"]) >= dates[train_days]]
    training = {setup: _execution_metrics(train, setup) for setup in ("close", "pullback", "breakout", "auto")}
    selected_setup = select_execution_profile(training, min_train_fills=30)
    chosen = _execution_metrics(validation, selected_setup)
    baseline = _execution_metrics(validation, "close")
    lift = None if chosen["hit_rate"] is None or baseline["hit_rate"] is None else round(chosen["hit_rate"] - baseline["hit_rate"], 2)
    eligible = selected_setup != "close" and chosen["filled"] >= 30 and lift is not None and lift >= 3 and (chosen["avg_excess_return"] or 0) > (baseline["avg_excess_return"] or 0)
    return {
        "status": "eligible_for_review" if eligible else "no_stable_improvement",
        "deployment_eligible": eligible,
        "selected_setup": selected_setup,
        "train_end": dates[train_days - 1],
        "validation_start": dates[train_days],
        "training_profiles": training,
        "validation_metrics": chosen,
        "baseline_validation_metrics": baseline,
        "hit_rate_lift": lift,
        "fee_pct": 0.15,
    }


def evaluate_board_specific_profiles(
    samples: list[dict],
    *,
    train_days: int = 80,
    top_n: int = 10,
    min_train_fills: int = 30,
    min_validation_fills: int = 30,
    setups: tuple[str, ...] = ("close", "pullback", "breakout", "auto"),
    segments: tuple[str, ...] = ("main", "chinext", "star"),
) -> dict:
    """Fit gate/execution combinations independently per board, then test untouched dates."""
    board_results: dict[str, dict] = {}
    for board in segments:
        board_samples = [row for row in samples if row.get("market_board") == board]
        dates = sorted({str(row["date"]) for row in board_samples})
        if len(dates) <= train_days:
            board_results[board] = {
                "status": "collecting",
                "deployment_eligible": False,
                "sample_dates": len(dates),
                "blockers": ["insufficient_dates"],
            }
            continue
        train_dates = set(dates[:train_days])
        validation_dates = set(dates[train_days:])
        train_rows = [row for row in board_samples if str(row["date"]) in train_dates]
        validation_rows = [row for row in board_samples if str(row["date"]) in validation_dates]
        candidates: list[dict] = []
        for profile in _GATE_PROFILES:
            selected, _ = _gate_profile_rows(train_rows, profile, top_n)
            for setup in setups:
                candidates.append(
                    {
                        "profile": profile["key"],
                        "setup": setup,
                        "metrics": _execution_metrics(selected, setup),
                    }
                )
        eligible_training = [
            candidate
            for candidate in candidates
            if int(candidate["metrics"].get("filled") or 0) >= min_train_fills
        ]
        selected_candidate = max(
            eligible_training or [candidates[0]],
            key=lambda candidate: (
                candidate["metrics"]["hit_rate"] if candidate["metrics"]["hit_rate"] is not None else -1,
                candidate["metrics"]["avg_excess_return"] if candidate["metrics"]["avg_excess_return"] is not None else -999,
                -candidates.index(candidate),
            ),
        )
        selected_profile = next(
            profile for profile in _GATE_PROFILES if profile["key"] == selected_candidate["profile"]
        )
        selected_validation, _ = _gate_profile_rows(validation_rows, selected_profile, top_n)
        baseline_validation, _ = _gate_profile_rows(validation_rows, _GATE_PROFILES[0], top_n)
        chosen_metrics = _execution_metrics(selected_validation, selected_candidate["setup"])
        baseline_metrics = _execution_metrics(baseline_validation, "close")
        hit_lift = None
        if chosen_metrics["hit_rate"] is not None and baseline_metrics["hit_rate"] is not None:
            hit_lift = round(chosen_metrics["hit_rate"] - baseline_metrics["hit_rate"], 2)
        enough_validation = chosen_metrics["filled"] >= min_validation_fills
        changed = selected_candidate["profile"] != "baseline" or selected_candidate["setup"] != "close"
        window_count = min(3, len(validation_dates))
        window_size = math.ceil(len(validation_dates) / window_count)
        ordered_validation_dates = sorted(validation_dates)
        stability_windows = []
        for start in range(0, len(ordered_validation_dates), window_size):
            window_dates = set(ordered_validation_dates[start : start + window_size])
            chosen_window = _execution_metrics(
                [row for row in selected_validation if str(row["date"]) in window_dates],
                selected_candidate["setup"],
            )
            baseline_window = _execution_metrics(
                [row for row in baseline_validation if str(row["date"]) in window_dates],
                "close",
            )
            stable_win = (
                chosen_window["hit_rate"] is not None
                and baseline_window["hit_rate"] is not None
                and chosen_window["avg_excess_return"] is not None
                and baseline_window["avg_excess_return"] is not None
                and chosen_window["hit_rate"] > baseline_window["hit_rate"]
                and chosen_window["avg_excess_return"] > baseline_window["avg_excess_return"]
            )
            stability_windows.append(
                {
                    "start": min(window_dates),
                    "end": max(window_dates),
                    "stable_win": stable_win,
                    "metrics": chosen_window,
                    "baseline_metrics": baseline_window,
                }
            )
        stable_win_windows = sum(window["stable_win"] for window in stability_windows)
        required_stable_windows = math.ceil(len(stability_windows) * 2 / 3)
        regime_validation_metrics = {
            regime: _execution_metrics(
                [row for row in selected_validation if row.get("market_regime") == regime],
                selected_candidate["setup"],
            )
            for regime in ("bull", "sideways", "bear")
        }
        cost_stress = evaluate_execution_cost_stress(
            selected_validation,
            setup=selected_candidate["setup"],
        )
        deployment_eligible = (
            changed
            and enough_validation
            and hit_lift is not None
            and hit_lift >= 3
            and (chosen_metrics["avg_excess_return"] or 0) > (baseline_metrics["avg_excess_return"] or 0)
            and stable_win_windows >= required_stable_windows
        )
        board_results[board] = {
            "status": "eligible_for_review" if deployment_eligible else ("no_stable_improvement" if enough_validation else "collecting"),
            "deployment_eligible": deployment_eligible,
            "sample_dates": len(dates),
            "train_end": dates[train_days - 1],
            "validation_start": dates[train_days],
            "selected_profile": selected_candidate["profile"],
            "selected_setup": selected_candidate["setup"],
            "training_candidates": candidates,
            "validation_metrics": chosen_metrics,
            "baseline_validation_metrics": baseline_metrics,
            "hit_rate_lift": hit_lift,
            "stability_windows": stability_windows,
            "stable_win_windows": stable_win_windows,
            "required_stable_windows": required_stable_windows,
            "regime_validation_metrics": regime_validation_metrics,
            "cost_stress": cost_stress,
            "blockers": [] if deployment_eligible else (["validation_fills_below_minimum"] if not enough_validation else ["promotion_thresholds_not_met"]),
        }
    return {
        "status": "eligible_for_review" if any(row["deployment_eligible"] for row in board_results.values()) else "no_board_ready",
        "deployment_eligible": False,
        "mode": "research_only",
        "candidate_count_per_board": len(_GATE_PROFILES) * len(setups),
        "boards": board_results,
    }


def assess_board_profile_consensus(
    runs: list[dict], *, min_matching_runs: int = 2, min_total_fills: int = 60
) -> dict:
    """Require the same board scheme to clear independent sample runs before review."""
    scheme_counts: dict[tuple[str, str], int] = {}
    for run in runs:
        scheme = (str(run.get("selected_profile") or ""), str(run.get("selected_setup") or ""))
        scheme_counts[scheme] = scheme_counts.get(scheme, 0) + 1
    consensus = max(scheme_counts, key=lambda scheme: (scheme_counts[scheme], scheme), default=("", ""))
    matching = [
        run
        for run in runs
        if (run.get("selected_profile"), run.get("selected_setup")) == consensus
    ]
    fills = [int((run.get("validation_metrics") or {}).get("filled") or 0) for run in matching]
    total_fills = sum(fills)
    weighted_hit_lift = (
        round(sum(float(run.get("hit_rate_lift") or 0) * fill for run, fill in zip(matching, fills)) / total_fills, 2)
        if total_fills else None
    )
    return_lifts = [
        float((run.get("validation_metrics") or {}).get("avg_excess_return") or 0)
        - float((run.get("baseline_validation_metrics") or {}).get("avg_excess_return") or 0)
        for run in matching
    ]
    weighted_return_lift = (
        round(sum(lift * fill for lift, fill in zip(return_lifts, fills)) / total_fills, 4)
        if total_fills else None
    )
    blockers = []
    if len(matching) < min_matching_runs:
        blockers.append(f"matching_runs_below_{min_matching_runs}")
    if total_fills < min_total_fills:
        blockers.append(f"validation_fills_below_{min_total_fills}")
    if any(not run.get("deployment_eligible") for run in matching):
        blockers.append("matching_run_not_individually_eligible")
    if weighted_hit_lift is None or weighted_hit_lift < 3:
        blockers.append("weighted_hit_rate_lift_below_3pct")
    if weighted_return_lift is None or weighted_return_lift <= 0:
        blockers.append("weighted_net_excess_not_improved")
    return {
        "consensus_profile": consensus[0] or None,
        "consensus_setup": consensus[1] or None,
        "matching_runs": len(matching),
        "total_runs": len(runs),
        "total_validation_fills": total_fills,
        "weighted_hit_rate_lift": weighted_hit_lift,
        "weighted_avg_excess_return_lift": weighted_return_lift,
        "eligible_for_review": not blockers,
        "blockers": blockers,
    }


def evaluate_rolling_segment_profiles(
    samples: list[dict],
    *,
    segment: str,
    train_days: int = 240,
    validation_days: int = 120,
    top_n: int = 5,
    min_train_fills: int = 30,
    min_validation_fills: int = 30,
    setups: tuple[str, ...] = ("close", "pullback", "breakout", "auto"),
) -> dict:
    """Repeated expanding-window selection with untouched forward validation blocks."""
    segment_samples = [row for row in samples if row.get("market_board") == segment]
    dates = sorted({str(row["date"]) for row in segment_samples})
    windows = []
    for validation_index in range(train_days, len(dates), validation_days):
        validation_end_index = min(len(dates), validation_index + validation_days)
        if validation_end_index - validation_index < max(2, validation_days // 2):
            break
        included_dates = set(dates[:validation_end_index])
        window_result = evaluate_board_specific_profiles(
            [row for row in segment_samples if str(row["date"]) in included_dates],
            train_days=validation_index,
            top_n=top_n,
            min_train_fills=min_train_fills,
            min_validation_fills=min_validation_fills,
            setups=setups,
            segments=(segment,),
        )["boards"][segment]
        validation_dates = set(dates[validation_index:validation_end_index])
        regime_counts = {
            regime: sum(
                1
                for row in segment_samples
                if str(row["date"]) in validation_dates and row.get("market_regime") == regime
            )
            for regime in ("bull", "sideways", "bear")
        }
        metrics = window_result["validation_metrics"]
        baseline = window_result["baseline_validation_metrics"]
        stress = window_result["cost_stress"]["0.25"]
        passed = (
            metrics["filled"] >= min_validation_fills
            and (window_result.get("hit_rate_lift") or 0) >= 3
            and (metrics.get("avg_excess_return") or 0) > (baseline.get("avg_excess_return") or 0)
            and (stress.get("avg_excess_return") or 0) > 0
        )
        windows.append(
            {
                "train_end": dates[validation_index - 1],
                "validation_start": dates[validation_index],
                "validation_end": dates[validation_end_index - 1],
                "selected_profile": window_result.get("selected_profile"),
                "selected_setup": window_result.get("selected_setup"),
                "dominant_regime": max(regime_counts, key=regime_counts.get),
                "regime_counts": regime_counts,
                "validation_metrics": metrics,
                "baseline_validation_metrics": baseline,
                "hit_rate_lift": window_result.get("hit_rate_lift"),
                "cost_stress_0_40": stress,
                "passed": passed,
            }
        )
    scheme_counts: dict[tuple[str, str], int] = {}
    for window in windows:
        scheme = (str(window["selected_profile"]), str(window["selected_setup"]))
        scheme_counts[scheme] = scheme_counts.get(scheme, 0) + 1
    consensus = max(scheme_counts, key=lambda key: (scheme_counts[key], key), default=("", ""))
    passed_windows = sum(window["passed"] for window in windows)
    required_windows = math.ceil(len(windows) * 2 / 3) if windows else 0
    matching_windows = scheme_counts.get(consensus, 0)
    eligible_for_review = (
        len(windows) >= 3
        and passed_windows >= required_windows
        and matching_windows >= required_windows
    )
    return {
        "segment": segment,
        "window_count": len(windows),
        "passed_windows": passed_windows,
        "required_windows": required_windows,
        "consensus_profile": consensus[0] or None,
        "consensus_setup": consensus[1] or None,
        "matching_windows": matching_windows,
        "eligible_for_review": eligible_for_review,
        "deployment_eligible": False,
        "windows": windows,
        "caliber": "expanding_train_forward_validation_total_cost_0_40",
    }


def evaluate_regime_switching_profiles(
    samples: list[dict],
    *,
    segment: str,
    train_days: int = 240,
    top_n: int = 5,
    min_train_fills_per_regime: int = 30,
    min_validation_fills: int = 30,
    setups: tuple[str, ...] = ("close", "pullback", "breakout", "auto"),
) -> dict:
    """Select a segment scheme and its enabled regimes using training dates only."""
    segment_samples = [row for row in samples if row.get("market_board") == segment]
    dates = sorted({str(row["date"]) for row in segment_samples})
    if len(dates) <= train_days:
        return {
            "status": "collecting",
            "segment": segment,
            "deployment_eligible": False,
            "sample_dates": len(dates),
            "blockers": ["insufficient_dates"],
        }

    profile_result = evaluate_board_specific_profiles(
        segment_samples,
        train_days=train_days,
        top_n=top_n,
        min_train_fills=min_train_fills_per_regime,
        min_validation_fills=min_validation_fills,
        setups=setups,
        segments=(segment,),
    )["boards"][segment]
    selected_profile = next(
        profile for profile in _GATE_PROFILES if profile["key"] == profile_result["selected_profile"]
    )
    train_dates = set(dates[:train_days])
    validation_dates = set(dates[train_days:])
    selected_train, _ = _gate_profile_rows(
        [row for row in segment_samples if str(row["date"]) in train_dates],
        selected_profile,
        top_n,
    )
    selected_validation, _ = _gate_profile_rows(
        [row for row in segment_samples if str(row["date"]) in validation_dates],
        selected_profile,
        top_n,
    )
    setup = str(profile_result["selected_setup"])
    training_by_regime = {
        regime: _execution_metrics(
            [row for row in selected_train if row.get("market_regime") == regime],
            setup,
        )
        for regime in ("bull", "sideways", "bear")
    }
    selected_regimes = [
        regime
        for regime, metrics in training_by_regime.items()
        if int(metrics.get("filled") or 0) >= min_train_fills_per_regime
        and (metrics.get("hit_rate") or 0) >= 50
        and (metrics.get("avg_excess_return") or 0) > 0
    ]
    switched_validation = [
        row for row in selected_validation if row.get("market_regime") in selected_regimes
    ]
    chosen_metrics = _execution_metrics(switched_validation, setup)
    baseline_metrics = _execution_metrics(selected_validation, setup)
    hit_lift = None
    if chosen_metrics["hit_rate"] is not None and baseline_metrics["hit_rate"] is not None:
        hit_lift = round(chosen_metrics["hit_rate"] - baseline_metrics["hit_rate"], 2)
    cost_stress = evaluate_execution_cost_stress(switched_validation, setup=setup)
    review_eligible = (
        bool(selected_regimes)
        and len(selected_regimes) < 3
        and chosen_metrics["filled"] >= min_validation_fills
        and hit_lift is not None
        and hit_lift >= 3
        and (chosen_metrics.get("avg_excess_return") or 0)
        > (baseline_metrics.get("avg_excess_return") or 0)
        and (cost_stress["0.25"].get("avg_excess_return") or 0) > 0
    )
    blockers = []
    if not selected_regimes:
        blockers.append("no_training_regime_passed")
    if chosen_metrics["filled"] < min_validation_fills:
        blockers.append("validation_fills_below_minimum")
    if not review_eligible and not blockers:
        blockers.append("promotion_thresholds_not_met")
    return {
        "status": "eligible_for_review" if review_eligible else "no_stable_improvement",
        "segment": segment,
        "deployment_eligible": False,
        "eligible_for_review": review_eligible,
        "train_end": dates[train_days - 1],
        "validation_start": dates[train_days],
        "selected_profile": selected_profile["key"],
        "selected_setup": setup,
        "selected_regimes": selected_regimes,
        "training_by_regime": training_by_regime,
        "validation_metrics": chosen_metrics,
        "baseline_validation_metrics": baseline_metrics,
        "hit_rate_lift": hit_lift,
        "cost_stress": cost_stress,
        "blockers": blockers,
        "caliber": "training_only_regime_gate_same_scheme_baseline_total_cost_0_40",
    }


def evaluate_rolling_regime_switching(
    samples: list[dict],
    *,
    segment: str,
    train_days: int = 240,
    validation_days: int = 120,
    top_n: int = 5,
    min_train_fills_per_regime: int = 30,
    min_validation_fills: int = 30,
    setups: tuple[str, ...] = ("close", "pullback", "breakout", "auto"),
) -> dict:
    """Repeat training-only regime selection across untouched forward windows."""
    segment_samples = [row for row in samples if row.get("market_board") == segment]
    dates = sorted({str(row["date"]) for row in segment_samples})
    windows = []
    for validation_index in range(train_days, len(dates), validation_days):
        validation_end_index = min(len(dates), validation_index + validation_days)
        if validation_end_index - validation_index < max(2, validation_days // 2):
            break
        included_dates = set(dates[:validation_end_index])
        result = evaluate_regime_switching_profiles(
            [row for row in segment_samples if str(row["date"]) in included_dates],
            segment=segment,
            train_days=validation_index,
            top_n=top_n,
            min_train_fills_per_regime=min_train_fills_per_regime,
            min_validation_fills=min_validation_fills,
            setups=setups,
        )
        windows.append(
            {
                "train_end": result.get("train_end"),
                "validation_start": result.get("validation_start"),
                "validation_end": dates[validation_end_index - 1],
                "selected_profile": result.get("selected_profile"),
                "selected_setup": result.get("selected_setup"),
                "selected_regimes": result.get("selected_regimes", []),
                "validation_metrics": result.get("validation_metrics"),
                "baseline_validation_metrics": result.get("baseline_validation_metrics"),
                "hit_rate_lift": result.get("hit_rate_lift"),
                "cost_stress_0_40": (result.get("cost_stress") or {}).get("0.25"),
                "passed": bool(result.get("eligible_for_review")),
                "blockers": result.get("blockers", []),
            }
        )
    passed_windows = sum(window["passed"] for window in windows)
    required_windows = math.ceil(len(windows) * 2 / 3) if windows else 0
    regime_counts: dict[tuple[str, ...], int] = {}
    for window in windows:
        key = tuple(window["selected_regimes"])
        regime_counts[key] = regime_counts.get(key, 0) + 1
    consensus = max(regime_counts, key=lambda key: (regime_counts[key], key), default=())
    matching_windows = regime_counts.get(consensus, 0)
    eligible_for_review = (
        len(windows) >= 3
        and passed_windows >= required_windows
        and matching_windows >= required_windows
        and bool(consensus)
    )
    return {
        "segment": segment,
        "window_count": len(windows),
        "passed_windows": passed_windows,
        "required_windows": required_windows,
        "consensus_regimes": list(consensus),
        "matching_windows": matching_windows,
        "eligible_for_review": eligible_for_review,
        "deployment_eligible": False,
        "windows": windows,
        "caliber": "rolling_training_only_regime_switch_total_cost_0_40",
    }


_LIQUIDITY_PROFILES = (
    {"key": "baseline"},
    {"key": "amount_ratio_1_0", "min_amount_ratio": 1.0},
    {"key": "amplitude_2_0", "max_amplitude_pct": 2.0},
    {
        "key": "amount_ratio_1_0_amplitude_2_0",
        "min_amount_ratio": 1.0,
        "max_amplitude_pct": 2.0,
    },
)

_HIGH_WIN_RATE_PROFILES = (
    {"key": "baseline"},
    {"key": "relative_strength_2_trend", "min_relative_strength_20d": 2.0, "require_trend_alignment": True},
    {"key": "relative_strength_trend", "min_relative_strength_20d": 0.0, "require_trend_alignment": True},
    {"key": "relative_strength_positive", "min_relative_strength_20d": 0.0},
    {"key": "trend_alignment", "require_trend_alignment": True},
)


def _filter_execution_quality(rows: list[dict], profile: dict) -> list[dict]:
    selected = []
    for row in rows:
        features = row.get("point_in_time_features") or {}
        amount_ratio = features.get("amount_ratio_20")
        amplitude = features.get("amplitude_pct")
        if "min_amount_ratio" in profile and (
            amount_ratio is None or float(amount_ratio) < float(profile["min_amount_ratio"])
        ):
            continue
        if "max_amplitude_pct" in profile and (
            amplitude is None or float(amplitude) > float(profile["max_amplitude_pct"])
        ):
            continue
        selected.append(row)
    return selected


def evaluate_liquidity_profiles(
    samples: list[dict],
    *,
    segment: str,
    train_days: int = 240,
    top_n: int = 5,
    min_train_fills: int = 30,
    min_validation_fills: int = 30,
    setups: tuple[str, ...] = ("close", "pullback", "breakout", "auto"),
) -> dict:
    """Fit a small set of point-in-time ETF liquidity filters on training dates."""
    segment_samples = [row for row in samples if row.get("market_board") == segment]
    dates = sorted({str(row["date"]) for row in segment_samples})
    if len(dates) <= train_days:
        return {
            "status": "collecting",
            "segment": segment,
            "deployment_eligible": False,
            "sample_dates": len(dates),
            "blockers": ["insufficient_dates"],
        }
    scheme = evaluate_board_specific_profiles(
        segment_samples,
        train_days=train_days,
        top_n=top_n,
        min_train_fills=min_train_fills,
        min_validation_fills=min_validation_fills,
        setups=setups,
        segments=(segment,),
    )["boards"][segment]
    gate_profile = next(
        profile for profile in _GATE_PROFILES if profile["key"] == scheme["selected_profile"]
    )
    train_dates = set(dates[:train_days])
    validation_dates = set(dates[train_days:])
    train_rows, _ = _gate_profile_rows(
        [row for row in segment_samples if str(row["date"]) in train_dates], gate_profile, top_n
    )
    validation_rows, _ = _gate_profile_rows(
        [row for row in segment_samples if str(row["date"]) in validation_dates], gate_profile, top_n
    )
    setup = str(scheme["selected_setup"])
    training_candidates = [
        {
            "profile": profile["key"],
            "metrics": _execution_metrics(_filter_execution_quality(train_rows, profile), setup),
        }
        for profile in _LIQUIDITY_PROFILES
    ]
    eligible = [
        candidate
        for candidate in training_candidates
        if int(candidate["metrics"].get("filled") or 0) >= min_train_fills
    ]
    selected_candidate = max(
        eligible or [training_candidates[0]],
        key=lambda candidate: (
            candidate["metrics"]["hit_rate"] if candidate["metrics"]["hit_rate"] is not None else -1,
            candidate["metrics"]["avg_excess_return"]
            if candidate["metrics"]["avg_excess_return"] is not None else -999,
            -training_candidates.index(candidate),
        ),
    )
    liquidity_profile = next(
        profile for profile in _LIQUIDITY_PROFILES if profile["key"] == selected_candidate["profile"]
    )
    filtered_validation = _filter_execution_quality(validation_rows, liquidity_profile)
    chosen_metrics = _execution_metrics(filtered_validation, setup)
    baseline_metrics = _execution_metrics(validation_rows, setup)
    hit_lift = None
    if chosen_metrics["hit_rate"] is not None and baseline_metrics["hit_rate"] is not None:
        hit_lift = round(chosen_metrics["hit_rate"] - baseline_metrics["hit_rate"], 2)
    stress = evaluate_execution_cost_stress(filtered_validation, setup=setup)
    changed = liquidity_profile["key"] != "baseline"
    review_eligible = (
        changed
        and chosen_metrics["filled"] >= min_validation_fills
        and hit_lift is not None
        and hit_lift >= 3
        and (chosen_metrics.get("avg_excess_return") or 0)
        > (baseline_metrics.get("avg_excess_return") or 0)
        and (stress["0.25"].get("avg_excess_return") or 0) > 0
    )
    return {
        "status": "eligible_for_review" if review_eligible else "no_stable_improvement",
        "segment": segment,
        "deployment_eligible": False,
        "eligible_for_review": review_eligible,
        "train_end": dates[train_days - 1],
        "validation_start": dates[train_days],
        "selected_profile": gate_profile["key"],
        "selected_setup": setup,
        "selected_liquidity_profile": liquidity_profile["key"],
        "training_candidates": training_candidates,
        "validation_metrics": chosen_metrics,
        "baseline_validation_metrics": baseline_metrics,
        "hit_rate_lift": hit_lift,
        "cost_stress": stress,
        "caliber": "training_only_relative_amount_amplitude_same_scheme_total_cost_0_40",
    }


def evaluate_rolling_liquidity_profiles(
    samples: list[dict],
    *,
    segment: str,
    train_days: int = 240,
    validation_days: int = 120,
    top_n: int = 5,
    min_train_fills: int = 30,
    min_validation_fills: int = 30,
    setups: tuple[str, ...] = ("close", "pullback", "breakout", "auto"),
) -> dict:
    """Repeat training-only ETF liquidity selection across forward windows."""
    segment_samples = [row for row in samples if row.get("market_board") == segment]
    dates = sorted({str(row["date"]) for row in segment_samples})
    windows = []
    for validation_index in range(train_days, len(dates), validation_days):
        validation_end_index = min(len(dates), validation_index + validation_days)
        if validation_end_index - validation_index < max(2, validation_days // 2):
            break
        included_dates = set(dates[:validation_end_index])
        result = evaluate_liquidity_profiles(
            [row for row in segment_samples if str(row["date"]) in included_dates],
            segment=segment,
            train_days=validation_index,
            top_n=top_n,
            min_train_fills=min_train_fills,
            min_validation_fills=min_validation_fills,
            setups=setups,
        )
        windows.append(
            {
                "train_end": result.get("train_end"),
                "validation_start": result.get("validation_start"),
                "validation_end": dates[validation_end_index - 1],
                "selected_profile": result.get("selected_profile"),
                "selected_setup": result.get("selected_setup"),
                "selected_liquidity_profile": result.get("selected_liquidity_profile"),
                "validation_metrics": result.get("validation_metrics"),
                "baseline_validation_metrics": result.get("baseline_validation_metrics"),
                "hit_rate_lift": result.get("hit_rate_lift"),
                "cost_stress_0_40": (result.get("cost_stress") or {}).get("0.25"),
                "passed": bool(result.get("eligible_for_review")),
            }
        )
    profile_counts: dict[str, int] = {}
    for window in windows:
        profile = str(window.get("selected_liquidity_profile") or "")
        profile_counts[profile] = profile_counts.get(profile, 0) + 1
    consensus = max(profile_counts, key=lambda key: (profile_counts[key], key), default="")
    passed_windows = sum(window["passed"] for window in windows)
    required_windows = math.ceil(len(windows) * 2 / 3) if windows else 0
    matching_windows = profile_counts.get(consensus, 0)
    eligible_for_review = (
        len(windows) >= 3
        and consensus not in ("", "baseline")
        and passed_windows >= required_windows
        and matching_windows >= required_windows
    )
    return {
        "segment": segment,
        "window_count": len(windows),
        "passed_windows": passed_windows,
        "required_windows": required_windows,
        "consensus_liquidity_profile": consensus or None,
        "matching_windows": matching_windows,
        "eligible_for_review": eligible_for_review,
        "deployment_eligible": False,
        "windows": windows,
        "caliber": "rolling_training_only_relative_amount_amplitude_total_cost_0_40",
    }


def _execution_window_metrics(
    samples: list[dict], *, setup: str, validity_days: int, extra_cost: float = 0.0
) -> dict:
    outcomes = [
        resolve_historical_execution_window(sample, setup, validity_days=validity_days)
        for sample in samples
    ]
    rejection_reasons: dict[str, int] = {}
    for row in outcomes:
        reason = row.get("reason")
        if reason:
            rejection_reasons[str(reason)] = rejection_reasons.get(str(reason), 0) + 1
    returns = [float(row["net_excess_return"]) - extra_cost for row in outcomes if row.get("net_excess_return") is not None]
    by_fill_day = {}
    for fill_day in range(1, validity_days + 1):
        day_returns = [
            float(row["net_excess_return"]) - extra_cost
            for row in outcomes
            if row.get("fill_day") == fill_day and row.get("net_excess_return") is not None
        ]
        by_fill_day[str(fill_day)] = {
            "filled": len(day_returns),
            "hit_rate": round(sum(value > 0 for value in day_returns) / len(day_returns) * 100, 2)
            if day_returns else None,
            "avg_excess_return": round(mean(day_returns), 4) if day_returns else None,
            "min_excess_return": round(min(day_returns), 4) if day_returns else None,
            "total_excess_return": round(sum(day_returns), 4) if day_returns else None,
        }
    return {
        "plans": len(outcomes),
        "filled": len(returns),
        "fill_rate": round(len(returns) / len(outcomes) * 100, 2) if outcomes else None,
        "hit_rate": round(sum(value > 0 for value in returns) / len(returns) * 100, 2)
        if returns else None,
        "avg_excess_return": round(mean(returns), 4) if returns else None,
        "avg_fill_day": round(
            mean(float(row["fill_day"]) for row in outcomes if row.get("fill_day") is not None), 2
        ) if returns else None,
        "by_fill_day": by_fill_day,
        "rejection_reasons": rejection_reasons,
    }


def _filter_high_win_rate(rows: list[dict], profile: dict) -> list[dict]:
    selected = []
    for row in rows:
        features = row.get("point_in_time_features") or {}
        relative_strength = features.get("relative_strength_20d_pct")
        if "min_relative_strength_20d" in profile and (
            relative_strength is None
            or float(relative_strength) <= float(profile["min_relative_strength_20d"])
        ):
            continue
        if profile.get("require_trend_alignment") and not bool(
            features.get("trend_alignment_5_20_60")
        ):
            continue
        selected.append(row)
    return selected


def evaluate_high_win_rate_profiles(
    samples: list[dict],
    *,
    segment: str,
    train_days: int = 240,
    top_n: int = 5,
    min_train_fills: int = 30,
    min_validation_fills: int = 30,
) -> dict:
    """Choose a point-in-time relative-strength filter on training dates only."""
    segment_samples = [row for row in samples if row.get("market_board") == segment]
    dates = sorted({str(row["date"]) for row in segment_samples})
    if len(dates) <= train_days:
        return {
            "status": "collecting",
            "segment": segment,
            "deployment_eligible": False,
            "sample_dates": len(dates),
            "blockers": ["insufficient_dates"],
        }
    train_dates = set(dates[:train_days])
    validation_dates = set(dates[train_days:])
    train_rows, _ = _gate_profile_rows(
        [row for row in segment_samples if str(row["date"]) in train_dates],
        _GATE_PROFILES[0],
        top_n,
    )
    validation_rows, _ = _gate_profile_rows(
        [row for row in segment_samples if str(row["date"]) in validation_dates],
        _GATE_PROFILES[0],
        top_n,
    )
    training_candidates = [
        {
            "profile": profile["key"],
            "metrics": _execution_window_metrics(
                _filter_high_win_rate(train_rows, profile),
                setup="pullback",
                validity_days=3,
            ),
        }
        for profile in _HIGH_WIN_RATE_PROFILES
    ]
    eligible = [
        candidate
        for candidate in training_candidates
        if int(candidate["metrics"].get("filled") or 0) >= min_train_fills
    ]
    selected_candidate = max(
        eligible or [training_candidates[0]],
        key=lambda candidate: (
            candidate["metrics"]["hit_rate"] if candidate["metrics"]["hit_rate"] is not None else -1,
            candidate["metrics"]["avg_excess_return"]
            if candidate["metrics"]["avg_excess_return"] is not None else -999,
            -training_candidates.index(candidate),
        ),
    )
    profile = next(
        row for row in _HIGH_WIN_RATE_PROFILES if row["key"] == selected_candidate["profile"]
    )
    chosen_rows = _filter_high_win_rate(validation_rows, profile)
    chosen_metrics = _execution_window_metrics(
        chosen_rows, setup="pullback", validity_days=3
    )
    baseline_metrics = _execution_window_metrics(
        validation_rows, setup="pullback", validity_days=3
    )
    stressed_metrics = _execution_window_metrics(
        chosen_rows, setup="pullback", validity_days=3, extra_cost=0.25
    )
    hit_lift = None
    if chosen_metrics["hit_rate"] is not None and baseline_metrics["hit_rate"] is not None:
        hit_lift = round(chosen_metrics["hit_rate"] - baseline_metrics["hit_rate"], 2)
    review_eligible = (
        profile["key"] != "baseline"
        and chosen_metrics["filled"] >= min_validation_fills
        and hit_lift is not None
        and hit_lift >= 3
        and (chosen_metrics.get("avg_excess_return") or 0)
        > (baseline_metrics.get("avg_excess_return") or 0)
        and (stressed_metrics.get("avg_excess_return") or 0) > 0
    )
    return {
        "status": "eligible_for_review" if review_eligible else "no_stable_improvement",
        "segment": segment,
        "deployment_eligible": False,
        "eligible_for_review": review_eligible,
        "train_end": dates[train_days - 1],
        "validation_start": dates[train_days],
        "selected_high_win_profile": profile["key"],
        "training_candidates": training_candidates,
        "validation_metrics": chosen_metrics,
        "baseline_validation_metrics": baseline_metrics,
        "cost_stress_0_40": stressed_metrics,
        "hit_rate_lift": hit_lift,
        "caliber": "training_only_relative_strength_trend_fixed_3_day_pullback",
    }


def evaluate_rolling_high_win_rate_profiles(
    samples: list[dict],
    *,
    segment: str,
    train_days: int = 240,
    validation_days: int = 120,
    top_n: int = 5,
    min_train_fills: int = 30,
    min_validation_fills: int = 30,
) -> dict:
    """Repeat high-win-rate profile selection across forward windows."""
    segment_samples = [row for row in samples if row.get("market_board") == segment]
    dates = sorted({str(row["date"]) for row in segment_samples})
    windows = []
    for validation_index in range(train_days, len(dates), validation_days):
        validation_end_index = min(len(dates), validation_index + validation_days)
        if validation_end_index - validation_index < max(2, validation_days // 2):
            break
        included_dates = set(dates[:validation_end_index])
        result = evaluate_high_win_rate_profiles(
            [row for row in segment_samples if str(row["date"]) in included_dates],
            segment=segment,
            train_days=validation_index,
            top_n=top_n,
            min_train_fills=min_train_fills,
            min_validation_fills=min_validation_fills,
        )
        windows.append(
            {
                "train_end": result.get("train_end"),
                "validation_start": result.get("validation_start"),
                "validation_end": dates[validation_end_index - 1],
                "selected_high_win_profile": result.get("selected_high_win_profile"),
                "validation_metrics": result.get("validation_metrics"),
                "baseline_validation_metrics": result.get("baseline_validation_metrics"),
                "hit_rate_lift": result.get("hit_rate_lift"),
                "cost_stress_0_40": result.get("cost_stress_0_40"),
                "passed": bool(result.get("eligible_for_review")),
            }
        )
    profile_counts: dict[str, int] = {}
    for window in windows:
        profile = str(window.get("selected_high_win_profile") or "")
        profile_counts[profile] = profile_counts.get(profile, 0) + 1
    consensus = max(profile_counts, key=lambda key: (profile_counts[key], key), default="")
    passed_windows = sum(window["passed"] for window in windows)
    required_windows = math.ceil(len(windows) * 2 / 3) if windows else 0
    matching_windows = profile_counts.get(consensus, 0)
    eligible_for_review = (
        len(windows) >= 3
        and consensus not in ("", "baseline")
        and passed_windows >= required_windows
        and matching_windows >= required_windows
    )
    return {
        "segment": segment,
        "window_count": len(windows),
        "passed_windows": passed_windows,
        "required_windows": required_windows,
        "consensus_high_win_profile": consensus or None,
        "matching_windows": matching_windows,
        "eligible_for_review": eligible_for_review,
        "deployment_eligible": False,
        "windows": windows,
        "caliber": "rolling_training_only_relative_strength_trend_fixed_3_day_pullback",
    }


def evaluate_order_validity_profiles(
    samples: list[dict],
    *,
    segment: str,
    train_days: int = 240,
    top_n: int = 5,
    min_train_fills: int = 30,
    min_validation_fills: int = 30,
) -> dict:
    """Select a 1/2/3-day pullback order lifetime using training dates only."""
    segment_samples = [row for row in samples if row.get("market_board") == segment]
    dates = sorted({str(row["date"]) for row in segment_samples})
    if len(dates) <= train_days:
        return {
            "status": "collecting",
            "segment": segment,
            "deployment_eligible": False,
            "sample_dates": len(dates),
            "blockers": ["insufficient_dates"],
        }
    scheme = evaluate_board_specific_profiles(
        segment_samples,
        train_days=train_days,
        top_n=top_n,
        min_train_fills=min_train_fills,
        min_validation_fills=min_validation_fills,
        setups=("pullback",),
        segments=(segment,),
    )["boards"][segment]
    gate_profile = next(
        profile for profile in _GATE_PROFILES if profile["key"] == scheme["selected_profile"]
    )
    train_dates = set(dates[:train_days])
    validation_dates = set(dates[train_days:])
    train_rows, _ = _gate_profile_rows(
        [row for row in segment_samples if str(row["date"]) in train_dates], gate_profile, top_n
    )
    validation_rows, _ = _gate_profile_rows(
        [row for row in segment_samples if str(row["date"]) in validation_dates], gate_profile, top_n
    )
    training_candidates = {
        validity: _execution_window_metrics(train_rows, setup="pullback", validity_days=validity)
        for validity in (1, 2, 3)
    }
    eligible = [
        validity
        for validity, metrics in training_candidates.items()
        if int(metrics.get("filled") or 0) >= min_train_fills
    ]
    selected_validity = max(
        eligible or [1],
        key=lambda validity: (
            training_candidates[validity]["hit_rate"]
            if training_candidates[validity]["hit_rate"] is not None else -1,
            training_candidates[validity]["avg_excess_return"]
            if training_candidates[validity]["avg_excess_return"] is not None else -999,
            -validity,
        ),
    )
    chosen = _execution_window_metrics(
        validation_rows, setup="pullback", validity_days=selected_validity
    )
    baseline = _execution_window_metrics(validation_rows, setup="pullback", validity_days=1)
    stressed = _execution_window_metrics(
        validation_rows, setup="pullback", validity_days=selected_validity, extra_cost=0.25
    )
    hit_lift = None
    if chosen["hit_rate"] is not None and baseline["hit_rate"] is not None:
        hit_lift = round(chosen["hit_rate"] - baseline["hit_rate"], 2)
    review_eligible = (
        selected_validity > 1
        and chosen["filled"] >= min_validation_fills
        and hit_lift is not None
        and hit_lift >= 3
        and (chosen.get("avg_excess_return") or 0) > (baseline.get("avg_excess_return") or 0)
        and (stressed.get("avg_excess_return") or 0) > 0
    )
    return {
        "status": "eligible_for_review" if review_eligible else "no_stable_improvement",
        "segment": segment,
        "deployment_eligible": False,
        "eligible_for_review": review_eligible,
        "train_end": dates[train_days - 1],
        "validation_start": dates[train_days],
        "selected_profile": gate_profile["key"],
        "selected_setup": "pullback",
        "selected_validity_days": selected_validity,
        "training_candidates": training_candidates,
        "validation_metrics": chosen,
        "baseline_validation_metrics": baseline,
        "hit_rate_lift": hit_lift,
        "cost_stress_0_40": stressed,
        "caliber": "first_trigger_same_day_close_cumulative_benchmark_total_cost_0_40",
    }


def evaluate_rolling_order_validity(
    samples: list[dict],
    *,
    segment: str,
    train_days: int = 240,
    validation_days: int = 120,
    top_n: int = 5,
    min_train_fills: int = 30,
    min_validation_fills: int = 30,
) -> dict:
    """Repeat training-only order-validity selection across forward windows."""
    segment_samples = [row for row in samples if row.get("market_board") == segment]
    dates = sorted({str(row["date"]) for row in segment_samples})
    windows = []
    for validation_index in range(train_days, len(dates), validation_days):
        validation_end_index = min(len(dates), validation_index + validation_days)
        if validation_end_index - validation_index < max(2, validation_days // 2):
            break
        included_dates = set(dates[:validation_end_index])
        result = evaluate_order_validity_profiles(
            [row for row in segment_samples if str(row["date"]) in included_dates],
            segment=segment,
            train_days=validation_index,
            top_n=top_n,
            min_train_fills=min_train_fills,
            min_validation_fills=min_validation_fills,
        )
        windows.append(
            {
                "train_end": result.get("train_end"),
                "validation_start": result.get("validation_start"),
                "validation_end": dates[validation_end_index - 1],
                "selected_profile": result.get("selected_profile"),
                "selected_validity_days": result.get("selected_validity_days"),
                "validation_metrics": result.get("validation_metrics"),
                "baseline_validation_metrics": result.get("baseline_validation_metrics"),
                "hit_rate_lift": result.get("hit_rate_lift"),
                "cost_stress_0_40": result.get("cost_stress_0_40"),
                "passed": bool(result.get("eligible_for_review")),
            }
        )
    validity_counts: dict[int, int] = {}
    for window in windows:
        validity = int(window.get("selected_validity_days") or 1)
        validity_counts[validity] = validity_counts.get(validity, 0) + 1
    consensus = max(validity_counts, key=lambda key: (validity_counts[key], -key), default=1)
    passed_windows = sum(window["passed"] for window in windows)
    required_windows = math.ceil(len(windows) * 2 / 3) if windows else 0
    matching_windows = validity_counts.get(consensus, 0)
    eligible_for_review = (
        len(windows) >= 3
        and consensus > 1
        and passed_windows >= required_windows
        and matching_windows >= required_windows
    )
    return {
        "segment": segment,
        "window_count": len(windows),
        "passed_windows": passed_windows,
        "required_windows": required_windows,
        "consensus_validity_days": consensus,
        "matching_windows": matching_windows,
        "eligible_for_review": eligible_for_review,
        "deployment_eligible": False,
        "windows": windows,
        "caliber": "rolling_first_trigger_order_validity_total_cost_0_40",
    }


def evaluate_market_regime_filter(
    samples: list[dict], *, train_days: int = 80, top_n: int = 10, min_train_selections: int = 30
) -> dict:
    dates = sorted({str(sample["date"]) for sample in samples})
    if len(dates) <= train_days:
        return {"status": "insufficient_dates", "deployment_eligible": False}
    selected, _ = _gate_profile_rows(samples, _GATE_PROFILES[0], top_n)
    train = [row for row in selected if str(row["date"]) <= dates[train_days - 1]]
    validation = [row for row in selected if str(row["date"]) >= dates[train_days]]
    train_by_regime = {
        regime: _return_metrics([row for row in train if row.get("market_regime") == regime])
        for regime in ("bull", "sideways", "bear")
    }
    selected_regimes = [
        regime for regime, metrics in train_by_regime.items()
        if metrics["selections"] >= min_train_selections
        and (metrics["hit_rate"] or 0) >= 50
        and (metrics["avg_excess_return"] or 0) > 0
    ]
    filtered = [row for row in validation if row.get("market_regime") in selected_regimes]
    filtered_metrics = _return_metrics(filtered)
    baseline_metrics = _return_metrics(validation)
    lift = None if filtered_metrics["hit_rate"] is None or baseline_metrics["hit_rate"] is None else round(filtered_metrics["hit_rate"] - baseline_metrics["hit_rate"], 2)
    eligible = bool(selected_regimes) and filtered_metrics["selections"] >= 30 and lift is not None and lift >= 3 and (filtered_metrics["avg_excess_return"] or 0) > (baseline_metrics["avg_excess_return"] or 0)
    return {
        "status": "eligible_for_review" if eligible else "no_stable_improvement",
        "deployment_eligible": eligible,
        "train_end": dates[train_days - 1],
        "validation_start": dates[train_days],
        "selected_regimes": selected_regimes,
        "training_by_regime": train_by_regime,
        "validation_metrics": filtered_metrics,
        "baseline_validation_metrics": baseline_metrics,
        "hit_rate_lift": lift,
        "recommendation_retention_pct": round(len(filtered) / len(validation) * 100, 2) if validation else None,
    }


def evaluate_holding_periods(
    samples: list[dict], *, train_days: int = 80, top_n: int = 10, min_train_selections: int = 30
) -> dict:
    dates = sorted({str(row["date"]) for row in samples})
    if len(dates) <= train_days:
        return {"status": "insufficient_dates", "deployment_eligible": False}
    selected, _ = _gate_profile_rows(samples, _GATE_PROFILES[0], top_n)
    train = [row for row in selected if str(row["date"]) <= dates[train_days - 1]]
    validation = [row for row in selected if str(row["date"]) >= dates[train_days]]

    def metrics(rows: list[dict], horizon: int) -> dict:
        values = [float(row["holding_excess_returns"][str(horizon)]) for row in rows if str(horizon) in (row.get("holding_excess_returns") or {})]
        return {"selections": len(values), "hit_rate": round(sum(v > 0 for v in values) / len(values) * 100, 2) if values else None, "avg_excess_return": round(mean(values), 4) if values else None}

    training = {h: metrics(train, h) for h in (1, 3, 5)}
    eligible_horizons = [h for h, value in training.items() if value["selections"] >= min_train_selections]
    selected_horizon = max(eligible_horizons or [1], key=lambda h: ((training[h]["hit_rate"] or -1), (training[h]["avg_excess_return"] or -999), -h))
    chosen = metrics(validation, selected_horizon)
    baseline = metrics(validation, 1)
    lift = None if chosen["hit_rate"] is None or baseline["hit_rate"] is None else round(chosen["hit_rate"] - baseline["hit_rate"], 2)
    deployable = selected_horizon != 1 and chosen["selections"] >= 30 and lift is not None and lift >= 3 and (chosen["avg_excess_return"] or 0) > (baseline["avg_excess_return"] or 0)
    return {"status": "eligible_for_review" if deployable else "no_stable_improvement", "deployment_eligible": deployable, "selected_horizon": selected_horizon, "train_end": dates[train_days - 1], "validation_start": dates[train_days], "training_horizons": training, "validation_metrics": chosen, "baseline_validation_metrics": baseline, "hit_rate_lift": lift, "caliber": "per_signal_close_to_close_not_capital_constrained"}


def volatility_weight_multiplier(volatility: float | None, target_volatility: float | None) -> float:
    if not target_volatility or not volatility or volatility <= 0:
        return 1.0
    return round(min(1.0, target_volatility / volatility), 6)


def simulate_capacity_constrained(samples: list[dict], *, horizon: int, max_positions: int = 10, top_n: int = 10, target_volatility: float | None = None, max_per_board: int | None = None) -> dict:
    selected, _ = _gate_profile_rows(samples, _GATE_PROFILES[0], top_n)
    by_date: dict[str, list[dict]] = {}
    for row in selected:
        if str(horizon) in (row.get("holding_excess_returns") or {}) and str(horizon) in (row.get("holding_outcome_dates") or {}):
            by_date.setdefault(str(row["date"]), []).append(row)
    active: list[dict] = []
    realized: list[float] = []
    weighted_total = 0.0
    skipped = 0
    skipped_board = 0
    equity = peak = 1.0
    max_drawdown = 0.0
    for day in sorted(by_date):
        closing = [position for position in active if position["exit_date"] <= day]
        for position in closing:
            value = position["return"] * position["weight"]
            realized.append(position["return"])
            weighted_total += value
            equity += value / 100
            peak = max(peak, equity)
            max_drawdown = min(max_drawdown, (equity / peak - 1) * 100)
        active = [position for position in active if position["exit_date"] > day]
        rows = sorted(by_date[day], key=lambda row: (-float(row["strategy_scores"].get("momentum") or 0), str(row["code"])))
        capacity = max(0, max_positions - len(active))
        opened = 0
        for row in rows:
            if opened >= capacity:
                skipped += 1
                continue
            board = row.get("market_board") or market_board(str(row["code"]))
            if max_per_board is not None and sum(position.get("board") == board for position in active) >= max_per_board:
                skipped_board += 1
                continue
            multiplier = volatility_weight_multiplier(row.get("historical_volatility"), target_volatility)
            active.append({"exit_date": row["holding_outcome_dates"][str(horizon)], "return": float(row["holding_excess_returns"][str(horizon)]), "weight": multiplier / max_positions, "board": board})
            opened += 1
    for position in active:
        realized.append(position["return"])
        value = position["return"] * position["weight"]
        weighted_total += value
        equity += value / 100
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, (equity / peak - 1) * 100)
    return {"trades": len(realized), "skipped_for_capacity": skipped, "skipped_for_board": skipped_board, "hit_rate": round(sum(v > 0 for v in realized) / len(realized) * 100, 2) if realized else None, "avg_excess_return": round(mean(realized), 4) if realized else None, "total_excess_return": round(weighted_total, 4), "max_realized_drawdown_pct": round(max_drawdown, 2), "max_positions": max_positions, "target_volatility": target_volatility, "max_per_board": max_per_board}


def evaluate_capacity_horizons(samples: list[dict], *, train_days: int = 80, top_n: int = 10, max_positions: int = 10) -> dict:
    dates = sorted({str(row["date"]) for row in samples})
    if len(dates) <= train_days:
        return {"status": "insufficient_dates", "deployment_eligible": False}
    train = [row for row in samples if str(row["date"]) <= dates[train_days - 1]]
    validation = [row for row in samples if str(row["date"]) >= dates[train_days]]
    training = {h: simulate_capacity_constrained(train, horizon=h, max_positions=max_positions, top_n=top_n) for h in (1, 3, 5)}
    selected_horizon = max(training, key=lambda h: (training[h]["total_excess_return"], training[h]["hit_rate"] or -1, -h))
    chosen = simulate_capacity_constrained(validation, horizon=selected_horizon, max_positions=max_positions, top_n=top_n)
    baseline = simulate_capacity_constrained(validation, horizon=1, max_positions=max_positions, top_n=top_n)
    eligible = selected_horizon != 1 and chosen["trades"] >= 30 and chosen["total_excess_return"] > baseline["total_excess_return"] and chosen["max_realized_drawdown_pct"] >= baseline["max_realized_drawdown_pct"]
    return {"status": "eligible_for_review" if eligible else "no_stable_improvement", "deployment_eligible": eligible, "selected_horizon": selected_horizon, "training_horizons": training, "validation_metrics": chosen, "baseline_validation_metrics": baseline, "caliber": "fixed_slots_realized_equity_no_daily_mark_to_market"}


def select_risk_budget(training: dict[int, dict], *, min_trades: int = 30) -> int:
    eligible = [slots for slots, result in training.items() if result["trades"] >= min_trades]
    return max(eligible or [10], key=lambda slots: (training[slots]["total_excess_return"] / max(0.01, abs(training[slots]["max_realized_drawdown_pct"])), training[slots]["total_excess_return"], -slots))


def evaluate_risk_budgets(samples: list[dict], *, train_days: int = 80, top_n: int = 10) -> dict:
    dates = sorted({str(row["date"]) for row in samples})
    if len(dates) <= train_days:
        return {"status": "insufficient_dates", "deployment_eligible": False}
    train = [row for row in samples if str(row["date"]) <= dates[train_days - 1]]
    validation = [row for row in samples if str(row["date"]) >= dates[train_days]]
    training = {slots: simulate_capacity_constrained(train, horizon=3, max_positions=slots, top_n=top_n) for slots in (5, 10, 15, 20)}
    selected_slots = select_risk_budget(training)
    chosen = simulate_capacity_constrained(validation, horizon=3, max_positions=selected_slots, top_n=top_n)
    baseline = simulate_capacity_constrained(validation, horizon=1, max_positions=10, top_n=top_n)
    eligible = chosen["trades"] >= 30 and chosen["total_excess_return"] > baseline["total_excess_return"] and chosen["max_realized_drawdown_pct"] >= baseline["max_realized_drawdown_pct"]
    return {"status": "eligible_for_review" if eligible else "no_stable_improvement", "deployment_eligible": eligible, "selected_max_positions": selected_slots, "training_budgets": training, "validation_metrics": chosen, "baseline_validation_metrics": baseline, "caliber": "t3_equal_weight_slot_budget_vs_t1_10_slots"}


def evaluate_volatility_budgets(samples: list[dict], *, train_days: int = 80, top_n: int = 10) -> dict:
    dates = sorted({str(row["date"]) for row in samples})
    if len(dates) <= train_days:
        return {"status": "insufficient_dates", "deployment_eligible": False}
    train = [row for row in samples if str(row["date"]) <= dates[train_days - 1]]
    validation = [row for row in samples if str(row["date"]) >= dates[train_days]]
    targets = (20.0, 30.0, 40.0)
    training = {target: simulate_capacity_constrained(train, horizon=3, max_positions=20, top_n=top_n, target_volatility=target) for target in targets}
    selected = max(targets, key=lambda target: (training[target]["total_excess_return"] / max(0.01, abs(training[target]["max_realized_drawdown_pct"])), training[target]["total_excess_return"], -target))
    chosen = simulate_capacity_constrained(validation, horizon=3, max_positions=20, top_n=top_n, target_volatility=selected)
    baseline = simulate_capacity_constrained(validation, horizon=1, max_positions=10, top_n=top_n)
    eligible = chosen["trades"] >= 30 and chosen["total_excess_return"] > baseline["total_excess_return"] and chosen["max_realized_drawdown_pct"] >= baseline["max_realized_drawdown_pct"]
    return {"status": "eligible_for_review" if eligible else "no_stable_improvement", "deployment_eligible": eligible, "selected_target_volatility": selected, "training_targets": training, "validation_metrics": chosen, "baseline_validation_metrics": baseline, "caliber": "t3_20_slots_downscale_only_no_leverage"}


def evaluate_board_budgets(samples: list[dict], *, train_days: int = 80, top_n: int = 10, max_positions: int = 20) -> dict:
    dates = sorted({str(row["date"]) for row in samples})
    if len(dates) <= train_days:
        return {"status": "insufficient_dates", "deployment_eligible": False}
    train = [row for row in samples if str(row["date"]) <= dates[train_days - 1]]
    validation = [row for row in samples if str(row["date"]) >= dates[train_days]]
    limits = tuple(sorted({max(1, max_positions // 4), max(1, max_positions // 2), max_positions}))
    training = {
        limit: simulate_capacity_constrained(
            train, horizon=3, max_positions=max_positions, top_n=top_n, max_per_board=limit
        )
        for limit in limits
    }
    selected = max(
        limits,
        key=lambda limit: (
            training[limit]["total_excess_return"] / max(0.01, abs(training[limit]["max_realized_drawdown_pct"])),
            training[limit]["total_excess_return"],
            limit,
        ),
    )
    chosen = simulate_capacity_constrained(
        validation, horizon=3, max_positions=max_positions, top_n=top_n, max_per_board=selected
    )
    unconstrained = simulate_capacity_constrained(
        validation, horizon=3, max_positions=max_positions, top_n=top_n
    )
    baseline = simulate_capacity_constrained(validation, horizon=1, max_positions=10, top_n=top_n)
    eligible = (
        selected < max_positions
        and chosen["trades"] >= 30
        and chosen["total_excess_return"] > baseline["total_excess_return"]
        and chosen["max_realized_drawdown_pct"] >= baseline["max_realized_drawdown_pct"]
        and chosen["total_excess_return"] >= unconstrained["total_excess_return"]
    )
    return {
        "status": "eligible_for_review" if eligible else "no_stable_improvement",
        "deployment_eligible": eligible,
        "selected_max_per_board": selected,
        "training_budgets": training,
        "validation_metrics": chosen,
        "unconstrained_validation_metrics": unconstrained,
        "baseline_validation_metrics": baseline,
        "caliber": "code_stable_main_chinext_star_board_cap_t3_vs_unconstrained_and_t1",
    }


def evaluate_rolling_stability(
    samples: list[dict], *, train_days: int = 80, window_days: int = 60, top_n: int = 10, max_positions: int = 20
) -> dict:
    dates = sorted({str(row["date"]) for row in samples})
    if len(dates) <= train_days:
        return {"status": "insufficient_dates", "deployment_eligible": False, "window_count": 0, "windows": []}
    validation_dates = dates[train_days:]
    windows = []
    for offset in range(0, len(validation_dates), window_days):
        period = validation_dates[offset : offset + window_days]
        if not period:
            continue
        rows = [row for row in samples if period[0] <= str(row["date"]) <= period[-1]]
        candidate = simulate_capacity_constrained(rows, horizon=3, max_positions=max_positions, top_n=top_n)
        baseline = simulate_capacity_constrained(rows, horizon=1, max_positions=10, top_n=top_n)
        windows.append(
            {
                "start": period[0],
                "end": period[-1],
                "trading_days": len(period),
                "candidate": candidate,
                "baseline": baseline,
                "return_win": candidate["total_excess_return"] > baseline["total_excess_return"],
                "drawdown_win": candidate["max_realized_drawdown_pct"] >= baseline["max_realized_drawdown_pct"],
            }
        )
    return_wins = sum(window["return_win"] for window in windows)
    drawdown_wins = sum(window["drawdown_win"] for window in windows)
    required_wins = (len(windows) * 2 + 2) // 3
    eligible = len(windows) >= 3 and return_wins >= required_wins and drawdown_wins >= required_wins
    return {
        "status": "eligible_for_review" if eligible else "no_stable_improvement",
        "deployment_eligible": eligible,
        "window_count": len(windows),
        "required_win_windows": required_wins,
        "return_win_windows": return_wins,
        "drawdown_win_windows": drawdown_wins,
        "windows": windows,
        "caliber": "fixed_t3_20_slots_vs_t1_10_slots_disjoint_validation_windows",
    }


def evaluate_transaction_cost_sensitivity(
    samples: list[dict], *, horizon: int = 1, costs: tuple[float, ...] = (0.15, 0.30, 0.50), top_n: int = 10
) -> dict:
    selected, _ = _gate_profile_rows(samples, _GATE_PROFILES[0], top_n)
    stored = [
        float(row["holding_excess_returns"][str(horizon)])
        for row in selected
        if str(horizon) in (row.get("holding_excess_returns") or {})
    ]
    scenarios = {}
    for cost in costs:
        repriced = [value - (cost - BASE_TRANSACTION_COST_PCT) for value in stored]
        scenarios[f"{cost:.2f}"] = {
            "selections": len(repriced),
            "hit_rate": round(sum(value > 0 for value in repriced) / len(repriced) * 100, 2) if repriced else None,
            "avg_excess_return": round(mean(repriced), 4) if repriced else None,
        }
    worst = scenarios[f"{max(costs):.2f}"] if costs else {"selections": 0, "hit_rate": None, "avg_excess_return": None}
    resilient = worst["selections"] >= 30 and (worst["hit_rate"] or 0) >= 50 and (worst["avg_excess_return"] or 0) > 0
    return {
        "status": "cost_resilient" if resilient else "cost_sensitive",
        "deployment_eligible": False,
        "base_cost_pct": BASE_TRANSACTION_COST_PCT,
        "horizon": horizon,
        "cost_scenarios": scenarios,
        "caliber": "close_to_close_excess_return_repriced_for_total_round_trip_cost",
    }


def evaluate_return_distribution(samples: list[dict], *, horizon: int = 1, top_n: int = 10) -> dict:
    selected, _ = _gate_profile_rows(samples, _GATE_PROFILES[0], top_n)
    values = [
        float(row["holding_excess_returns"][str(horizon)])
        for row in selected
        if str(horizon) in (row.get("holding_excess_returns") or {})
    ]
    if not values:
        return {"status": "no_samples", "selections": 0}
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value <= 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    top_count = max(1, math.ceil(len(values) * 0.1))
    top_profit = sum(sorted(wins, reverse=True)[:top_count])
    return {
        "status": "diagnostic_only",
        "deployment_eligible": False,
        "selections": len(values),
        "hit_rate": round(len(wins) / len(values) * 100, 2),
        "avg_excess_return": round(mean(values), 4),
        "median_excess_return": round(median(values), 4),
        "avg_win": round(mean(wins), 4) if wins else None,
        "avg_loss": round(mean(losses), 4) if losses else None,
        "payoff_ratio": round(mean(wins) / abs(mean(losses)), 3) if wins and losses and mean(losses) else None,
        "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss else None,
        "top_decile_profit_share_pct": round(top_profit / gross_profit * 100, 2) if gross_profit else None,
        "caliber": "baseline_gate_close_to_close_net_excess_distribution",
    }


_GATE_PROFILES = (
    {"key": "baseline", "trend_key": "trend", "trend_min": 3.5},
    {"key": "progressive_strict", "trend_key": "trend_progressive", "trend_min": 8.0},
    {"key": "progressive_balanced", "trend_key": "trend_progressive", "trend_min": 6.0},
    {"key": "progressive_loose", "trend_key": "trend_progressive", "trend_min": 5.0},
)

_LOSS_REJECTION_PROFILES = (
    {"key": "baseline"},
    {"key": "volatility_22", "volatility_max": 22.0},
    {"key": "volatility_30", "volatility_max": 30.0},
    {"key": "strong_signal", "strength_min": 8.0},
    {"key": "volatility_30_strong_signal", "volatility_max": 30.0, "strength_min": 8.0},
    {"key": "ma20_extension_5", "ma20_distance_max": 5.0},
    {"key": "gap_2", "gap_abs_max": 2.0},
    {"key": "runup_3", "consecutive_up_max": 3},
    {"key": "no_bearish_volume_divergence", "reject_bearish_volume_divergence": True},
    {
        "key": "balanced_price_action",
        "ma20_distance_max": 8.0,
        "gap_abs_max": 3.0,
        "consecutive_up_max": 4,
        "reject_bearish_volume_divergence": True,
    },
)


def _gate_profile_rows(samples: list[dict], profile: dict, top_n: int) -> tuple[list[dict], dict]:
    by_date: dict[str, list[tuple[float, dict]]] = {}
    for sample in samples:
        scores = sample.get("strategy_scores") or {}
        momentum = float(scores.get("momentum") or 0)
        trend = float(scores.get(profile["trend_key"]) or 0)
        if momentum < 4 or trend < profile["trend_min"]:
            continue
        score = momentum * 0.7 + trend * 0.3
        by_date.setdefault(str(sample["date"]), []).append((score, sample))
    selected: list[dict] = []
    for rows in by_date.values():
        rows.sort(key=lambda item: (-item[0], str(item[1].get("code") or "")))
        selected.extend(sample for _, sample in rows[:top_n])
    all_dates = {str(sample["date"]) for sample in samples}
    counts = {day: len(by_date.get(day, [])) for day in all_dates}
    coverage = {
        "candidate_days": sum(count > 0 for count in counts.values()),
        "empty_days": sum(count == 0 for count in counts.values()),
        "avg_candidates": round(mean(counts.values()), 2) if counts else 0.0,
    }
    return selected, coverage


def _return_metrics(samples: list[dict]) -> dict:
    values = [float(sample["excess_return"]) for sample in samples]
    return {
        "selections": len(values),
        "hit_rate": round(sum(value > 0 for value in values) / len(values) * 100, 2) if values else None,
        "avg_excess_return": round(mean(values), 4) if values else None,
    }


def _matches_loss_rejection_profile(sample: dict, profile: dict) -> bool:
    volatility = sample.get("historical_volatility")
    if "volatility_max" in profile and (
        volatility is None or float(volatility) > float(profile["volatility_max"])
    ):
        return False
    strength = (sample.get("signal") or {}).get("strength")
    if "strength_min" in profile and (
        strength is None or float(strength) < float(profile["strength_min"])
    ):
        return False
    features = sample.get("point_in_time_features") or {}
    ma20_distance = features.get("ma20_distance_pct")
    if "ma20_distance_max" in profile and (
        ma20_distance is None or float(ma20_distance) > float(profile["ma20_distance_max"])
    ):
        return False
    gap_pct = features.get("gap_pct")
    if "gap_abs_max" in profile and (
        gap_pct is None or abs(float(gap_pct)) > float(profile["gap_abs_max"])
    ):
        return False
    consecutive_up_days = features.get("consecutive_up_days")
    if "consecutive_up_max" in profile and (
        consecutive_up_days is None
        or int(consecutive_up_days) > int(profile["consecutive_up_max"])
    ):
        return False
    if profile.get("reject_bearish_volume_divergence") and (
        features.get("bearish_volume_divergence") is None
        or bool(features["bearish_volume_divergence"])
    ):
        return False
    return True


def evaluate_loss_rejection_profiles(
    samples: list[dict],
    *,
    train_days: int = 80,
    top_n: int = 10,
    min_train_selections: int = 30,
    min_validation_selections: int = 30,
) -> dict:
    """Train a conservative abstention rule, then evaluate untouched dates once."""
    dates = sorted({str(sample["date"]) for sample in samples})
    if len(dates) <= train_days:
        return {"status": "insufficient_dates", "deployment_eligible": False}
    train_dates = set(dates[:train_days])
    validation_dates = set(dates[train_days:])
    train_rows = [sample for sample in samples if str(sample["date"]) in train_dates]
    validation_rows = [sample for sample in samples if str(sample["date"]) in validation_dates]
    train_selected, _ = _gate_profile_rows(train_rows, _GATE_PROFILES[0], top_n)
    validation_selected, _ = _gate_profile_rows(validation_rows, _GATE_PROFILES[0], top_n)

    training_profiles = []
    for profile in _LOSS_REJECTION_PROFILES:
        filtered = [row for row in train_selected if _matches_loss_rejection_profile(row, profile)]
        training_profiles.append({"profile": profile["key"], "metrics": _return_metrics(filtered)})
    selected_training = max(
        enumerate(training_profiles),
        key=lambda item: (
            item[1]["metrics"]["hit_rate"]
            if item[1]["metrics"]["selections"] >= min_train_selections
            and item[1]["metrics"]["hit_rate"] is not None
            else -1,
            item[1]["metrics"]["avg_excess_return"]
            if item[1]["metrics"]["selections"] >= min_train_selections
            and item[1]["metrics"]["avg_excess_return"] is not None
            else -999,
            -item[0],
        ),
    )[1]
    selected_profile = next(
        profile for profile in _LOSS_REJECTION_PROFILES if profile["key"] == selected_training["profile"]
    )
    selected_validation = [
        row for row in validation_selected if _matches_loss_rejection_profile(row, selected_profile)
    ]
    validation_metrics = _return_metrics(selected_validation)
    baseline_metrics = _return_metrics(validation_selected)
    validation_profiles = []
    for profile in _LOSS_REJECTION_PROFILES:
        metrics = _return_metrics(
            [row for row in validation_selected if _matches_loss_rejection_profile(row, profile)]
        )
        profile_hit_lift = None
        if metrics["hit_rate"] is not None and baseline_metrics["hit_rate"] is not None:
            profile_hit_lift = round(metrics["hit_rate"] - baseline_metrics["hit_rate"], 2)
        profile_return_lift = None
        if metrics["avg_excess_return"] is not None and baseline_metrics["avg_excess_return"] is not None:
            profile_return_lift = round(
                metrics["avg_excess_return"] - baseline_metrics["avg_excess_return"], 4
            )
        validation_profiles.append(
            {
                "profile": profile["key"],
                "metrics": metrics,
                "hit_rate_lift": profile_hit_lift,
                "avg_excess_return_lift": profile_return_lift,
            }
        )
    hit_lift = None
    if validation_metrics["hit_rate"] is not None and baseline_metrics["hit_rate"] is not None:
        hit_lift = round(validation_metrics["hit_rate"] - baseline_metrics["hit_rate"], 2)
    eligible = (
        selected_profile["key"] != "baseline"
        and validation_metrics["selections"] >= min_validation_selections
        and hit_lift is not None
        and hit_lift >= 3
        and (validation_metrics["avg_excess_return"] or 0) > (baseline_metrics["avg_excess_return"] or 0)
    )
    return {
        "status": "eligible_for_review" if eligible else "no_stable_improvement",
        "deployment_eligible": eligible,
        "train_start": dates[0],
        "train_end": dates[train_days - 1],
        "validation_start": dates[train_days],
        "validation_end": dates[-1],
        "selected_profile": selected_profile["key"],
        "training_profiles": training_profiles,
        "validation_metrics": validation_metrics,
        "baseline_validation_metrics": baseline_metrics,
        "validation_profiles": validation_profiles,
        "hit_rate_lift": hit_lift,
        "caliber": "baseline_gate_then_point_in_time_loss_rejection_on_untouched_dates",
    }


def evaluate_candidate_gate_profiles(
    samples: list[dict], *, train_days: int = 80, top_n: int = 10
) -> dict:
    """Select a gate on early dates, then evaluate once on untouched later dates."""
    dates = sorted({str(sample["date"]) for sample in samples})
    if len(dates) <= train_days:
        return {"status": "insufficient_dates", "deployment_eligible": False}
    train_dates = set(dates[:train_days])
    validation_dates = set(dates[train_days:])
    train_rows = [sample for sample in samples if str(sample["date"]) in train_dates]
    validation_rows = [sample for sample in samples if str(sample["date"]) in validation_dates]

    training: list[dict] = []
    for profile in _GATE_PROFILES:
        selected, coverage = _gate_profile_rows(train_rows, profile, top_n)
        training.append({"profile": profile["key"], "metrics": _return_metrics(selected), "coverage": coverage})
    selected_training = max(
        enumerate(training),
        key=lambda item: (
            item[1]["metrics"]["hit_rate"] if item[1]["metrics"]["hit_rate"] is not None else -1,
            item[1]["metrics"]["avg_excess_return"] if item[1]["metrics"]["avg_excess_return"] is not None else -999,
            -item[0],
        ),
    )[1]
    selected_profile = next(profile for profile in _GATE_PROFILES if profile["key"] == selected_training["profile"])
    baseline_profile = _GATE_PROFILES[0]
    selected_validation, selected_coverage = _gate_profile_rows(validation_rows, selected_profile, top_n)
    baseline_validation, baseline_coverage = _gate_profile_rows(validation_rows, baseline_profile, top_n)
    validation_metrics = _return_metrics(selected_validation)
    baseline_metrics = _return_metrics(baseline_validation)
    hit_lift = None
    if validation_metrics["hit_rate"] is not None and baseline_metrics["hit_rate"] is not None:
        hit_lift = round(validation_metrics["hit_rate"] - baseline_metrics["hit_rate"], 2)
    eligible = (
        selected_profile["key"] != "baseline"
        and validation_metrics["selections"] >= 30
        and hit_lift is not None
        and hit_lift >= 3
        and (validation_metrics["avg_excess_return"] or 0) > (baseline_metrics["avg_excess_return"] or 0)
    )
    return {
        "status": "eligible_for_review" if eligible else "no_stable_improvement",
        "deployment_eligible": eligible,
        "train_start": dates[0],
        "train_end": dates[train_days - 1],
        "validation_start": dates[train_days],
        "validation_end": dates[-1],
        "selected_profile": selected_profile["key"],
        "training_profiles": training,
        "validation_metrics": validation_metrics,
        "baseline_validation_metrics": baseline_metrics,
        "validation_coverage": selected_coverage,
        "baseline_validation_coverage": baseline_coverage,
        "hit_rate_lift": hit_lift,
    }


def _fetch_benchmark(start: str, end: str) -> pd.DataFrame:
    frame = akshare_guard.call(ak.stock_zh_index_daily, symbol=BENCHMARK)
    if frame is None or frame.empty:
        return pd.DataFrame()
    frame["date"] = pd.to_datetime(frame["date"])
    return frame[(frame["date"] >= start) & (frame["date"] <= end)].copy()


def _fetch_stock_history(code: str, days: int) -> pd.DataFrame:
    history = data_service.get_history(code, days)
    if history is None or not history.dates:
        return pd.DataFrame()
    size = min(
        len(history.dates),
        len(history.closes),
        len(history.opens),
        len(history.highs),
        len(history.lows),
    )
    turnover = list(history.turnover or [])
    if len(turnover) < size:
        turnover.extend([None] * (size - len(turnover)))
    return pd.DataFrame(
        {
            "date": history.dates[-size:],
            "open": history.opens[-size:],
            "high": history.highs[-size:],
            "low": history.lows[-size:],
            "close": history.closes[-size:],
            "turnover": turnover[-size:],
        }
    )


def _fetch_etf_history(code: str, days: int) -> pd.DataFrame:
    """Fetch ETF bars through the Tencent path without Eastmoney's fund-code lookup."""
    end = dt.date.today()
    start = end - dt.timedelta(days=max(240, days * 2))
    symbol = f"sh{code}" if str(code).startswith("5") else f"sz{code}"
    required = {"date", "open", "high", "low", "close"}
    frame = None
    for _attempt in range(3):
        try:
            candidate = akshare_guard.call(
                ak.stock_zh_a_hist_tx,
                symbol=symbol,
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )
        except Exception:
            continue
        if candidate is not None and not candidate.empty and required.issubset(candidate.columns):
            frame = candidate
            break
    if frame is None:
        return pd.DataFrame()
    columns = ["date", "open", "high", "low", "close"]
    if "amount" in frame.columns:
        columns.append("amount")
    result = frame.loc[:, columns].copy()
    result["turnover"] = None
    return result.tail(days)


def historical_window_days(eval_days: int, instrument_type: str) -> int:
    upper_bound = 1400 if instrument_type == "etf" else 640
    minimum = 400 if instrument_type == "etf" else 180
    return min(upper_bound, max(minimum, eval_days + 100))


def run_historical_calibration(
    *,
    codes: list[str] | None = None,
    eval_days: int = 120,
    top_n: int = 10,
    min_train_days: int = 20,
    validation_days: int = 5,
    instrument_type: str = "stock",
    segment_by_code: dict[str, str] | None = None,
    cross_sectional_evaluation_pools: dict[str, list[str]] | None = None,
) -> dict:
    universe = list(dict.fromkeys(codes or STRATEGY_BACKTEST_POOL))
    end = dt.date.today()
    start = end - dt.timedelta(days=max(420, (eval_days + 100) * 2))
    history_days = historical_window_days(eval_days, instrument_type)
    history_loader = _fetch_etf_history if instrument_type == "etf" else _fetch_stock_history
    histories = {
        code: frame
        for code in universe
        if not (frame := history_loader(code, history_days)).empty
    }
    benchmark = _fetch_benchmark(start.isoformat(), end.isoformat())
    relative_benchmarks_by_code = (
        build_category_relative_benchmarks(histories, segment_by_code or {})
        if instrument_type == "etf" and segment_by_code
        else None
    )
    samples = build_historical_samples(
        histories,
        benchmark,
        eval_days=eval_days,
        segment_by_code=segment_by_code,
        instrument_type=instrument_type,
        relative_benchmarks_by_code=relative_benchmarks_by_code,
    )
    baseline_samples, _ = _gate_profile_rows(samples, _GATE_PROFILES[0], min(top_n, len(universe)))
    regression_train_days = min(
        120,
        max(20, len({sample["date"] for sample in samples}) * 2 // 5),
    )
    result = calibrate_walk_forward(
        samples,
        min_train_days=min_train_days,
        validation_days=validation_days,
        top_n=min(top_n, len(universe)),
        min_train_selections=max(20, min_train_days),
        min_oos_selections=max(30, validation_days * 6),
    )
    backtest_caliber_audit = assess_backtest_caliber(
        instrument_type=instrument_type,
        capabilities={
            "settlement_rule": "t_plus_1",
            "price_limit_handling": (
                instrument_type == "etf"
                and all(code in KNOWN_ETF_PRICE_LIMIT_CODES for code in universe)
            ),
            "tick_size_rounding": True,
            "fee_model_verified": False,
            "historical_tradability": False,
            "point_in_time_features": True,
            "benchmark_alignment": True,
        },
    )
    result.update(
        {
            "deployment_eligible": False,
            "deployment_reason": (
                "ETF 分类方案仍需跨样本与滚动窗口复核，不可直接上线"
                if instrument_type == "etf"
                else "历史截面仍缺少 PE/PB，仅供技术与量能因子研究复核，不可直接上线"
            ),
            "validation_scope": "research_only_technical_factors",
            "result_claim_scope": backtest_caliber_audit["claim_scope"],
            "backtest_caliber_audit": backtest_caliber_audit,
            "fee_assumptions": etf_fee_assumptions() if instrument_type == "etf" else None,
            "instrument_type": instrument_type,
            "data_source": (
                "Tencent ETF daily + AKShare CSI300 daily"
                if instrument_type == "etf"
                else "Tencent A-share daily with turnover + AKShare CSI300 daily"
            ),
            "requested_universe": universe,
            "loaded_universe": sorted(histories),
            "universe_bias": "static_pool_survivorship_risk",
            "feature_coverage": {
                "momentum": "production_equivalent_from_daily_close",
                "trend": "production_equivalent_from_daily_close",
                "value": "unavailable_historical_snapshot",
                "volume": "production_equivalent_from_daily_turnover_close_and_macd",
                "loss_rejection": "point_in_time_ma20_gap_runup_and_turnover_divergence",
                "execution_quality": (
                    "point_in_time_relative_amount_and_amplitude"
                    if instrument_type == "etf"
                    else "amplitude_only_without_amount_series"
                ),
                "high_win_rate": (
                    "point_in_time_20d_leave_one_out_category_relative_strength_and_5_20_60_trend_alignment"
                    if instrument_type == "etf" and segment_by_code
                    else "point_in_time_20d_market_relative_strength_and_5_20_60_trend_alignment"
                ),
                "regression": "rolling_standardized_ridge_on_point_in_time_technical_features",
            },
            "candidate_gate_research": evaluate_candidate_gate_profiles(
                samples,
                train_days=min(80, max(20, len({sample["date"] for sample in samples}) * 2 // 3)),
                top_n=min(top_n, len(universe)),
            ),
            "execution_research": evaluate_execution_profiles(
                samples,
                train_days=min(80, max(20, len({sample["date"] for sample in samples}) * 2 // 3)),
                top_n=min(top_n, len(universe)),
            ),
            "board_specific_research": evaluate_board_specific_profiles(
                samples,
                train_days=min(80, max(20, len({sample["date"] for sample in samples}) * 2 // 3)),
                top_n=min(top_n, len(universe)),
                segments=tuple(dict.fromkeys((segment_by_code or {}).values())) or ("main", "chinext", "star"),
            ),
            "market_regime_research": evaluate_market_regime_filter(
                samples,
                train_days=min(80, max(20, len({sample["date"] for sample in samples}) * 2 // 3)),
                top_n=min(top_n, len(universe)),
            ),
            "holding_period_research": evaluate_holding_periods(
                samples,
                train_days=min(80, max(20, len({sample["date"] for sample in samples}) * 2 // 3)),
                top_n=min(top_n, len(universe)),
            ),
            "capacity_holding_research": evaluate_capacity_horizons(
                samples,
                train_days=min(80, max(20, len({sample["date"] for sample in samples}) * 2 // 3)),
                top_n=min(top_n, len(universe)),
                max_positions=10,
            ),
            "risk_budget_research": evaluate_risk_budgets(
                samples,
                train_days=min(80, max(20, len({sample["date"] for sample in samples}) * 2 // 3)),
                top_n=min(top_n, len(universe)),
            ),
            "volatility_budget_research": evaluate_volatility_budgets(
                samples,
                train_days=min(80, max(20, len({sample["date"] for sample in samples}) * 2 // 3)),
                top_n=min(top_n, len(universe)),
            ),
            "board_budget_research": evaluate_board_budgets(
                samples,
                train_days=min(80, max(20, len({sample["date"] for sample in samples}) * 2 // 3)),
                top_n=min(top_n, len(universe)),
            ),
            "rolling_stability_research": evaluate_rolling_stability(
                samples,
                train_days=min(80, max(20, len({sample["date"] for sample in samples}) * 2 // 3)),
                window_days=60,
                top_n=min(top_n, len(universe)),
            ),
            "transaction_cost_research": evaluate_transaction_cost_sensitivity(
                samples,
                horizon=1,
                top_n=min(top_n, len(universe)),
            ),
            "return_distribution_research": evaluate_return_distribution(
                samples,
                horizon=1,
                top_n=min(top_n, len(universe)),
            ),
            "loss_rejection_research": evaluate_loss_rejection_profiles(
                samples,
                train_days=min(80, max(20, len({sample["date"] for sample in samples}) * 2 // 3)),
                top_n=min(top_n, len(universe)),
            ),
            "regression_research": evaluate_walk_forward_regression(
                baseline_samples,
                train_days=regression_train_days,
                validation_days=min(20, max(5, validation_days)),
                top_n=min(top_n, len(universe)),
            ),
        }
    )
    if instrument_type == "etf" and segment_by_code:
        sample_date_count = len({sample["date"] for sample in samples})
        rolling_train_days = min(240, max(80, sample_date_count // 3))
        rolling_validation_days = min(120, max(40, sample_date_count // 6))
        result["rolling_segment_research"] = {
            segment: evaluate_rolling_segment_profiles(
                samples,
                segment=segment,
                train_days=rolling_train_days,
                validation_days=rolling_validation_days,
                top_n=min(top_n, len(universe)),
            )
            for segment in dict.fromkeys(segment_by_code.values())
        }
        result["rolling_regime_switching_research"] = {
            segment: evaluate_rolling_regime_switching(
                samples,
                segment=segment,
                train_days=rolling_train_days,
                validation_days=rolling_validation_days,
                top_n=min(top_n, len(universe)),
            )
            for segment in dict.fromkeys(segment_by_code.values())
        }
        result["rolling_liquidity_research"] = {
            segment: evaluate_rolling_liquidity_profiles(
                samples,
                segment=segment,
                train_days=rolling_train_days,
                validation_days=rolling_validation_days,
                top_n=min(top_n, len(universe)),
            )
            for segment in dict.fromkeys(segment_by_code.values())
        }
        result["rolling_order_validity_research"] = {
            segment: evaluate_rolling_order_validity(
                samples,
                segment=segment,
                train_days=rolling_train_days,
                validation_days=rolling_validation_days,
                top_n=min(top_n, len(universe)),
            )
            for segment in dict.fromkeys(segment_by_code.values())
        }
        result["rolling_high_win_rate_research"] = {
            segment: evaluate_rolling_high_win_rate_profiles(
                samples,
                segment=segment,
                train_days=rolling_train_days,
                validation_days=rolling_validation_days,
                top_n=min(top_n, len(universe)),
            )
            for segment in dict.fromkeys(segment_by_code.values())
        }
        result["rolling_cross_sectional_factor_research"] = {
            segment: evaluate_rolling_cross_sectional_factors(
                samples,
                segment=segment,
                train_days=rolling_train_days,
                validation_days=rolling_validation_days,
            )
            for segment in dict.fromkeys(segment_by_code.values())
        }
        if cross_sectional_evaluation_pools:
            result["rolling_cross_sectional_pool_research"] = {}
            loaded_codes = set(histories)
            for pool_name, pool_codes in cross_sectional_evaluation_pools.items():
                evaluation_codes = sorted(set(pool_codes) & loaded_codes)
                evaluation_code_set = set(evaluation_codes)
                evaluation_samples = [
                    sample for sample in samples if sample.get("code") in evaluation_code_set
                ]
                result["rolling_cross_sectional_pool_research"][pool_name] = {}
                for segment in dict.fromkeys(segment_by_code.values()):
                    segment_result = evaluate_rolling_cross_sectional_factors(
                        evaluation_samples,
                        segment=segment,
                        rank_reference_samples=samples,
                        train_days=rolling_train_days,
                        validation_days=rolling_validation_days,
                    )
                    segment_result["evaluation_codes"] = sorted(
                        code for code in evaluation_codes if segment_by_code.get(code) == segment
                    )
                    segment_result["rank_reference_codes"] = len(
                        {
                            sample.get("code")
                            for sample in samples
                            if sample.get("market_board") == segment
                        }
                    )
                    result["rolling_cross_sectional_pool_research"][pool_name][segment] = (
                        segment_result
                    )
    return result


DEFAULT_ETF_GROUPS = {
    "broad": ["510300", "510500", "510050", "159915", "588000"],
    "industry": ["512480", "512010", "512800", "515030", "515790"],
    "style": ["510880", "512100", "159967", "159949", "515180"],
}


def run_etf_historical_calibration(
    *,
    etf_groups: dict[str, list[str]] | None = None,
    eval_days: int = 300,
    top_n: int = 5,
    min_train_days: int = 80,
    validation_days: int = 20,
    cross_sectional_evaluation_pools: dict[str, list[str]] | None = None,
) -> dict:
    groups = etf_groups or DEFAULT_ETF_GROUPS
    segment_by_code = {
        code: segment
        for segment, codes in groups.items()
        for code in codes
    }
    return run_historical_calibration(
        codes=list(segment_by_code),
        eval_days=eval_days,
        top_n=top_n,
        min_train_days=min_train_days,
        validation_days=validation_days,
        instrument_type="etf",
        segment_by_code=segment_by_code,
        cross_sectional_evaluation_pools=cross_sectional_evaluation_pools,
    )
