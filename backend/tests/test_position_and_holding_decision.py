"""仓位决策（position_service，A）与持仓决策层（holding_decision_service，B）的用例。

分四组：① 仓位：只降档不上调（核心不变量）② 仓位：决策四要素与板块名单
③ 持仓：四态可分 + 结构位锚定 ④ 红线：不接入证据分 / LLM ctx、禁契约外文案。

⚠️ 组 ① 的「只降档」是本模块最重要的不变量：方向分、情绪温度、板块资金三者
高度相关（同一轮行情的不同切面），相加等于把同一个信号放大 N 倍 ——
``MEMORY-FEATURES`` 第 7.5 节点名的问题。所以测试直接断言
``cap <= base_cap`` 而不是只测几个样例。
"""
from __future__ import annotations

import itertools
import pathlib
import re

import pytest

from app.services import decision, holding_decision_service as hds, position_service as ps

_SECTOR_FOLLOW_OK = {
    "available": True,
    "sectors": [
        {"code": "BK1036", "name": "半导体", "state": "follow_accel"},
        {"code": "BK1204", "name": "国防军工", "state": "follow_exit"},
        {"code": "BK0451", "name": "房地产开发", "state": "follow_ebb"},
    ],
}


def _holding(**kw):
    base = {
        "code": "000001",
        "name": "平安银行",
        "price": 10.0,
        "pnl_pct": 0.0,
        "position_pct": 5.0,
        "signal": {"support": 9.5, "resistance": 11.0, "stop_loss": 9.0},
        "tactics": [],
    }
    base.update(kw)
    return base


# ─────────────────────────────── ① 仓位：只降档不上调


@pytest.mark.parametrize("score", [2.0, 3.0, 4.0, 4.9, 5.0, 5.4, 5.5, 6.0, 6.9, 7.0, 9.5, None])
@pytest.mark.parametrize("break_rate", [None, 0.0, 15.0, 22.0, 35.0, 60.0])
@pytest.mark.parametrize("limit_up", [None, 5, 30, 80])
def test_position_cap_never_exceeds_base(score, break_rate, limit_up):
    """核心不变量：情绪与板块只能**降档**，不能把仓位顶上去。

    方向分、情绪、板块是同一轮行情的不同切面，高度相关；若允许相加/上调，
    一次亢奋日会把三个同向信号叠成激进仓位。测试遍历组合而非抽样，
    因为这类 bug 恰好只在某些组合下露头。
    """
    sentiment = None
    if break_rate is not None or limit_up is not None:
        sentiment = {"break_rate": break_rate, "limit_up_count": limit_up}
    plan = ps.build_position_plan(score, "上涨", sentiment, _SECTOR_FOLLOW_OK)
    assert plan["position_cap"] <= plan["basis"]["base_cap"], (
        f"score={score} br={break_rate} lu={limit_up} 出现了上调"
    )
    assert 1 <= plan["position_cap"] <= 7


def test_sentiment_penalty_is_non_negative():
    """降档成数永不为负（负 penalty 等于上调）。"""
    for br in (None, 0.0, 10.0, 22.0, 35.0, 99.0):
        for lu in (None, 0, 5, 30, 100):
            penalty, _ = ps._sentiment_penalty({"break_rate": br, "limit_up_count": lu})
            assert penalty >= 0, f"br={br} lu={lu} → penalty={penalty}"


def test_missing_score_uses_neutral_not_zero():
    """方向分缺失按中性 4 成起算，不能按 0 —— 缺数据不等于看空。"""
    assert ps._base_cap(None) == 4
    assert ps._base_cap(5.0) == 4


# ─────────────────────────────── ② 仓位：决策四要素与板块名单


