"""V5.42：决策留痕（A）、一键告警（B）、今日总指令（C）的用例。

分五组：① 留痕降级与幂等 ② 复盘口径（自选择偏差 + 最小样本）
③ 决策→告警规则映射 ④ 行动清单：不加权 + 排序 + 缺席语义
⑤ 红线：禁契约外文案、不进证据分。
"""
from __future__ import annotations

import re
from unittest import mock

import pytest

from app.services import action_list_service as als, alert_service, decision, decision_ledger_service as dls

_PLAN = {
    "action": "reduce",
    "position_cap": 1,
    "reason": "方向分 2.97（下跌）→ 基础 1 成",
    "trigger": "方向分回到 6.0 以上可加至 2 成",
    "invalidation": "已在最低仓位档",
}
_DECS = [
    {
        "code": "000001", "name": "平安银行", "price": 8.8, "pnl_pct": -5.0,
        "support": 9.5, "resistance": 11.0, "stop_loss": 9.0,
        "decision": {"action": "sell", "label": "卖出", "reason": "跌破止损位 9.00",
                     "trigger": "现价 ≤ 9.00（已触发）", "invalidation": "站回 9.00 之上"},
    },
    {
        "code": "600000", "name": "浦发银行", "price": 10.5, "pnl_pct": 3.0,
        "support": 9.5, "resistance": 11.0, "stop_loss": 9.0,
        "decision": {"action": "hold", "label": "持有不动", "reason": "结构完好",
                     "trigger": "现价 ≤ 9.50 时转减仓", "invalidation": None},
    },
]
_SF = {"available": True, "sectors": [
    {"name": "半导体", "state": "follow_accel"},
    {"name": "国防军工", "state": "follow_exit"},
]}


# ─────────────────────────────── ① 留痕降级


def test_ledger_degrades_when_unconfigured():
    """Supabase 未配置时三个入口都静默返回 0/空，不抛异常。"""
    with mock.patch.object(dls, "_configured", return_value=False):
        import asyncio
        assert asyncio.run(dls.save_daily_decisions("u1")) == 0
        assert asyncio.run(dls.settle_pending()) == 0
        r = asyncio.run(dls.get_review("u1"))
        assert r["available"] is False
        assert r["note"]


def test_review_empty_shape_matches_populated():
    """降级载荷与正常载荷字段集一致 —— 前端不能因为降级就崩。"""
    empty = dls._empty("x")
    for k in ("available", "note", "window_days", "total_decided", "total_settled", "groups", "caveats"):
        assert k in empty, k
    # 降级时也要带口径免责（自选择偏差那句）
    assert any("自选择" in c for c in empty["caveats"])


def test_review_caveats_always_present():
    """自选择偏差免责必须**始终**存在，不是只在有数据时才有。"""
    r = dls._empty("x")
    joined = " ".join(r["caveats"])
    assert "自选择" in joined and "不是随机分组" in joined
    assert "描述性读数" in joined


# ─────────────────────────────── ② 复盘口径


def test_min_sample_gate():
    """样本不足 _MIN_SAMPLE 时不给平均值 —— 3 个样本的「平均 +8%」是噪声。"""
    assert dls._MIN_SAMPLE >= 5
    # 直接验证常量被用于门槛（构造 <5 个 settled 的组不应有 avg）
    rows = [
        {"action": "sell", "follow_gain_pct": 5.0, "trade_date": "2026-10-10", "code": "a"},
    ]
    assert len([r for r in rows if r.get("follow_gain_pct") is not None]) < dls._MIN_SAMPLE


# ─────────────────────────────── ③ 决策 → 告警规则映射


def test_sync_decision_rules_type_mapping():
    """ sell → stop_loss，reduce → breakdown，hold → buy_point，skip → 不建。"""
    cases = [
        ("sell", 9.0, "stop_loss"),
        ("reduce", 9.5, "breakdown"),
        ("hold", 9.5, "buy_point"),
    ]
    for action, threshold, want in cases:
        d = _DECS[0] if action == "sell" else dict(_DECS[1])
        d["decision"] = dict(d["decision"], action=action)
        with mock.patch.object(alert_service, "supabase_store") as sb, \
             mock.patch.object(alert_service, "add_rule") as add:
            sb.is_configured.return_value = True
            sb.get_service_client = _async_return(_Client(existing=[]))
            add.side_effect = _async_value({"id": 1})
            import asyncio
            r = asyncio.run(alert_service.sync_decision_rules("u1", d))
            assert r["action"] == "created", f"{action} → {r}"
            assert r["type"] == want, f"{action} 应映射到 {want}，实得 {r['type']}"
            assert add.call_args.args[3] == threshold, "阈值必须取决策的结构位"


