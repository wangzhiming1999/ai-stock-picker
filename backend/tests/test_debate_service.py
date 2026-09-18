"""多空研究员辩论（debate_service）的测试。

两条铁律在这里锁定：

1. **闸门单向**：辩论结论无论多笃定，`executable` 恒为 False、证据等级恒为
   `unknown`（不在 ACTIONABLE_TIERS）—— LLM 论证没有任何回测样本，不得进买卖点位置。
2. **降级不抛异常**：无 Key / LLM 失败 / JSON 解析失败一律返回 None，
   辩论是增强项，绝不能让深度分析主流程跟着挂。
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.models import DebateResult
from app.services import debate_service as ds
from app.services import llm_service, tactic_evidence

ALLOWED_TIERS = {"verified", "preliminary", "unsupported", "unknown", "not_testable"}


def _side_json(thesis: str, confidence, *, rebuttal=None, key_disagreement="") -> str:
    payload = {
        "thesis": thesis,
        "evidence": ["现价站上 MA5(12.34)", "市盈率 18.2 处于合理区间"],
        "rebuttal": rebuttal or [],
        "confidence": confidence,
    }
    if key_disagreement:
        payload["key_disagreement"] = key_disagreement
    return json.dumps(payload, ensure_ascii=False)


CTX = "600519 贵州茅台 现价 1500.00，市盈率 18.2，换手率 1.2%，近20日 +8.3%"


# ---------------- 纯函数口径 ----------------


class TestParsers:
    def test_parse_plain_json(self) -> None:
        data = ds._parse_json_object('{"thesis": "看多", "confidence": 70}')
        assert data == {"thesis": "看多", "confidence": 70}

    def test_parse_fenced_json(self) -> None:
        text = '好的，分析如下：\n```json\n{"thesis": "看多", "confidence": 70}\n```'
        assert ds._parse_json_object(text)["confidence"] == 70

    def test_parse_garbage_returns_none(self) -> None:
        assert ds._parse_json_object("") is None
        assert ds._parse_json_object("没有 JSON 的输出") is None
        assert ds._parse_json_object("{broken json") is None
        assert ds._parse_json_object('[1, 2, 3]') is None  # 数组不是对象

    def test_clamp_confidence_ratio_vs_percent(self) -> None:
        # LLM 常见把信心当比例（0.8）或百分数（80）返回
        assert ds._clamp_confidence(0.8) == 80.0
        assert ds._clamp_confidence(85) == 85.0
        assert ds._clamp_confidence("abc") == 50.0  # 解析失败给中性
        assert ds._clamp_confidence(120) == 100.0
        assert ds._clamp_confidence(-5) == 0.0

    def test_divergence_uses_min_not_delta(self) -> None:
        # min 口径：90/10 是「方向共识明确」，分歧必须低；
        # 90/80 才是「两边都笃定的真争议」。
        assert ds._divergence(90, 10) == 10.0
        assert ds._divergence(90, 80) == 80.0
        assert ds._divergence(72, 65) == 65.0

    def test_direction_neutral_band(self) -> None:
        # 信心差在 ±20 内视为没有共识方向（LLM 信心打分本身有噪声）
        assert ds._direction(70, 45) == "bull"
        assert ds._direction(45, 70) == "bear"
        assert ds._direction(60, 50) == "neutral"
        assert ds._direction(50, 60) == "neutral"


class TestSideFrom:
    def test_clean_fields(self) -> None:
        side = ds.side_from(
            json.loads(
                _side_json("估值与趋势双支撑", 72,
                           rebuttal=["流动性不支持", ""],
                           key_disagreement="量能能否持续")
            ),
            "bull",
        )
        assert side.side == "bull"
        assert side.thesis == "估值与趋势双支撑"
        assert len(side.evidence) == 2
        assert side.rebuttal == ["流动性不支持"]  # 空串被洗掉
        assert side.confidence == 72.0

    def test_single_string_evidence_tolerated(self) -> None:
        side = ds.side_from({"thesis": "t", "evidence": "只有一条", "confidence": 60}, "bear")
        assert side.evidence == ["只有一条"]


# ---------------- 闸门纪律（最重要的一组） ----------------


class TestEvidenceGate:
    def test_tier_is_unknown_and_not_actionable(self) -> None:
        """辩论结论不得进买卖点位置 —— 与形态闸门同一纪律。"""
        assert ds._DEBATE_EVIDENCE.tier == "unknown"
        assert ds._DEBATE_EVIDENCE.tier in ALLOWED_TIERS  # 不得发明新档位
        assert ds._DEBATE_EVIDENCE.actionable is False
        assert ds._DEBATE_EVIDENCE.tier not in tactic_evidence.ACTIONABLE_TIERS

    def test_result_carries_gate(self) -> None:
        # 默认值本身不携带闸门；闸门由 run_debate 按 _DEBATE_EVIDENCE 统一挂上。
        # 这里按 run_debate 的挂法构造，锁定「挂出来的东西永远不可执行」。
        ev = ds._DEBATE_EVIDENCE
        result = DebateResult(
            evidence=ev.as_dict(),
            executable=False,
            gate_note=f"观察池 · {ev.label}：{ev.summary}",
        )
        assert result.executable is False
        assert result.evidence.get("actionable") is False
        assert result.evidence.get("tier") == "unknown"
        assert "观察池" in result.gate_note
        assert result.direction == "neutral"


# ---------------- run_debate 流程 ----------------


def _patch_settings(monkeypatch, api_key: str = "test-key") -> None:
    monkeypatch.setattr(ds, "get_settings", lambda: SimpleNamespace(deepseek_api_key=api_key))


def _patch_llm(monkeypatch, responder):
    """responder(side: 'bull'|'bear', round_no: int, user: str) -> str"""
    calls: list[tuple[str, int, str]] = []

    async def fake_complete(system: str, user: str, *, temperature=0.3, max_tokens=1500) -> str:
        side = "bull" if "多头研究员" in system else "bear"
        round_no = 2 if "上一轮观点" in user else 1
        calls.append((side, round_no, user))
        return responder(side, round_no, user)

    monkeypatch.setattr(llm_service, "complete", fake_complete)
    return calls


@pytest.mark.asyncio
async def test_run_debate_two_rounds_with_rebuttals(monkeypatch) -> None:
    _patch_settings(monkeypatch)

    def responder(side: str, round_no: int, user: str) -> str:
        if round_no == 1:
            conf = 72 if side == "bull" else 65
            return _side_json(f"{side} 第一轮论点", conf)
        return _side_json(
            f"{side} 第二轮论点", 80 if side == "bull" else 55,
            rebuttal=[f"反驳对方{side}论据"],
            key_disagreement="量能能否持续放大",
        )

    calls = _patch_llm(monkeypatch, responder)
    result = await ds.run_debate(CTX)

    assert result is not None
    assert result.rounds == 2
    assert len(calls) == 4  # 2 轮 × 双方
    assert result.bull.rebuttal == ["反驳对方bull论据"]
    assert result.bear.rebuttal == ["反驳对方bear论据"]
    assert result.key_disagreement == "量能能否持续放大"
    assert result.divergence == 55.0  # min(80, 55)
    assert result.direction == "bull"  # 80 - 55 = 25 ≥ 20
    # 第二轮的输入里必须真的带了对方第一轮的观点（否则"反驳"是空转）：
    # 多头的第二轮 prompt 要含空头第一轮论点，反之亦然
    bull_r2 = next(u for s, r, u in calls if s == "bull" and r == 2)
    bear_r2 = next(u for s, r, u in calls if s == "bear" and r == 2)
    assert "bear 第一轮论点" in bull_r2
    assert "bull 第一轮论点" in bear_r2
    assert result.executable is False


@pytest.mark.asyncio
async def test_run_debate_round2_failure_keeps_round1(monkeypatch) -> None:
    """第二轮失败只降级到一轮，不整体放弃 —— 第一轮双方已各有独立立论。"""
    _patch_settings(monkeypatch)

    def responder(side: str, round_no: int, user: str) -> str:
        if round_no == 2:
            raise RuntimeError("LLM 超时")
        return _side_json(f"{side} 第一轮论点", 70)

    _patch_llm(monkeypatch, responder)
    result = await ds.run_debate(CTX)

    assert result is not None
    assert result.rounds == 1
    assert result.bull.rebuttal == []
    # key_disagreement 兜底链：空头第一条反驳 → 空头论点
    assert result.key_disagreement == "bear 第一轮论点"


@pytest.mark.asyncio
async def test_run_debate_side_failure_degrades_to_none(monkeypatch) -> None:
    """缺一半的辩论没有意义（单边观点会被读成单边结论），必须整体降级。"""
    _patch_settings(monkeypatch)

    async def broken(system: str, user: str, *, temperature=0.3, max_tokens=1500) -> str:
        if "空头研究员" in system:
            raise RuntimeError("空头挂了")
        return _side_json("多头论点", 70)

    monkeypatch.setattr(llm_service, "complete", broken)
    assert await ds.run_debate(CTX) is None


@pytest.mark.asyncio
async def test_run_debate_unparseable_output_degrades(monkeypatch) -> None:
    _patch_settings(monkeypatch)

    async def garbage(system: str, user: str, *, temperature=0.3, max_tokens=1500) -> str:
        return "模型今天不想输出 JSON"

    monkeypatch.setattr(llm_service, "complete", garbage)
    assert await ds.run_debate(CTX) is None


@pytest.mark.asyncio
async def test_run_debate_without_api_key(monkeypatch) -> None:
    """无 Key：静默返回 None（调用方已在用本地规则评分），绝不抛异常。"""
    _patch_settings(monkeypatch, api_key="")
    assert await ds.run_debate(CTX) is None


def test_summarize_hides_direction_from_downstream(monkeypatch) -> None:
    """summarize 只递分歧不递倾向：direction 没有统计支撑，
    若被主分析照单全收，等于让未回测的结论间接进了总分。"""
    debate = DebateResult(
        rounds=2,
        bull=ds.side_from({"thesis": "多头论点", "confidence": 80}, "bull"),
        bear=ds.side_from({"thesis": "空头论点", "confidence": 55}, "bear"),
        direction="bull",
        divergence=55,
        key_disagreement="量能能否持续放大",
    )
    text = ds.summarize(debate)
    assert "55" in text and "量能能否持续放大" in text
    assert "bull" not in text and "bear" not in text  # 倾向词不得外泄
    assert "不得作为评分依据" in text


class TestTradePlan:
    """TradingAgents ③ 交易员层：辩论 → 结构化计划。

    两条纪律：
    1. 数值越界一律取保守值（仓位压上限、非法动作归 hold）
    2. 任何失败降级为 None，不影响主分析
    """

    def _debate(self, direction="bull", divergence=40) -> DebateResult:
        bull = ds.side_from({"thesis": "多头", "confidence": 70 if direction == "bull" else 45}, "bull")
        bear = ds.side_from({"thesis": "空头", "confidence": 30 if direction == "bull" else 42}, "bear")
        return DebateResult(
            rounds=2, bull=bull, bear=bear, divergence=divergence, direction=direction,
            key_disagreement="量能",
        )

    def test_parse_plan_clamps_action_only(self) -> None:
        """非法动作归 hold；仓位**不压到风险上限**（越界是终审的 demote 职责）。
        100% 是模型层物理上限（pydantic le=100），超出会被收敛到 100 再交给终审降级。"""
        plan = ds._parse_plan(
            {"action": "yolo", "position_pct": 999, "entry_price": 10, "stop_price": 9},
            price=10,
        )
        assert plan.action == "hold"
        assert plan.position_pct == 100  # pydantic 物理上限；风险上限由 review_plan 压

    def test_parse_plan_tolerates_garbage_numbers(self) -> None:
        plan = ds._parse_plan(
            {"action": "buy", "position_pct": "abc", "entry_price": None, "stop_price": "x"},
            price=10,
        )
        assert plan.position_pct == 0
        assert plan.entry_price is None
        assert plan.stop_price is None

    @pytest.mark.asyncio
    async def test_draft_plan_without_debate_returns_none(self) -> None:
        """辩论缺一半（bull/bear 为 None）时交易员不开工。"""
        lone = DebateResult(rounds=1, bull=None, bear=None)
        assert await ds.draft_trade_plan(lone, "ctx", price=10) is None

    @pytest.mark.asyncio
    async def test_draft_plan_downgrades_on_llm_failure(self, monkeypatch) -> None:
        """LLM 失败返回 None，不抛异常 —— 计划是增强项。"""
        async def _boom(*a, **k):
            raise RuntimeError("network")
        monkeypatch.setattr(ds.llm_service, "complete", _boom)
        assert await ds.draft_trade_plan(self._debate(), "ctx", price=10) is None

    @pytest.mark.asyncio
    async def test_draft_plan_includes_tech_stop_in_prompt(self, monkeypatch) -> None:
        """系统技术位必须进 prompt 且明示「不得松于」——交易员的止损纪律来源。"""
        captured = {}

        async def _fake(system, user):
            captured["user"] = user
            return '{"action": "buy", "entry_price": 10, "stop_price": 9.2, "position_pct": 15, "batches": [], "rationale": "r", "invalidation": "i"}'

        monkeypatch.setattr(ds.llm_service, "complete", _fake)
        plan = await ds.draft_trade_plan(
            self._debate(), "ctx", price=10.0,
            signal={"support": 9.5, "resistance": 11, "buy_point": 9.8, "stop_loss": 9.0,
                    "rr_ratio": 2.0, "strength": 6, "sell_point": 11.5},
        )
        assert plan is not None and plan.action == "buy"
        assert "不得松于" in captured["user"]
        assert "9.0" in captured["user"]  # 技术止损位注入


class TestFundManagerVerdict:
    """TradingAgents ④ 终审层：硬约束全部代码判定，不走 LLM。"""

    def _debate(self, direction="bull", divergence=40, bull_conf=70, bear_conf=30) -> DebateResult:
        return DebateResult(
            rounds=2,
            bull=ds.side_from({"thesis": "多", "confidence": bull_conf}, "bull"),
            bear=ds.side_from({"thesis": "空", "confidence": bear_conf}, "bear"),
            divergence=divergence, direction=direction, key_disagreement="x",
        )

    def test_valid_plan_approved(self) -> None:
        """交易员止损必须不松于技术位才算完全合规 —— 9.2 > 9.0 会被 demote，所以用 9.0。"""
        plan = ds._parse_plan(
            {"action": "buy", "entry_price": 10.0, "stop_price": 9.0,
             "target_price": 12.0, "position_pct": 15}, price=10)
        v = ds.review_plan(plan, self._debate(), signal={"stop_loss": 9.0})
        assert v.decision == "approved"
        assert v.final_position_pct == 15
        assert v.final_stop_price == 9.0

    def test_stop_above_entry_rejected(self) -> None:
        """止损 >= 入场 = 亏损边界无效，硬否决。"""
        plan = ds._parse_plan(
            {"action": "buy", "entry_price": 10.0, "stop_price": 10.5, "position_pct": 10}, price=10)
        v = ds.review_plan(plan, self._debate())
        assert v.decision == "rejected"
        assert v.final_position_pct == 0

    def test_missing_stop_rejected(self) -> None:
        plan = ds._parse_plan({"action": "buy", "entry_price": 10.0, "position_pct": 10}, price=10)
        assert ds.review_plan(plan, self._debate()).decision == "rejected"

    def test_position_over_cap_demoted(self) -> None:
        """仓位超等级上限：压回而不是否决（方向没错，只是手太大）。"""
        plan = ds._parse_plan(
            {"action": "buy", "entry_price": 10.0, "stop_price": 9.0, "position_pct": 30}, price=10)
        v = ds.review_plan(plan, self._debate(), risk_level="稳健")
        assert v.decision == "demoted"
        assert v.final_position_pct == 20

    def test_loose_stop_tightened_to_tech_stop(self) -> None:
        """止损只能收紧不能放大：松于技术位时上移到技术位（与 _select_stop_price 同铁律）。"""
        plan = ds._parse_plan(
            {"action": "buy", "entry_price": 10.0, "stop_price": 9.6, "position_pct": 10}, price=10)
        v = ds.review_plan(plan, self._debate(), signal={"stop_loss": 9.4})
        assert v.decision == "demoted"
        assert v.final_stop_price == 9.4

    def test_neutral_debate_with_buy_plan_rejected(self) -> None:
        """辩论没有共识方向却提交看多计划 → 硬否决。"""
        plan = ds._parse_plan(
            {"action": "buy", "entry_price": 10.0, "stop_price": 9.0, "position_pct": 10}, price=10)
        v = ds.review_plan(plan, self._debate(direction="neutral", bull_conf=45, bear_conf=42))
        assert v.decision == "rejected"
        assert "没有共识方向" in v.verdict_notes[0]

    def test_high_divergence_halves_position(self) -> None:
        plan = ds._parse_plan(
            {"action": "buy", "entry_price": 10.0, "stop_price": 9.0, "position_pct": 16}, price=10)
        v = ds.review_plan(plan, self._debate(divergence=70, bull_conf=75, bear_conf=70))
        assert v.decision == "demoted"
        assert v.final_position_pct == 8.0

    def test_poor_rr_demoted(self) -> None:
        """风险收益比 < 1.5 降级（止损贴近入场）。"""
        plan = ds._parse_plan(
            {"action": "buy", "entry_price": 10.0, "stop_price": 9.8,
             "target_price": 10.2, "position_pct": 10}, price=10)
        v = ds.review_plan(plan, self._debate())
        assert v.decision == "demoted"
        assert any("风险收益比" in n for n in v.verdict_notes)

    def test_reduce_plan_skips_bullish_constraints(self) -> None:
        """减仓/回避计划不吃看多约束 —— 防御方向永远放行。"""
        plan = ds._parse_plan({"action": "reduce", "position_pct": 25}, price=10)
        v = ds.review_plan(plan, self._debate(direction="neutral"))
        assert v.decision == "approved"

    def test_rejected_plan_zero_position(self) -> None:
        """否决 = 仓位归零、止损失效 —— 不留任何可参考的执行参数。"""
        plan = ds._parse_plan(
            {"action": "buy", "entry_price": 10.0, "stop_price": 10.0, "position_pct": 20}, price=10)
        v = ds.review_plan(plan, self._debate())
        assert v.decision == "rejected"
        assert v.final_position_pct == 0
        assert v.final_stop_price is None