def test_position_plan_has_full_decision_quad():
    """四要素齐备：缺 trigger/invalidation 就只是一句建议，不是决策。"""
    plan = ps.build_position_plan(7.5, "上涨", {"break_rate": 5.0, "limit_up_count": 60}, _SECTOR_FOLLOW_OK)
    for k in ("action", "label", "reason", "trigger", "invalidation"):
        assert plan[k], f"缺 {k}"
    # 动作与标签必须自洽（前端 DecisionBadge 以 label 为锚）
    assert plan["label"] == decision.DECISION_LONG_LABEL[plan["action"]]
    assert decision.is_decision(plan["action"])


def test_position_action_comes_from_contract():
    """动作必须落在 decision 6 态内，不得自造。"""
    for score in (1.0, 3.0, 5.0, 6.5, 8.0, None):
        plan = ps.build_position_plan(score, "x", None, None)
        assert decision.is_decision(plan["action"]), plan["action"]
        assert plan["label"] == decision.DECISION_LONG_LABEL[plan["action"]]


def test_sector_lists_take_names_not_ranks():
    """板块名单只取**名字**，不把横截面分位搬过来（分位换日换基准，不可跨日比较）。"""
    plan = ps.build_position_plan(6.0, "上涨", None, _SECTOR_FOLLOW_OK)
    assert plan["sectors_long"] == ["半导体"]
    assert plan["sectors_avoid"] == ["国防军工"]
    # 名单里不得出现任何分位数
    blob = " ".join(plan["sectors_long"] + plan["sectors_avoid"])
    assert not re.search(r"\d\.\d{2,}", blob), "名单里混进了分位数"


def test_sector_lists_degrade_when_unavailable():
    """板块数据不可用时给空名单 + 说明，不编造方向。"""
    plan = ps.build_position_plan(6.0, "上涨", None, None)
    assert plan["sectors_long"] == []
    assert plan["sectors_avoid"] == []
    assert plan["basis"]["sector_note"]
    assert plan["basis"]["sector_note"] != ""


def test_sector_lists_capped():
    """名单有上限，不把半个市场都列成「可参与」。"""
    many = {
        "available": True,
        "sectors": [{"name": f"板块{i}", "state": "follow_accel"} for i in range(30)],
    }
    plan = ps.build_position_plan(7.0, "上涨", None, many)
    assert len(plan["sectors_long"]) <= ps._SECTOR_LONG_MAX
    assert len(plan["sectors_avoid"]) <= ps._SECTOR_AVOID_MAX


def test_disclaimer_is_kept():
    """免责句不属于模棱两可，按 decision.py 纪律必须保留。"""
    plan = ps.build_position_plan(5.0, "震荡", None, None)
    assert "不是收益预测" in plan["disclaimer"]


def test_trigger_at_max_cap_is_not_self_referential():
    """已在最高档（7 成）时 trigger 不得说「加至 7 成」—— 那是自指。

    实测边界：方向分 9.5 → cap=7，若照搬通用模板会出现「可加至 7 成」。
    """
    plan = ps.build_position_plan(9.5, "上涨", None, None)
    assert plan["position_cap"] == ps._MAX_CAP
    assert "加至 7 成" not in plan["trigger"]
    assert "维持" in plan["trigger"]


def test_invalidation_at_min_cap_is_not_self_contradictory():
    """已在最低档（1 成）时不得说「降到 1 成」—— 自相矛盾。

    实测边界：方向分 3.79 + 炸板率 44% → cap=1，通用模板会输出「降到 1 成」。
    """
    plan = ps.build_position_plan(3.79, "下跌", {"break_rate": 44.0, "limit_up_count": 50}, None)
    assert plan["position_cap"] == ps._MIN_CAP
    assert "降到 1 成" not in plan["invalidation"]
    assert "清仓" in plan["invalidation"]


def test_mid_cap_uses_generic_template():
    """中档仍走通用模板（加一档 / 降两档），确认没有把边界逻辑写歪。"""
    plan = ps.build_position_plan(5.5, "震荡", None, None)
    assert plan["position_cap"] == 5
    assert "可加至 6 成" in plan["trigger"]
    assert "降到 3 成" in plan["invalidation"]


# ─────────────────────────────── ③ 持仓：四态 + 结构位锚定