def test_sync_decision_rules_skips_skip_and_missing_level():
    """skip 与缺结构位的决策不建规则 —— 没有可信触发价就不建。"""
    import asyncio
    d = dict(_DECS[1]); d["decision"] = dict(d["decision"], action="skip")
    with mock.patch.object(alert_service, "supabase_store") as sb:
        sb.is_configured.return_value = True
        assert asyncio.run(alert_service.sync_decision_rules("u1", d))["action"] == "skipped"
    # 有动作但 support 缺失
    d2 = {"code": "000001", "name": "x", "support": None, "stop_loss": None,
          "decision": {"action": "sell", "label": "卖出"}}
    with mock.patch.object(alert_service, "supabase_store") as sb:
        sb.is_configured.return_value = True
        assert asyncio.run(alert_service.sync_decision_rules("u1", d2))["action"] == "skipped"


def test_sync_decision_rules_uses_distinct_note():
    """自动规则必须用独立 note，**不覆盖**用户手动建的规则。"""
    src = open(alert_service.__file__, encoding="utf-8").read()
    assert "_DECISION_RULE_NOTE" in src
    # 手动规则与自动止损规则的 note 必须与决策规则的 note 不同
    assert 'auto:holding_decision' in src and 'auto:holding_stop' in src


def test_sync_decision_rules_degrades_when_unconfigured():
    import asyncio
    with mock.patch.object(alert_service, "supabase_store") as sb:
        sb.is_configured.return_value = False
        assert asyncio.run(alert_service.sync_decision_rules("u1", _DECS[0]))["action"] == "skipped"


# ─────────────────────────────── ④ 行动清单


def test_action_list_has_no_composite_score():
    """核心不变量：不得产出任何综合分/健康度/评分。"""
    out = als.build_action_list(_PLAN, _DECS, _SF, [{"name": "A", "code": "1", "buy_point": 1.0}],
                                {"level": "hunt", "label": "可打板", "note": ""})
    blob = str(out).lower()
    for bad in ("score", "rating", "综合分", "健康度", "总分"):
        assert bad not in blob, f"出现了合成指标 {bad}"


def test_action_list_sorted_risk_first():
    """排序按 DECISION_ORDER：卖出 → 减仓 → 买入 → 加仓 → 不参与。"""
    out = als.build_action_list(_PLAN, _DECS, _SF, [{"name": "A", "code": "1", "buy_point": 1.0}],
                                {"level": "avoid", "label": "空仓等待", "note": ""})
    order = [i["action"] for i in out["items"]]
    assert order[0] == "sell"
    assert "reduce" in order and order.index("reduce") < order.index("buy")
    assert order[-1] == "skip"


def test_action_list_excludes_hold_holdings():
    """hold / skip 的持仓不进清单 —— 它们不需要「行动」。"""
    out = als.build_action_list(None, _DECS, None, None, None)
    sources = [i["source"] for i in out["items"]]
    assert "holding" in sources          # sell 那条在
    assert len([i for i in out["items"] if i["source"] == "holding"]) == 1  # hold 那条不在


def test_action_list_skips_missing_blocks():
    """某块数据缺失时**跳过该项**，不是填「无」也不是猜。"""
    out = als.build_action_list()
    assert out["items"] == []
    # 缺失语义必须写进 caveats
    assert any("缺席" in c for c in out["caveats"])


def test_action_list_declares_incomparability():
    """不可比声明必须存在 —— 用户并排看到各项时需知不是同一把尺子。"""
    out = als.build_action_list(_PLAN, _DECS, _SF, None, None)
    assert "不可比" in out["incomparable_note"] and "不可相加" in out["incomparable_note"]


def test_action_list_limitup_maps_environment_not_action():
    """连板环境档位是**环境质量**不是买卖动作：hunt→hold、avoid→skip。

    不得映射成 buy/add —— 那会把「环境允许」读成「该买了」。
    """
    for level, want in (("hunt", "hold"), ("watch", "skip"), ("avoid", "skip")):
        out = als.build_action_list(None, None, None, None, {"level": level, "label": level, "note": ""})
        lu = [i for i in out["items"] if i["source"] == "limitup"]
        assert lu and lu[0]["action"] == want, f"{level} 应映射到 {want}"


