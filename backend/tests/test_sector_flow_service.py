"""``sector_flow_service`` 的用例。

分五组：① 字段守卫（漏字段不报错、只会整块失效，线上真踩过）
② 日线按位解析 ③ 四态边界 ④ 降级路径 ⑤ 缓存与不变量。

**fixture 里的日线样本是 2026-10-16 从东财真��抓下来的 BK1204（国防军工）**，
不是编的 —— 字段位序与四态边界都是照这批真实数据定的。

⚠️ 字段位序是**定长逗号分隔**：少给一位，后面全部错位而不报错。
所以 ② 里用「主力 == 大单 + 超大单」恒等式锁死映射 —— 这条恒等式在
真实样本 10/10 成立，是唯一能自动发现错位的方法。
"""
from __future__ import annotations

import asyncio
import time

import pytest

from app.services import sector_flow_service as sfs


# BK1204 国防军工 2026-10-16 实测 10 根日线（节选 5 根，够判四态）
# 字段序：日期,主力,小单,中单,大单,超大单,主力占比,...,收盘价,涨跌幅,...
_REAL_DAILY = [
    "2026-10-09,-1511147984.0,1485612032.0,25754112.0,-663195392.0,-847952592.0,-3.33,3.28,0.06,-1.46,-1.87,5247.81,-1.00,0.00,0.00",
    "2026-10-12,-2162896480.0,1859439872.0,294183424.0,-1201469184.0,-961427296.0,-6.83,5.87,0.93,-3.80,-3.04,5129.22,-2.26,0.00,0.00",
    "2026-10-13,1932941248.0,-1378048768.0,-545758720.0,843956224.0,1088985024.0,4.12,-2.93,-1.16,1.80,2.32,5258.99,2.53,0.00,0.00",
    "2026-10-14,-293297168.0,-3803392.0,299103232.0,-93455104.0,-199842064.0,-0.77,-0.01,0.79,-0.25,-0.53,5212.73,-0.88,0.00,0.00",
    "2026-10-15,-3069326048.0,2008698880.0,1042555392.0,-1122099200.0,-1947226848.0,-7.33,4.80,2.49,-2.68,-4.65,5021.55,-3.67,0.00,0.00",
]


@pytest.fixture(autouse=True)
def _clear_caches():
    sfs._rank_cache = None
    sfs._daily_cache.clear()
    sfs._cooldown_until = 0.0
    sfs._last_live_at = 0.0
    yield
    sfs._rank_cache = None
    sfs._daily_cache.clear()
    sfs._cooldown_until = 0.0
    sfs._last_live_at = 0.0


def _series(nets: list[float], supers: list[float] | None = None) -> list[dict]:
    """构造日线序列（nets 单位元）。"""
    supers = supers if supers is not None else [n / 2 for n in nets]
    out = []
    for i, (n, sp) in enumerate(zip(nets, supers)):
        out.append({
            "date": f"2026-10-{i + 5:02d}",
            "main_net": n,
            "super_net": sp,
            "small_net": None,
            "mid_net": None,
            "large_net": n - sp,
            "main_pct": 1.0,
            "close": 5000.0,
            "change_pct": 0.0,
        })
    return out


# ─────────────────────────────── ① 字段守卫


def test_rank_fields_must_carry_key_columns():
    """排行字段串**不能**漏 f184/f66/f72/f104/f105。

    漏字段不会报错，只会让对应分项永远 None：漏 f184 → 结构质量维整块失效；
    漏 f104/f105 → 广度（确认度）恒为None。同一坑在 spot_service 已踩过一次。
    """
    for field in ("f62", "f184", "f66", "f69", "f72", "f75", "f104", "f105", "f128", "f140", "f136"):
        assert field in sfs._RANK_FIELDS, f"排行字段串缺 {field}"


def test_rank_fs_must_be_industry_board_scope():
    """fs 必须是 m:90 t:2（行业板块全量 496），不能漂成个股或概念板块口径。"""
    assert sfs._RANK_FS.strip() == "m:90 t:2"