def test_all_four_holding_states_reachable():
    """四态必须真的分得开 —— 否则这层决策只是换了说法的两层提示。"""
    reached = set()
    for price, pnl, pos, sector in itertools.product(
        (8.8, 9.2, 9.8, 10.5, None), (0.0, 15.0, -5.0), (5.0, 25.0), (None, "follow_exit")
    ):
        it = _holding(price=price, pnl_pct=pnl, position_pct=pos)
        reached.add(hds._decide_one(it, sector)["action"])
    reached.add(hds._decide_one({"code": "x", "price": 1.0, "signal": {}, "tactics": []})["action"])
    assert {"sell", "reduce", "hold", "skip"} <= reached


def test_sell_triggers_on_stop_loss_only():
    """卖出只认止损位（结构位），不看浮盈 —— 沉没成本不参与决策。"""
    for pnl in (-30.0, -5.0, 0.0, 5.0, 50.0):
        d = hds._decide_one(_holding(price=8.8, pnl_pct=pnl))
        assert d["action"] == "sell", f"浮盈 {pnl} 影响了止损判定"
        assert "8.8" in d["reason"] and "9.0" in d["reason"]


def test_reduce_on_support_break():
    """跌破主支撑 → 减仓，且 trigger 反映真实原因。"""
    d = hds._decide_one(_holding(price=9.2))
    assert d["action"] == "reduce"
    assert "主支撑" in d["trigger"]


def test_reduce_on_pullback_from_resistance_not_cost_multiple():
    """止盈锚在**压力位**而不是「成本价 × 1.2」。

    本项目铁律：买卖点必须是结构位，禁「现价×系数」—— 系数法实测在 70~83%
    的样本上退化成现价∓1%。
    """
    # 浮盈 15% 但已从压力位 11.0 回落超 5%（现价 10.3）
    d = hds._decide_one(_holding(price=10.3, pnl_pct=15.0))
    assert d["action"] == "reduce"
    assert "压力位" in d["reason"]
    assert "11.0" in d["reason"]
    # 同样的浮盈，但现价仍在压力位附近（10.9 > 11.0*0.95）→ 不因此降档
    d2 = hds._decide_one(_holding(price=10.9, pnl_pct=15.0))
    assert d2["action"] == "hold", "离压力位还近就减仓，等于用系数法"


def test_reduce_when_sector_exiting_with_profit():
    """板块资金撤离 + 有浮盈 → 提高减仓优先级（这是 B 接板块四态的意义）。"""
    d = hds._decide_one(_holding(price=10.5, pnl_pct=8.0), "follow_exit")
    assert d["action"] == "reduce"
    assert "撤离" in d["reason"]
    # 板块撤离但没浮盈 → 不因此赶人（一天正常波动不该触发减仓）
    d2 = hds._decide_one(_holding(price=10.5, pnl_pct=1.0), "follow_exit")
    assert d2["action"] == "hold"


def test_hold_when_structure_intact():
    """结构完好 → 持有，且 trigger 给出转为减仓/卖出的价位。"""
    d = hds._decide_one(_holding(price=10.5))
    assert d["action"] == "hold"
    assert "9.5" in (d["trigger"] or "")


def test_skip_when_signal_missing():
    """样本不足 → 明说不参与，不用「持有不动」冒充。"""
    d = hds._decide_one({"code": "x", "name": "x", "price": 10.0, "signal": {}, "tactics": []})
    assert d["action"] == "skip"
    assert d["label"] == decision.DECISION_LONG_LABEL["skip"]


def test_decisions_sorted_risk_first():
    """排序：风险处置先于开仓（sell → reduce → hold → skip）。"""
    items = [
        _holding(code="A", price=10.5),
        _holding(code="B", price=8.8),
        _holding(code="C", price=9.2),
        {"code": "D", "name": "D", "price": 1.0, "signal": {}, "tactics": []},
    ]
    out = hds.build_holding_decisions(items)
    assert [x["code"] for x in out] == ["B", "C", "A", "D"]


