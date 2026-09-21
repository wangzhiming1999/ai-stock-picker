"""三度交易理论打分 · 确定性单测（不联网，纯函数）。"""

import math

from app.services.sandu_service import (
    _detect_golden_cross,
    score_sandu,
    score_strength,
    score_thickness,
    score_velocity,
)


def _build_bullish() -> tuple[list[float], list[float]]:
    """构造一段「先抑后扬」的日线：前期阴跌建仓，末 12 日放量拉升。

    预期：厚度(三阳控三阴)高、力度(金叉+多头排列)高、速度(放量突破)高 → passed。
    """
    closes: list[float] = []
    vols: list[float] = []
    # 前 48 日：阴跌 12.0 → 10.0（MA5 低于 MA20）
    v = 12.0
    for i in range(48):
        v -= 2.0 / 48
        closes.append(round(v, 3))
        vols.append(1.0)  # 阴跌期量小
    # 末 12 日：放量拉升 10.0 → 13.0（MA5 上穿 MA20，金叉）
    for i in range(12):
        v += 3.0 / 12
        closes.append(round(v, 3))
        # 拉升日量能更大，且越近越大
        vols.append(3.0 + i * 0.3)
    # 末日明确放量突破（突破量 >> 前 5 日均量）
    vols[-1] = 12.0
    return closes, vols


def test_insufficient_data():
    closes = [10 + i * 0.1 for i in range(10)]  # 仅 10 根
    res = score_sandu(type("H", (), {"closes": closes, "volumes": None})())
    assert res["status"] == "insufficient_data"
    assert res["overall"] == 0.0
    assert res["thickness"] == 0.0
    assert res["strength"] == 0.0
    assert res["velocity"] == 0.0


def test_full_three_degrees_passed():
    closes, vols = _build_bullish()
    res = score_sandu(type("H", (), {"closes": closes, "volumes": vols})())
    assert res["status"] == "passed", res
    assert res["overall"] >= 7.0, res
    assert res["thickness"] >= 6.0
    assert res["strength"] >= 6.0
    assert res["velocity"] >= 5.0
    # 三度齐备时 reasons 不应含偏弱提示
    assert not any("偏弱" in r for r in res["reasons"])
    # dimensions 含三度
    assert len(res["dimensions"]) == 3
    names = {d["name"] for d in res["dimensions"]}
    assert "厚度 · 量形态" in names
    assert "力度 · 均线归位" in names
    assert "速度 · 量价异动" in names


def test_thickness_all_up_days():
    # 20 根全涨、上涨日量远大于下跌日量（这里没下跌日）
    closes = [10 + i * 0.2 for i in range(20)]
    vols = [3.0] * 20
    res = score_thickness(closes, vols)
    assert res["score"] >= 6.0, res  # 三阳控三阴的「阳多阴少 + 阳放阴缩」成立
    assert res["conditions"][0]["passed"] is True  # 阳多阴少
    assert res["conditions"][1]["passed"] is True  # 阳放阴缩

    # 全跌 → 厚度很低
    down = [20 - i * 0.2 for i in range(20)]
    res_down = score_thickness(down, [2.0] * 20)
    assert res_down["score"] < res["score"]


def test_thickness_clustering_matters():
    """三阳控三阴要求阳线集中、阴线分散：阳线后聚应高于阳线前聚。"""
    # 阳线集中在后半段（建仓尾声）
    back = [10.0, 9.8, 9.9, 9.7, 9.8, 10.1, 10.0, 10.2, 10.4, 10.3,
            10.6, 10.5, 10.8, 10.7, 11.0, 10.9, 11.2, 11.1, 11.4, 11.3]
    # 阳线集中前半段（同样涨跌分布，只是顺序反过来）
    front = back[::-1]
    vols = [2.0] * 20
    res_back = score_thickness(back, vols)
    res_front = score_thickness(front, vols)
    assert res_back["score"] > res_front["score"], (res_back, res_front)


def test_strength_golden_cross_detection():
    # 末 12 日拉升 → 近期金叉
    closes, _ = _build_bullish()
    assert _detect_golden_cross(closes, 5, 20, lookback=12) is True

    # 全程单调上升（金叉发生在很久以前，不在最近 12 日）→ 检测为 False
    monotonic = [10 + i * 0.1 for i in range(80)]
    assert _detect_golden_cross(monotonic, 5, 20, lookback=12) is False

    # 数据不足 → False
    assert _detect_golden_cross([10, 10.1, 10.2], 5, 20) is False


def test_strength_requires_enough_history():
    closes = [10 + i * 0.1 for i in range(40)]  # < 60 根
    res = score_strength(closes)
    assert res["status"] == "insufficient_data"
    assert res["score"] == 0.0


def test_velocity_needs_spike():
    closes = [10 + i * 0.05 for i in range(40)]
    # 无量：末日量与前期持平 → 速度偏低
    vols_flat = [1.0] * 40
    low = score_velocity(closes, vols_flat)
    # 放量突破：末日量 5 倍 + 创新高
    vols_spike = [1.0] * 39 + [6.0]
    high = score_velocity(closes, vols_spike)
    assert high["score"] > low["score"], (low, high)


def test_velocity_insufficient_data():
    closes = [10, 10.1, 10.2]
    res = score_velocity(closes, [1.0, 1.0, 1.0])
    assert res["status"] == "insufficient_data"
    assert res["score"] == 0.0


def test_no_crash_when_volumes_none():
    closes, _ = _build_bullish()
    # volumes 为 None 时厚度/速度应降级而非抛错
    res = score_sandu(type("H", (), {"closes": closes, "volumes": None})())
    assert "overall" in res
    assert isinstance(res["overall"], float)
    assert not math.isnan(res["overall"])
