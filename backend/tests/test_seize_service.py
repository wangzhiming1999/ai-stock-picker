"""封板雷达纯函数测试（离线，不触发任何行情请求）。

覆盖三类信号派生与条件性收益读数：
  · derive_just_sealed  —— 首封时间窗口过滤 + premium 复用 + 次日涨停价锚点
  · derive_reseal      —— 距涨停 ≤ 阈值才进回封候选，按距涨停升序
  · derive_broken_alert—— 掉离涨停且振幅大才列为预警
  · _conditional_premium —— 条件性读数，expect_pct = 可成交档均值，conditional=True
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services import seize_service as s
from app.services.limitup_service import normalize_broken


def _cn_now_str(offset_sec: int = 0) -> str:
    """生产格式 ``HH:MM:SS``（limitup_service._fmt_time 的产出）。

    ⚠️ 必须喂带冒号的生产格式：旧夹具用 ``%H%M%S``（无冒号）与生产格式漂移，
    让「解析不了带冒号时间」的 bug 在测试里永远不暴露（2026-10-30 实测
    刚封板档 215 条落库里 0 条）。
    """
    t = datetime.now(timezone(timedelta(hours=8))) + timedelta(seconds=offset_sec)
    return t.strftime("%H:%M:%S")


def _broken(code: str, price: float, limit: float, amp: float, zbc: int, sector: str = "测试") -> dict:
    return normalize_broken(
        {"c": code, "n": f"股{code}", "p": int(price * 1000), "zdp": round((price / limit - 1) * 100, 2),
         "ztp": int(limit * 1000), "zf": amp, "zbc": zbc, "hybk": sector}
    )


def test_reseal_filters_by_distance_and_sorts():
    b_near = _broken("600000", 9.95, 10.0, 1.2, 1)   # dist 0.5%
    b_far = _broken("600001", 9.50, 10.0, 8.0, 3)    # dist 5.0% → 超出阈值
    b_mid = _broken("600002", 9.80, 10.0, 7.0, 2)    # dist 2.0%
    out = s.derive_reseal([b_far, b_near, b_mid])
    codes = [r["code"] for r in out]
    assert "600001" not in codes
    assert codes[0] == "600000"  # 距涨停最小排最前
    assert out[0]["dist_to_limit_pct"] == 0.5
    assert out[0]["premium_if_sealed"]["conditional"] is True


def test_reseal_recovering_flag_is_bool():
    out = s.derive_reseal([_broken("600000", 9.95, 10.0, 1.2, 1)])
    assert isinstance(out[0]["recovering"], bool)


def test_broken_alert_requires_distance_and_amplitude():
    b_big = _broken("600001", 9.50, 10.0, 8.0, 3)    # dist 5% + amp 8% → 预警
    b_small_amp = _broken("600002", 9.95, 10.0, 1.0, 1)  # 贴板、振幅小 → 不预警
    b_small_dist = _broken("600003", 9.97, 10.0, 9.0, 2) # dist 0.3% → 不预警（仍贴板）
    out = s.derive_broken_alert([b_big, b_small_amp, b_small_dist])
    assert [r["code"] for r in out] == ["600001"]


def test_conditional_premium_uses_tradable_mean():
    cp = s._conditional_premium()
    # 可成交档 = 5-15% / 15-30% / ≥30% 的期望均值：(1.62 + 1.10 + 0.40) / 3
    assert cp["expect_pct"] == 1.04
    assert cp["conditional"] is True


def test_just_sealed_window_filters_stale_and_reuses_premium():
    fresh = {
        "code": "000001", "name": "平安", "price": 10.0, "change_pct": 10.0,
        "seal_time": _cn_now_str(-30), "break_count": 0, "seal_fund_yi": 2.3,
        "seal_ratio": 1.5, "turnover": 8.0, "sector": "金融",
    }
    stale = {
        "code": "000002", "name": "万科", "price": 9.0, "change_pct": 10.0,
        "seal_time": "093000", "break_count": 0, "seal_fund_yi": 1.0,
        "seal_ratio": 0.5, "turnover": 6.0, "sector": "地产",
    }
    out = s.derive_just_sealed([fresh, stale])
    assert [r["code"] for r in out] == ["000001"]
    row = out[0]
    # premium 复用 limitup_premium（5-15% 档期望 1.62）；次日涨停价 = 10 × 1.1 = 11.0
    assert row["premium"]["expect_pct"] == 1.62
    assert row["next_limit_price"] == 11.0
    assert row["entry_discount_pct"] == 0.0


def test_seconds_since_seal_accepts_both_production_formats():
    """格式兼容守卫：带冒号（生产 _fmt_time 产出）与 HHMMSS 都要能解析。

    旧实现只认无冒号切片，``09:35:12`` 的 ``[2:4]`` 取到 ``:3`` → ValueError
    → 恒 None → 刚封板档从未落库。夹具曾用无冒号格式与生产漂移，测试全绿
    而线上 0 样本 —— 这里两种格式都必须进测试。
    """
    colon = s._seconds_since_seal(_cn_now_str(-60))
    assert colon is not None and 55 <= colon <= 65

    now_hms = _cn_now_str(-60)
    bare = now_hms.replace(":", "")
    assert s._seconds_since_seal(bare) is not None

    # 缺值 / 短串 / 非法字符 → None，不许抛
    assert s._seconds_since_seal(None) is None
    assert s._seconds_since_seal("") is None
    assert s._seconds_since_seal("09:35") is None
    assert s._seconds_since_seal("ab:cd:ef") is None


def test_clear_cache_is_safe():
    s.clear_cache()  # 不抛异常即可


def test_resolve_next_open_finds_first_later_day():
    dates = ["2026-09-28", "2026-09-29", "2026-09-30", "2026-10-09"]
    opens = [10.0, 10.5, None, 11.0]
    # trade_date=09-29 → D+1 是 09-30，但开盘缺失 → 跳到再下一个有效日 10-09
    assert s._resolve_next_open(dates, opens, "2026-09-29") == 11.0
    # trade_date=09-28 → 09-29 开盘
    assert s._resolve_next_open(dates, opens, "2026-09-28") == 10.5
    # 之后没有有效日 → None（留待下次结算，不写 0 冒充）
    assert s._resolve_next_open(dates, opens, "2026-10-09") is None
    assert s._resolve_next_open([], [], "2026-09-29") is None


def test_calc_return_pct_guards_illegal_input():
    assert s._calc_return_pct(10.0, 10.8) == 8.0
    assert s._calc_return_pct(0, 10.0) is None
    assert s._calc_return_pct(10.0, -1) is None


def test_log_rows_shape():
    sealed = [{"code": "000001", "name": "A", "price": 10.0, "limit_price": 10.0}]
    reseal = [{"code": "000002", "name": "B", "price": 9.95, "limit_price": 10.0, "dist_to_limit_pct": 0.5}]
    rows = s._log_rows("2026-09-30", sealed, reseal)
    kinds = {r["signal_kind"]: r for r in rows}
    assert kinds["just_sealed"]["dist_to_limit_pct"] == 0.0
    assert kinds["reseal"]["buy_price"] == 9.95
    assert all(r["trade_date"] == "2026-09-30" for r in rows)


def test_aggregate_reseal_buckets_and_stats():
    rows = [
        {"dist_to_limit_pct": 0.5, "return_pct": 2.0},
        {"dist_to_limit_pct": 0.8, "return_pct": -1.0},
        {"dist_to_limit_pct": 2.0, "return_pct": 1.0},
        {"dist_to_limit_pct": 2.5, "return_pct": None},  # 未结算不进统计
    ]
    out = s._aggregate_reseal(rows)
    assert out["n"] == 4
    assert out["settled"] == 3
    assert out["win_rate"] == 66.7
    assert out["avg_return"] == 0.67
    assert out["median_return"] == 1.0
    buckets = {b["label"]: b for b in out["buckets"]}
    assert buckets["≤1%"]["n"] == 2 and buckets["≤1%"]["avg_return"] == 0.5
    assert buckets["1-3%"]["n"] == 1 and buckets["1-3%"]["avg_return"] == 1.0


def test_aggregate_reseal_empty_is_safe():
    out = s._aggregate_reseal([])
    assert out["settled"] == 0 and out["win_rate"] is None and out["avg_return"] is None


def test_fbt_bucket_windows():
    assert s._fbt_bucket("09:31:00") == "9:30-10:00"
    assert s._fbt_bucket("092500") is None          # 集合竞价一字板，雷达捕捉不到
    assert s._fbt_bucket("10:30:00") == "10:00-11:00"
    assert s._fbt_bucket("13:20:00") == "13:00-14:00"
    assert s._fbt_bucket("14:10:00") == "14:00-14:30"
    assert s._fbt_bucket("14:35:00") is None        # 尾盘板，唯一负期望档，排除
    assert s._fbt_bucket("") is None
    assert s._fbt_bucket("abc") is None


def test_aggregate_sealed_buckets():
    rows = [
        {"return_pct": 2.0, "fbt_bucket": "9:30-10:00"},
        {"return_pct": -1.0, "fbt_bucket": "9:30-10:00"},
        {"return_pct": 1.5, "fbt_bucket": "13:00-14:00"},
        {"return_pct": None, "fbt_bucket": "13:00-14:00"},
    ]
    out = s._aggregate_sealed(rows)
    assert out["n"] == 4 and out["settled"] == 3
    assert out["win_rate"] == 66.7
    buckets = {b["label"]: b for b in out["buckets"]}
    assert buckets["9:30-10:00"]["n"] == 2 and buckets["9:30-10:00"]["win_rate"] == 50.0
    assert buckets["14:00-14:30"]["n"] == 0 and buckets["14:00-14:30"]["avg_return"] is None


def _row(ret, sealed):
    return {"realized_return_pct": ret, "sealed_final": sealed}


def test_summarize_settled_layers_by_sealed_final():
    """sealed_final 分层是复盘核心发现：亏损集中在炸板档，必须分开报。

    另锁四问：可成交/基准两问答不上来（passed=None 三态），没有四问 ≠ 四问过了。
    """
    rows = [
        _row(1.0, True), _row(2.0, True), _row(-1.0, True),   # 封住 3：胜率 66.7
        _row(-2.0, False), _row(-3.0, False), _row(-1.5, False), _row(0.5, False),  # 炸板 4
        _row(None, False),  # 待结算，不进分母
    ]
    out = s.summarize_settled(rows)
    assert out["total"] == 8 and out["settled"] == 7 and out["pending"] == 1
    sealed = out["sealed_split"]["sealed"]
    broken = out["sealed_split"]["broken"]
    assert sealed["n"] == 3 and sealed["win_rate"] == 66.7
    assert broken["n"] == 4 and broken["win_rate"] == 25.0
    assert broken["avg_return"] == -1.5  # (-2 -3 -1.5 +0.5)/4
    assert "不能" in out["sealed_split"]["note"] and "筛选器" in out["sealed_split"]["note"]

    four = out["four_questions"]
    by_key = {i["key"]: i for i in four["items"]}
    assert by_key["sample"]["passed"] is False          # n=7 < 30 门槛，样本问不通过
    assert by_key["tradable"]["passed"] is None         # 三态：答不上来不是通过
    assert by_key["benchmark_sign"]["passed"] is None
    assert by_key["tradable"]["answered"] is False


def test_summarize_settled_sample_gate_and_empty():
    # n < 30：样本问不通过（7 条已结算）
    out = s.summarize_settled([_row(-1.0, False)] * 7)
    by_key = {i["key"]: i for i in out["four_questions"]["items"]}
    assert by_key["sample"]["passed"] is False

    # 空样本：不出假分层假四问结论，sealed_split 各层 n=0
    empty = s.summarize_settled([])
    assert empty["settled"] == 0 and empty["win_rate"] is None
    assert empty["sealed_split"]["sealed"]["n"] == 0
    assert empty["four_questions"]["verdict"] in ("unknown", "inflated", "credible")


def test_summarize_settled_median_mean_spread_flags():
    """均值被左尾拉低（|均值|/|中位| > 1.3）时第二问必须报「引用中位数」。"""
    rows = [_row(-1.0, False)] * 10 + [_row(-20.0, False)]  # 中位 −1.0、均值 −2.73
    out = s.summarize_settled(rows)
    by_key = {i["key"]: i for i in out["four_questions"]["items"]}
    assert by_key["median"]["passed"] is False
    assert "中位数" in by_key["median"]["detail"]
    assert out["four_questions"]["verdict"] == "inflated"