def test_daily_path_must_be_fund_flow_daykline():
    """日线必须走 fflow/daykline（资金流日线），不是普通 kline（只有价格）。"""
    assert "fflow/daykline" in sfs._DAILY_PATH


def test_rank_row_keeps_all_columns():
    """解析排行行：所有关键列都要落到归一化字段上。"""
    row = sfs._rank_row({
        "f12": "BK1204", "f14": "国防军工", "f3": 3.52,
        "f62": 1229001152.0, "f184": 7.34,
        "f66": 849140800.0, "f69": 5.07,
        "f72": 379860352.0, "f75": 2.27,
        "f104": 136, "f105": 5,
        "f128": "长城军工", "f140": "601606", "f136": 9.99,
        "f207": "超卓航科", "f208": "688237",
    })
    assert row is not None
    assert row["code"] == "BK1204" and row["name"] == "国防军工"
    assert row["main_net"] == 1229001152.0
    assert row["main_pct"] == 7.34
    assert row["super_net"] == 849140800.0 and row["large_net"] == 379860352.0
    assert row["up_count"] == 136 and row["down_count"] == 5
    assert row["leader_name"] == "长城军工" and row["leader_code"] == "601606"
    assert row["laggard_name"] == "超卓航科"


def test_rank_row_drops_row_without_main_flow():
    """主力净额与净占比全缺的行没有排序价值，必须丢。"""
    assert sfs._rank_row({"f12": "BK0001", "f14": "x", "f62": "-", "f184": "-"}) is None
    assert sfs._rank_row({"f14": "x"}) is None


def test_num_keeps_missing_distinct_from_zero():
    """东财用 '-' 表示缺失；缺失必须落 None 而不是 0。"""
    assert sfs._num("-") is None
    assert sfs._num("") is None
    assert sfs._num(None) is None
    assert sfs._num("0") == 0.0


# ─────────────────────────────── ② 日线按位解析


def test_parse_daily_real_sample():
    """真实样本解析根数与数值。"""
    rows = sfs._parse_daily(_REAL_DAILY)
    assert len(rows) == 5
    assert rows[0]["date"] == "2026-10-09"
    assert rows[0]["main_net"] == -1511147984.0
    assert rows[-1]["main_net"] == -3069326048.0
    assert rows[-1]["close"] == 5021.55
    assert rows[-1]["change_pct"] == -3.67


def test_parse_daily_identity_main_equals_large_plus_super():
    """恒等式锁定字段位序：主力净额 == 大单 + 超大单。

    这是唯一能自动发现**错位**的方法 —— 错位后每一项都还是合法数字，
    不报错、只悄悄算错。没有这条断言，fields2 少给一位不会有人发现。
    """
    for row in sfs._parse_daily(_REAL_DAILY):
        assert abs(row["main_net"] - (row["large_net"] + row["super_net"])) < 1.0, row


def test_parse_daily_drops_short_row_instead_of_misaligning():
    """长度不足 13 位的行**整行丢弃**，不能硬解 —— 否则后半段全部错位。"""
    short = "2026-10-13,1932941248.0,-1378048768.0"
    assert sfs._parse_daily([short]) == []
    assert sfs._parse_daily([]) == []


def test_parse_daily_keeps_valid_rows_around_short_one():
    """有短行时，合法行仍要正常解析出来（不能整批连坐）。"""
    short = "2026-10-14,-1.0,-2.0"
    rows = sfs._parse_daily([_REAL_DAILY[0], short, _REAL_DAILY[1]])
    assert len(rows) == 2
    assert [r["date"] for r in rows] == ["2026-10-09", "2026-10-12"]


# ─────────────────────────────── ③ 四态边界


def test_state_exit_when_window_sum_negative():
    """窗口累计转负 = 撤离。"""
    m = {"main_sum_yi": -51.04, "accel_yi": -20.49}
    assert sfs._state(m, -30.69e8, 0.9, 0.5) == "follow_exit"


