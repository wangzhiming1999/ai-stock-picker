"""Deterministic long-term trend quality assessment.

Based on the public Minervini Trend Template.  This is a screening gate, not a
buy signal: relative strength versus the full market is deliberately omitted
until a reliable benchmark series is available.
"""

from math import isfinite


def _sma(values: list[float], window: int) -> float:
    return sum(values[-window:]) / window


def assess_trend_template(closes: list[float], current_price: float) -> dict:
    prices = [float(value) for value in closes if isfinite(float(value)) and float(value) > 0]
    if len(prices) < 250 or len(prices) != len(closes) or not isfinite(current_price) or current_price <= 0:
        return {
            "name": "长期趋势质量检查",
            "source": "Minervini Trend Template（去除尚无可靠基准的相对强度条件）",
            "status": "insufficient_data",
            "score": 0,
            "passed": 0,
            "total": 7,
            "action": "历史数据不足，需要至少 250 个交易日后再判断",
            "conditions": [],
        }

    ma50 = _sma(prices, 50)
    ma150 = _sma(prices, 150)
    ma200 = _sma(prices, 200)
    ma200_month_ago = sum(prices[-220:-20]) / 200
    low_52w = min(prices[-250:])
    high_52w = max(prices[-250:])

    checks = [
        ("站上长期均线", current_price > ma150 and current_price > ma200),
        ("中期趋势强于长期趋势", ma150 > ma200),
        ("长期趋势仍在上升", ma200 > ma200_month_ago),
        ("均线保持多头顺序", ma50 > ma150 > ma200),
        ("现价站上 50 日均线", current_price > ma50),
        ("已远离一年低点", current_price >= low_52w * 1.30),
        ("仍靠近一年高点", current_price >= high_52w * 0.75),
    ]
    passed = sum(ok for _, ok in checks)
    score = round(passed / len(checks) * 10, 1)
    if passed >= 6:
        status = "passed"
        action = "进入候选，等待放量突破或缩量回踩"
    elif passed >= 4:
        status = "watch"
        action = "继续观察，尚未满足完整趋势条件"
    else:
        status = "failed"
        action = "暂不参与，等待趋势重新转强"

    return {
        "name": "长期趋势质量检查",
        "source": "Minervini Trend Template（去除尚无可靠基准的相对强度条件）",
        "status": status,
        "score": score,
        "passed": passed,
        "total": len(checks),
        "action": action,
        "conditions": [{"label": label, "passed": ok} for label, ok in checks],
    }
