"""Point-in-time historical replay for recommendation technical factors.

This intentionally does not fabricate historical PE/PB/turnover snapshots.
Results are research evidence only and cannot directly change live parameters.
"""
from __future__ import annotations

import datetime as dt
import math
from statistics import mean, median, pstdev

import akshare as ak
import pandas as pd

from app.services import akshare_guard, data_service, signal_service
from app.services.backtest_service import BENCHMARK, STRATEGY_BACKTEST_POOL
from app.services.recommend_calibration_service import calibrate_walk_forward

BASE_TRANSACTION_COST_PCT = 0.15


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
            turnovers = (
                frame.iloc[: position + 1]["turnover"].tolist()
                if "turnover" in frame.columns
                else None
            )
            scores = compute_technical_strategy_scores(closes, turnovers)
            if scores is None:
                continue
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
            samples.append(
                {
                    "date": day.date().isoformat(),
                    "outcome_date": outcome_day.date().isoformat(),
                    "code": code,
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
                    "market_board": market_board(code),
                    "historical_volatility": round(historical_volatility, 4) if historical_volatility is not None else None,
                }
            )
    return samples


def resolve_historical_execution(sample: dict, setup: str) -> dict:
    """Resolve a T+1 execution from real OHLC; unfilled plans stay out of returns."""
    close = float(sample["recommend_close"])
    open_price = float(sample["next_open"])
    high = float(sample["next_high"])
    low = float(sample["next_low"])
    exit_price = float(sample["next_close"])
    signal = sample.get("signal") or {}
    if setup == "close":
        trigger, entry, filled = close, close, True
    else:
        expected = signal_service.expected_price_from_levels(close, signal, setup=setup)
        if not expected or not signal.get("level_valid"):
            return {"execution_status": "unverifiable", "entry_price": None, "net_excess_return": None}
        trigger = float(expected["price"])
        is_pullback = expected["setup"] == "pullback"
        filled = low <= trigger if is_pullback else high >= trigger
        entry = min(trigger, open_price) if is_pullback else max(trigger, open_price)
    if not filled:
        return {"execution_status": "not_triggered", "entry_price": None, "net_excess_return": None}
    net = (exit_price / entry - 1) * 100 - 0.15 - float(sample.get("benchmark_return") or 0)
    return {
        "execution_status": "filled",
        "entry_price": round(entry, 2),
        "exit_price": exit_price,
        "net_excess_return": round(net, 6),
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
    return True


def evaluate_loss_rejection_profiles(
    samples: list[dict],
    *,
    train_days: int = 80,
    top_n: int = 10,
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
            item[1]["metrics"]["hit_rate"] if item[1]["metrics"]["hit_rate"] is not None else -1,
            item[1]["metrics"]["avg_excess_return"]
            if item[1]["metrics"]["avg_excess_return"] is not None
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


def run_historical_calibration(
    *,
    codes: list[str] | None = None,
    eval_days: int = 120,
    top_n: int = 10,
    min_train_days: int = 20,
    validation_days: int = 5,
) -> dict:
    universe = list(dict.fromkeys(codes or STRATEGY_BACKTEST_POOL))
    end = dt.date.today()
    start = end - dt.timedelta(days=max(420, (eval_days + 100) * 2))
    history_days = min(640, max(180, eval_days + 100))
    histories = {
        code: frame
        for code in universe
        if not (frame := _fetch_stock_history(code, history_days)).empty
    }
    benchmark = _fetch_benchmark(start.isoformat(), end.isoformat())
    samples = build_historical_samples(histories, benchmark, eval_days=eval_days)
    result = calibrate_walk_forward(
        samples,
        min_train_days=min_train_days,
        validation_days=validation_days,
        top_n=min(top_n, len(universe)),
        min_train_selections=max(20, min_train_days),
        min_oos_selections=max(30, validation_days * 6),
    )
    result.update(
        {
            "deployment_eligible": False,
            "deployment_reason": "历史截面仍缺少 PE/PB，仅供技术与量能因子研究复核，不可直接上线",
            "validation_scope": "research_only_technical_factors",
            "data_source": "Tencent A-share daily with turnover + AKShare CSI300 daily",
            "requested_universe": universe,
            "loaded_universe": sorted(histories),
            "universe_bias": "static_pool_survivorship_risk",
            "feature_coverage": {
                "momentum": "production_equivalent_from_daily_close",
                "trend": "production_equivalent_from_daily_close",
                "value": "unavailable_historical_snapshot",
                "volume": "production_equivalent_from_daily_turnover_close_and_macd",
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
        }
    )
    return result