def test_state_accel_needs_both_high_accel_and_high_continuity():
    """加速流入要求**两张分位表同时**靠前。

    只看加速度分位会让「本来没人买、今天突然买一笔」的板块也判成加速流入；
    持续性门槛（分位 ≥ 中位）把它挡掉。
    """
    m = {"main_sum_yi": 12.0, "accel_yi": 5.0}
    assert sfs._state(m, 8e8, 0.95, 0.95) == "follow_accel"
    # 加速度高但持续性垫底 → 不是可跟随形态
    assert sfs._state(m, 8e8, 0.95, 0.10) == "follow_steady"


def test_state_ebb_when_acceleration_rank_low():
    """加速度分位落到后 1/3 且窗口仍为正 = 退潮。"""
    m = {"main_sum_yi": 20.0, "accel_yi": -8.0}
    assert sfs._state(m, 1e8, 0.10, 0.9) == "follow_ebb"


def test_state_steady_is_the_middle_bucket():
    """中段（加速度中位附近）= 持续流入。"""
    m = {"main_sum_yi": 20.0, "accel_yi": 0.0}
    assert sfs._state(m, 2e8, 0.5, 0.6) == "follow_steady"


def test_state_falls_back_to_today_only_when_trend_missing():
    """时序缺失时降级到「仅当日」，并由 trend_available 标注，不能假装有四态。"""
    assert sfs._state(None, -1e8, 0.5, 0.5) == "follow_exit"
    assert sfs._state(None, 1e8, 0.5, 0.5) == "follow_steady"
    assert sfs._state(None, None, 0.5, 0.5) == "unknown"


def test_all_four_states_are_reachable():
    """四态必须真的分得开 —— 否则四态设计退化成三态（曾因死分支发生过）。"""
    reached = set()
    for cont in (0.9, 0.5, 0.1):
        for accel in (0.95, 0.6, 0.4, 0.2, 0.05):
            for total in (30.0, -5.0):
                m = {"main_sum_yi": total, "accel_yi": 0.0}
                reached.add(sfs._state(m, 1e8, accel, cont))
    assert {"follow_accel", "follow_steady", "follow_ebb", "follow_exit"} <= reached


def test_pct_rank_is_cross_sectional():
    """分位是横截面口径：换日换基准，不可跨日比较。"""
    assert sfs._pct_rank([1.0, 2.0, 3.0, 4.0], 4.0) == 0.875
    assert sfs._pct_rank([1.0, 2.0, 3.0, 4.0], 1.0) == 0.125
    assert sfs._pct_rank([], 1.0) == 0.5


def test_trend_metrics_real_sample():
    """真实国防军工 5 日样本的时序指标。"""
    m = sfs._trend_metrics(sfs._parse_daily(_REAL_DAILY))
    assert m is not None
    assert m["days"] == 5
    assert m["main_sum_yi"] == -51.04
    assert m["today_yi"] == -30.69
    assert m["accel_yi"] == -20.49
    assert len(m["window"]) == 5


def test_trend_metrics_degrades_on_short_history():
    """样本不足 3 日 → None（不硬判持续性）。"""
    assert sfs._trend_metrics(_series([1e8, 2e8])) is None
    assert sfs._trend_metrics([]) is None
    # 净额为 None（缺失）也算不可判
    assert sfs._trend_metrics([{"date": "x", "main_net": None}] * 4) is None


def test_trend_metrics_super_share_none_when_absent():
    """超大单净额缺失时 super_share 落None，不能折成 0。"""
    rows = _series([1e8, 1e8, 1e8, 1e8, 1e8])
    for r in rows:
        r["super_net"] = None
    m = sfs._trend_metrics(rows)
    assert m["super_share"] is None


def test_acceleration_detects_reversal_that_daily_ranking_misses():
    """核心用例：当日净额看着在流入，但窗口已翻负 → 必须判撤离而不是加速。

    这正是本模块存在的理由（实测国防军工 10-13 +19.3亿 → 10-15 -30.7亿）。
    只看当日排行会在这两天给出方向相反的答案。
    """
    daily = _series([-30e8, -12e8, -5e8, +2e8, +8e8])
    m = sfs._trend_metrics(daily)
    assert m["today_yi"] == 8.0            # 今日是流入
    assert m["main_sum_yi"] < 0            # 但窗口累计为负
    assert sfs._state(m, 8e8, 0.9, 0.9) == "follow_exit"


