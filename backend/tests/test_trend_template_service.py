from app.services.trend_template_service import assess_trend_template


def test_strong_long_term_trend_is_ready_to_watch():
    closes = [10 + i * 0.05 for i in range(260)]
    result = assess_trend_template(closes, closes[-1])

    assert result["status"] == "passed"
    assert result["passed"] == result["total"]
    assert result["action"] == "进入候选，等待放量突破或缩量回踩"
    assert result["score"] == 10.0


def test_weak_trend_is_rejected_instead_of_presented_as_buy_signal():
    closes = [30 - i * 0.06 for i in range(260)]
    result = assess_trend_template(closes, closes[-1])

    assert result["status"] == "failed"
    assert result["passed"] < result["total"] / 2
    assert result["action"] == "暂不参与，等待趋势重新转强"


def test_insufficient_history_is_reported_honestly():
    result = assess_trend_template([10.0] * 120, 10.0)

    assert result["status"] == "insufficient_data"
    assert result["score"] == 0
    assert "至少 250 个交易日" in result["action"]


def test_invalid_prices_do_not_create_false_positive():
    result = assess_trend_template([10.0] * 250 + [0.0, -1.0], 10.0)

    assert result["status"] == "insufficient_data"