def test_summary_counts_without_weighted_score():
    """汇总只计数，不做加权打分 —— 各票结构位/浮盈/板块状态不可比。"""
    out = hds.build_holding_decisions([_holding(code="A", price=8.8), _holding(code="B", price=10.5)])
    s = hds.summarize(out)
    assert s["counts"]["sell"] == 1 and s["counts"]["hold"] == 1
    assert "不是收益预测" in s["disclaimer"]


def test_build_decisions_maps_sector_state():
    """板块名 → 四态映射正确；未知板块按 None 处理（该维不参与，其余照常）。"""
    items = [_holding(code="A", price=10.5, pnl_pct=8.0, sector="国防军工")]
    out = hds.build_holding_decisions(items, _SECTOR_FOLLOW_OK)
    assert out[0]["sector_state"] == "follow_exit"
    assert out[0]["decision"]["action"] == "reduce"


def test_build_decisions_tolerates_missing_sector_follow():
    """板块数据不可用 → 全部按 None，不抛异常、不整批降级。"""
    out = hds.build_holding_decisions([_holding(code="A", price=10.5)], None)
    assert out[0]["sector_state"] is None
    assert out[0]["decision"]["action"] == "hold"


# ─────────────────────────────── ④ 红线


@pytest.mark.parametrize("module", [ps, hds])
def test_never_enters_evidence_or_llm_ctx(module):
    """不变量：两个新服务都不得接入证据分或 LLM 上下文。"""
    src = pathlib.Path(module.__file__).read_text(encoding="utf-8")
    code = re.sub(r'"""[\s\S]*?"""', "", src)   # 摘掉 docstring 再断言
    for forbidden in ("evidence_score", "tactic_evidence", "llm_service", "decision.make("):
        if forbidden == "decision.make(":
            continue   # 这是允许的入口
        assert forbidden not in code, f"{module.__name__} 出现 {forbidden}"


@pytest.mark.parametrize("module", [ps, hds])
def test_no_forbidden_wording(module):
    """契约文案禁令：禁「观察/关注/留意/跟踪/观望」。

    只查**输出侧**（reason/trigger/invalidation 的构造），docstring 里引用反例是正当的。
    """
    banned = ("观察", "关注", "留意", "跟踪", "观望")
    if module is ps:
        payloads = [
            ps.build_position_plan(5.0, "x", None, None),
            ps.build_position_plan(7.5, "x", {"break_rate": 40.0, "limit_up_count": 5}, _SECTOR_FOLLOW_OK),
        ]
        texts = [p["reason"] + p["trigger"] + p["invalidation"] for p in payloads]
    else:
        payloads = [
            hds._decide_one(_holding(price=10.5)),
            hds._decide_one(_holding(price=8.8)),
            hds._decide_one(_holding(price=9.2, pnl_pct=20.0), "follow_exit"),
            hds._decide_one({"code": "x", "price": 1.0, "signal": {}, "tactics": []}),
        ]
        texts = [p["reason"] + (p["trigger"] or "") + (p["invalidation"] or "") for p in payloads]
    for t in texts:
        for w in banned:
            assert w not in t, f"出现契约禁用词「{w}」: {t[:80]}"


@pytest.mark.parametrize("module", [ps, hds])
def test_output_actions_are_contract_decisions(module):
    """产出的动作必须可被 decision 契约识别（前端 DecisionBadge 以此为锚）。"""
    if module is ps:
        plans = [ps.build_position_plan(s, "x", None, None) for s in (2.0, 5.0, 8.0, None)]
        actions = [p["action"] for p in plans]
    else:
        items = [
            hds._decide_one(_holding(price=8.8)),
            hds._decide_one(_holding(price=9.2)),
            hds._decide_one(_holding(price=10.5)),
            hds._decide_one({"code": "x", "price": 1.0, "signal": {}, "tactics": []}),
        ]
        actions = [p["action"] for p in items]
    for a in actions:
        assert decision.is_decision(a), a