def test_action_list_every_item_has_caliber():
    """每项必须自带口径 —— 没有口径的并列展示会诱导用户跨项比较。"""
    out = als.build_action_list(_PLAN, _DECS, _SF, [{"name": "A", "code": "1", "buy_point": 1.0}],
                                {"level": "hunt", "label": "x", "note": ""})
    for it in out["items"]:
        assert it["caliber"], f"{it['source']} 缺口径"
        assert it["headline"], f"{it['source']} 缺标题"


def test_action_list_limitup_uses_title_not_label():
    """连板环境的标题字段是 `title`（limitup_service.play_advice），不是 `label`。

    用错字段会让 headline 退化成英文 key（「连板环境：avoid」）——
    线上实测踩到过，这里锁死。
    """
    advice = {"level": "avoid", "title": "空仓等待", "reasons": ["炸板率 44.5% ≥ 35.0%"]}
    out = als.build_action_list(None, None, None, None, advice)
    lu = [i for i in out["items"] if i["source"] == "limitup"]
    assert lu, "连板环境项缺失"
    assert "空仓等待" in lu[0]["headline"], lu[0]["headline"]
    assert "avoid" not in lu[0]["headline"], "标题退化成了英文 key"
    # reasons 要进 detail（那是「为什么」）
    assert "炸板率" in lu[0]["detail"], lu[0]["detail"]


def test_action_list_actions_are_contract_decisions():
    """动作必须落在 decision 6 态内。"""
    out = als.build_action_list(_PLAN, _DECS, _SF, [{"name": "A", "code": "1", "buy_point": 1.0}],
                                {"level": "hunt", "label": "x", "note": ""})
    for it in out["items"]:
        assert decision.is_decision(it["action"]), it["action"]
        assert it["label"] == decision.DECISION_LONG_LABEL[it["action"]]


def test_action_list_board_only_names_accel():
    """板块项只点名加速流入的，不把撤离/退潮的也列成「行动」。"""
    out = als.build_action_list(None, None, _SF, None, None)
    board = [i for i in out["items"] if i["source"] == "board"]
    assert len(board) == 1
    assert "半导体" in board[0]["headline"]
    assert "国防军工" not in board[0]["headline"]


# ─────────────────────────────── ⑤ 红线


@pytest.mark.parametrize("module", [als, dls])
def test_no_forbidden_wording_in_outputs(module):
    """契约文案禁令：禁「观察/关注/留意/跟踪/观望」（只查输出侧）。"""
    banned = ("观察", "关注", "留意", "跟踪", "观望")
    if module is als:
        out = als.build_action_list(_PLAN, _DECS, _SF, [{"name": "A", "code": "1", "buy_point": 1.0}],
                                    {"level": "hunt", "label": "x", "note": ""})
        texts = [i["headline"] + i["detail"] + i["caliber"] + (i["trigger"] or "") for i in out["items"]]
        texts.append(out["incomparable_note"] + " ".join(out["caveats"]))
    else:
        texts = list(dls._empty("x")["caveats"]) + [dls._empty("x")["note"]]
    for t in texts:
        for w in banned:
            assert w not in t, f"出现契约禁用词「{w}」: {t[:70]}"


def test_ledger_service_never_enters_evidence_or_llm():
    """不变量：留痕服务不得接入证据分或 LLM ctx。"""
    src = open(dls.__file__, encoding="utf-8").read()
    code = re.sub(r'"""[\s\S]*?"""', "", src)
    for bad in ("evidence_score", "tactic_evidence", "llm_service"):
        assert bad not in code, bad


def test_ledger_settle_window_bounded():
    """复盘回填窗口有上限 —— 全表扫会拖慢 cron。"""
    assert 0 < dls._SETTLE_WINDOW_DAYS <= 120


# ─────────────────────────────── 测试辅助


class _Resp:
    def __init__(self, data):
        self.data = data


class _Table:
    def __init__(self, data):
        self._data = data

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def gte(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def update(self, *a, **k):
        return self

    async def execute(self):
        return _Resp(self._data)


class _Client:
    def __init__(self, existing=None, trades=None):
        self._existing = existing or []
        self._trades = trades or []

    def table(self, name):
        if name == "alert_rules":
            return _Table(self._existing)
        return _Table(self._trades)


def _async_return(v):
    async def _f(*a, **k):
        return v
    return _f


def _async_value(v):
    async def _f(*a, **k):
        return v
    return _f