# ─────────────────────────────── ④ 降级路径


def test_fetch_rank_returns_degraded_not_raise(monkeypatch):
    """端点全失败 → 返回结构完整的降级载荷，不抛异常到路由。"""
    def _boom(*a, **k):
        raise RuntimeError("取数失败")
    monkeypatch.setattr(sfs, "_get_json", _boom)
    out = sfs._fetch_rank()
    assert out["available"] is False
    assert out["rows"] == []
    assert out["note"]


def test_fetch_rank_enters_cooldown_after_failure(monkeypatch):
    """端点失败后进冷却，冷却期内直接返回、不再打源（防自造风控）。"""
    calls = {"n": 0}

    def _boom(*a, **k):
        calls["n"] += 1
        raise RuntimeError("取数失败")
    monkeypatch.setattr(sfs, "_get_json", _boom)
    sfs._fetch_rank()
    before = calls["n"]
    sfs._fetch_rank()
    assert calls["n"] == before, "冷却期内不应再打源"
    assert "冷却" in sfs._fetch_rank()["note"]


def test_get_sector_follow_degrades_when_rank_unavailable(monkeypatch):
    """排行不可用 → 降级载荷必须带齐结构字段，异常不外抛。"""
    async def _rank(force=False):
        return {"rows": [], "available": False, "complete": False, "note": "端点不可用"}
    monkeypatch.setattr(sfs, "get_rank", _rank)
    out = asyncio.run(sfs.get_sector_follow())
    assert out["available"] is False
    assert out["sectors"] == []
    assert out["caveats"]
    assert out["states"]["follow_accel"] == "加速流入"


def test_get_sector_follow_degrades_when_all_daily_fail(monkeypatch):
    """排行可用但日线全挂 → 仍返回板块，trend_available=False（不假装有四态依据）。"""
    async def _rank(force=False):
        return {
            "rows": [
                {"code": "BK1204", "name": "国防军工", "change_pct": 1.0, "main_net": 5e8,
                 "main_pct": 2.0, "super_pct": 1.0, "large_pct": 1.0,
                 "up_count": 100, "down_count": 20, "leader_name": None, "leader_code": None,
                 "leader_change_pct": None, "laggard_name": None, "laggard_code": None},
            ],
            "available": True, "complete": True, "note": "",
        }
    async def _daily(code):
        return None
    monkeypatch.setattr(sfs, "get_rank", _rank)
    monkeypatch.setattr(sfs, "get_daily", _daily)
    out = asyncio.run(sfs.get_sector_follow())
    assert out["available"] is True
    assert out["trend_available"] is False
    assert out["sectors"][0]["trend_available"] is False


def test_get_sector_follow_tolerates_single_daily_exception(monkeypatch):
    """单板块日线抛异常只降级该条，不整批中断（漏一个会把整批陪葬）。"""
    async def _rank(force=False):
        return {
            "rows": [
                {"code": f"BK12{i:02d}", "name": f"板块{i}", "change_pct": 1.0, "main_net": float(i + 1) * 1e8,
                 "main_pct": 2.0, "super_pct": 1.0, "large_pct": 1.0,
                 "up_count": 100, "down_count": 20, "leader_name": None, "leader_code": None,
                 "leader_change_pct": None, "laggard_name": None, "laggard_code": None}
                for i in range(3)
            ],
            "available": True, "complete": True, "note": "",
        }

    async def _daily(code):
        if code == "BK1201":
            raise RuntimeError("单板块失败")
        return _series([1e8, 2e8, 3e8, 4e8, 5e8])
    monkeypatch.setattr(sfs, "get_rank", _rank)
    monkeypatch.setattr(sfs, "get_daily", _daily)
    out = asyncio.run(sfs.get_sector_follow())
    assert out["available"] is True
    assert len(out["sectors"]) == 3
    bad = [s for s in out["sectors"] if s["code"] == "BK1201"][0]
    assert bad["trend_available"] is False


def test_sectors_sorted_by_state_then_strength(monkeypatch):
    """展示排序：先按四态（加速 → 持续 → 退潮 → 撤离），同态按窗口累计净额降序。"""
    async def _rank(force=False):
        def row(code, name, net):
            return {"code": code, "name": name, "change_pct": 1.0, "main_net": net,
                    "main_pct": 2.0, "super_pct": 1.0, "large_pct": 1.0,
                    "up_count": 100, "down_count": 20, "leader_name": None, "leader_code": None,
                    "leader_change_pct": None, "laggard_name": None, "laggard_code": None}
        return {"rows": [row("BK1201", "A", 1e8), row("BK1202", "B", 9e8), row("BK1203", "C", 5e8)],
                "available": True, "complete": True, "note": ""}
    maps = {
        "BK1201": _series([-5e8] * 5),                    # 撤离
        "BK1202": _series([1e8, 2e8, 3e8, 9e8, 9e8]),     # 加速
        "BK1203": _series([2e8] * 5),                      # 持续（加速度中位）
    }

    async def _daily(code):
        return maps[code]
    monkeypatch.setattr(sfs, "get_rank", _rank)
    monkeypatch.setattr(sfs, "get_daily", _daily)
    out = asyncio.run(sfs.get_sector_follow())
    order = [s["code"] for s in out["sectors"]]
    assert order[0] == "BK1202", f"加速流入应排最前，实得{order}"


# ─────────────────────────────── ⑤ 缓存与不变量


def test_rank_cache_hit_avoids_refetch(monkeypatch):
    """命中缓存不重打源。"""
    calls = {"n": 0}

    def _payload(*a, **k):
        calls["n"] += 1
        return {"data": {"total": 1, "diff": [
            {"f12": "BK1204", "f14": "国防军工", "f62": 1e8, "f184": 1.0},
        ]}}
    monkeypatch.setattr(sfs, "_get_json", _payload)
    asyncio.run(sfs.get_rank())
    n1 = calls["n"]
    asyncio.run(sfs.get_rank())
    assert calls["n"] == n1


def test_degraded_rank_uses_short_ttl(monkeypatch):
    """降级结果只短缓存（留自愈），不能按正常 TTL 把故障钉死 10 分钟。"""
    monkeypatch.setattr(sfs, "_get_json", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    asyncio.run(sfs.get_rank())
    assert sfs._rank_cache is not None
    cached_at, ttl, _ = sfs._rank_cache
    assert ttl == sfs._TTL_DEGRADED
    assert ttl < sfs._RANK_TTL


def test_force_respects_min_interval(monkeypatch):
    """force 连点受最小间隔保护 —— refresh 不能变成打源。"""
    calls = {"n": 0}

    def _payload(*a, **k):
        calls["n"] += 1
        return {"data": {"total": 1, "diff": [
            {"f12": "BK1204", "f14": "国防军工", "f62": 1e8, "f184": 1.0},
        ]}}
    monkeypatch.setattr(sfs, "_get_json", _payload)
    asyncio.run(sfs.get_rank())
    n1 = calls["n"]
    asyncio.run(sfs.get_rank(force=True))
    assert calls["n"] == n1, "最小间隔内的 force 应直接回缓存"


def test_caveats_cover_the_four_known_traps():
    """免责口径必须覆盖四个已知陷阱，且随接口下发（前端要渲染）。"""
    joined = " ".join(sfs.CAVEATS)
    assert "超大单 + 大单" in joined      # 不是真实暗盘
    assert "估算" in joined               # 板块资金流是估算值
    assert "不可跨日比较" in joined        # 横截面分位换日换基准
    assert "不是买卖信号" in joined        # 结构读数不是信号


def test_service_never_enters_evidence_or_llm_ctx():
    """不变量：本模块只读资金结构，不得接入证据分或 LLM ctx。

    只检查**可执行代码**：把模块 docstring 摘掉再断言，否则说明文字里的
    「不进 evidence_score」会把自己判失败。
    """
    import pathlib
    import re

    src = pathlib.Path(sfs.__file__).read_text(encoding="utf-8")
    code = re.sub(r'^"""[\s\S]*?"""', "", src, count=1)   # 摘掉模块 docstring
    code = re.sub(r'"""[\s\S]*?"""', "", code)            # 再摘掉函数 docstring

    for forbidden in ("evidence_score", "tactic_evidence", "llm_service", "decision.make"):
        assert forbidden not in code, f"发现 {forbidden}：读数不得接入决策/证据链路"


def test_trend_top_n_bounds_request_volume():
    """时序只拉 Top N —— 496 全拉必触发风控，请求量必须有闸门。"""
    assert 0 < sfs._TREND_TOP_N <= 40
    assert sfs._TREND_TOP_N < sfs._DISPLAY_SIZE * 4


def test_state_distribution_counts_all_ranked_not_just_displayed():
    """四态分布按**参与判定的全量**统计，不能只统计展示的 12 条。

    否则「显示 12 条里撤离 8 条」会被读成「全部板块都在撤离」，而实际比例完全不同。
    """
    async def _rank(force=False):
        return {
            "rows": [
                {"code": f"BK20{i:02d}", "name": f"板块{i}", "change_pct": 1.0, "main_net": float(i + 1) * 1e8,
                 "main_pct": 2.0, "super_pct": 1.0, "large_pct": 1.0,
                 "up_count": 100, "down_count": 20, "leader_name": None, "leader_code": None,
                 "leader_change_pct": None, "laggard_name": None, "laggard_code": None}
                for i in range(20)
            ],
            "available": True, "complete": True, "note": "",
        }

    async def _daily(code):
        idx = int(code[4:])
        # 前半持续净流入、后半窗口转负 —— 保证四态都出现
        return _series([1e8] * 5) if idx < 10 else _series([-1e8] * 5)
    import unittest.mock as m
    with m.patch.object(sfs, "get_rank", _rank), m.patch.object(sfs, "get_daily", _daily):
        out = asyncio.run(sfs.get_sector_follow())

    total_dist = sum(out["state_distribution"].values())
    assert total_dist == out["ranked_sectors"] == 20, "分布必须覆盖全部参与判定的板块"
    assert len(out["sectors"]) == min(20, sfs._DISPLAY_SIZE)
    assert total_dist > len(out["sectors"]), "样本多于展示条数时分布不应等于展示条数"


def test_sample_note_discloses_inflow_bias(monkeypatch):
    """取样口径必须下发：样本是「当日流入前 N 名」，天然偏流入端。

    不披露的话「撤离占比高」会被读成「全市场都在撤离」—— 实测展示 12 条里
    11 条撤离，而这只是流入榜的正常分布。
    """
    async def _rank(force=False):
        return {
            "rows": [
                {"code": f"BK30{i:02d}", "name": f"板块{i}", "change_pct": 1.0, "main_net": 5e8,
                 "main_pct": 2.0, "super_pct": 1.0, "large_pct": 1.0,
                 "up_count": 100, "down_count": 20, "leader_name": None, "leader_code": None,
                 "leader_change_pct": None, "laggard_name": None, "laggard_code": None}
                for i in range(4)
            ],
            "available": True, "complete": True, "note": "",
        }

    async def _daily(code):
        return _series([-1e8] * 5)
    import unittest.mock as m
    with m.patch.object(sfs, "get_rank", _rank), m.patch.object(sfs, "get_daily", _daily):
        out = asyncio.run(sfs.get_sector_follow())

    assert out["state_distribution"].get("撤离") == 4
    note = out["sample_note"]
    assert "流入" in note and "不代表全市场" in note, f"取样口径说明缺失：{note}"


def test_degraded_payload_has_same_shape():
    """降级载荷字段集与正常载荷一致 —— 前端不能因为降级就崩。"""
    import unittest.mock as m
    async def _rank(force=False):
        return {"rows": [], "available": False, "complete": False, "note": "端点不可用"}
    with m.patch.object(sfs, "get_rank", _rank):
        out = asyncio.run(sfs.get_sector_follow())
    for key in ("sectors", "available", "complete", "total_sectors", "ranked_sectors",
                "trend_available", "state_distribution", "sample_note", "note", "caveats", "states"):
        assert key in out, f"降级载荷缺字段 {key}"