"""多空研究员辩论：把 TradingAgents 的对抗机制搬进本项目的数据链路。

## 为什么是「抄机制」而不是「装依赖」

TradingAgents（TauricResearch，arXiv 2412.20138）把一家交易公司的投研流程拆成
「分析师团队 → 多空研究员辩论 → 交易员 → 风控/基金经理」四层。对照本项目：

| 上游那一层 | 本项目已有的对应物 |
|---|---|
| 分析师团队 | `signal_service`（技术位）+ `trend_template_service` + `pattern_service` + `data_service` 拼的 context |
| **研究员团队（多空辩论）** | **本模块 —— 四层里唯一缺的一层** |
| 交易员 | `llm_service` 的结构化 JSON 输出契约 |
| 风控 / 基金经理 | `tactic_evidence` 证据闸门（未验证不得进买卖点位置） |

补这一层的成本是 **0 个新运行时依赖**（复用已装的 openai SDK）。直接 `pip install`
上游框架则有三处硬冲突：

1. **部署体积**：langgraph / langchain 生态会进 Serverless 依赖，而本项目连 pytest
   都要靠 `requirements-dev.txt` 隔离，就是为了不撑大部署体积。
2. **数据源**：上游走 yfinance / FinnHub，A 股用不了；A 股特化分支走 mootdx + 东财直连 ——
   正好撞在本项目 **IP 级封禁的头号风险源**（东财全市场快照）上。
3. **超时**：上游一次完整辩论是 5~10 次 LLM 调用串行跑，会顶到 Vercel
   `maxDuration: 300` 的墙角；本模块固定 2 轮 = 4 次调用，且只跑用户显式开启时。

## 纪律（与 §8 证据闸门同一套）

辩论结论是本模块自己算出来的，**没有任何统计回测支撑**，因此：

- 证据等级固定取 `tactic_evidence` 的 `unknown` 档 —— label / badge / actionable
  全部从那里推导，本文件不手写任何等级文案。
- `executable` 恒为 `False`：展示层不得把它放进买点位置，只能作分歧与风险提示。
- `gate_note` 与形态闸门同格式，前端必须原样展示。

任何降级路径（未配 Key / LLM 报错 / JSON 解析失败）一律**返回 None 而不是抛异常** ——
辩论是增强项，不能因为它挂掉而让整个深度分析失败。
"""
from __future__ import annotations

import asyncio
import json

from app.config import get_settings
from app.models import DebateResult, DebateSide, FundManagerVerdict, TradePlan
from app.services import llm_service, tactic_evidence

# 辩论轮数上限。1 轮 = 双方各自立论；2 轮 = 各自拿到对方观点后逐条反驳。
# 上游支持调更多轮，这里刻意封在 2：每加一轮就是 +2 次 LLM 调用，而 300s 是硬顶。
MAX_ROUNDS = 2

# 倾向判定的中性带。两边信心差在 ±20 以内视为没有共识方向 ——
# LLM 的信心打分本身有噪声，阈值定在 0 会把噪声读成方向。
_NET_THRESHOLD = 20.0

# 证据记录：唯一来源是 tactic_evidence，label / badge / actionable 全部由它推导。
_DEBATE_EVIDENCE = tactic_evidence.Evidence(
    tier="unknown",
    summary="多空辩论为 LLM 推理结果，尚无回测样本，仅作分歧与风险提示",
    provenance="debate_service（未接入任何回测口径）",
)

# 交易员计划同样没有回测支撑（它只是把辩论结论翻译成结构），证据等级与辩论同源。
# 终审层不新增证据，只核对计划是否违反已有硬约束。
_TRADER_EVIDENCE = _DEBATE_EVIDENCE

_BULL_SYSTEM = """你是一位 A 股买方机构的多头研究员。你的唯一职责是：在给定资料范围内，为「看多」找出最强论证。

【纪律】
1. 只能使用资料中出现的数字与事实，严禁引入资料外的行情、财报、新闻或传闻
2. 每条论据必须引用具体数据（价格、均线、换手率、市盈率、涨跌幅、技术位等），禁止「基本面良好」「趋势向上」这类空话
3. 资料不足以支撑看多时必须如实下调 confidence，严禁编造理由凑数
4. confidence 是你对自己论证的把握（0-100），不是预期涨幅

【输出】只输出一个合法 JSON 对象，不要任何其他文字、注释或 Markdown 代码块标记：
{
  "thesis": "一句话核心论点",
  "evidence": ["带具体数据的论据，2-4 条"],
  "rebuttal": ["针对对方论点的逐条反驳"],
  "confidence": 0到100的整数
}
第一轮没有对方观点时，rebuttal 为空数组。"""

_BEAR_SYSTEM = """你是一位 A 股买方机构的空头研究员。你的唯一职责是：在给定资料范围内，为「看空 / 规避」找出最强论证。

【纪律】
1. 只能使用资料中出现的数字与事实，严禁引入资料外的行情、财报、新闻或传闻
2. 每条论据必须引用具体数据（价格、均线、换手率、市盈率、涨跌幅、技术位等），禁止「估值偏高」「风险较大」这类空话
3. 资料不足以支撑看空时必须如实下调 confidence，严禁编造理由凑数
4. confidence 是你对自己论证的把握（0-100），不是预期跌幅

【输出】只输出一个合法 JSON 对象，不要任何其他文字、注释或 Markdown 代码块标记：
{
  "thesis": "一句话核心论点",
  "evidence": ["带具体数据的论据，2-4 条"],
  "rebuttal": ["针对对方论点的逐条反驳"],
  "confidence": 0到100的整数,
  "key_disagreement": "双方最核心的分歧点，一句话"
}
第一轮没有对方观点时，rebuttal 为空数组、key_disagreement 留空字符串。"""


def _parse_json_object(text: str) -> dict | None:
    """从 LLM 输出里抠出最外层 JSON 对象。

    与 llm_service.parse_analysis 同策略（截取首尾花括号 + 兜底剥 Markdown 围栏），
    但解析失败返回 None 而不是抛 —— 辩论允许降级。
    """
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    raw = text[start : end + 1]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        try:
            data = json.loads(raw.replace("```json", "").replace("```", "").strip())
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


def _clean_list(value, limit: int = 6) -> list[str]:
    """把 LLM 给的「字符串数组」洗成干净的字符串列表（容忍它返回单个字符串）。"""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out[:limit]


def _clamp_confidence(value) -> float:
    """信心值收敛到 0-100。LLM 常见返回 0.8（当比例用）或 85（当百分数用），
    小于等于 1 的按比例处理，否则按百分数 —— 不这么判会把 0.8 当成「信心 0.8%」。"""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return 50.0
    if 0 < num <= 1:
        num *= 100
    return round(max(0.0, min(100.0, num)), 1)


def side_from(data: dict, side: str) -> DebateSide:
    """把一次 LLM 输出转成某一方的论点结构。"""
    return DebateSide(
        side=side,
        thesis=str(data.get("thesis", "")).strip(),
        evidence=_clean_list(data.get("evidence")),
        rebuttal=_clean_list(data.get("rebuttal")),
        confidence=_clamp_confidence(data.get("confidence", 50)),
    )


def _divergence(bull_conf: float, bear_conf: float) -> float:
    """分歧度口径：min(多头信心, 空头信心)。

    两边同时笃定（如 70 / 65）说明这是真争议，值高；
    一边笃定一边没底气（90 / 10）说明方向共识明确，值低。

    刻意不用 |bull - bear|：那个量在 90/10 与 10/90 上都是 80，
    会把「多头压倒性占优」和「空头压倒性占优」混成同一个数字，
    而这两种情形对用户的含义完全相反。
    """
    return round(min(bull_conf, bear_conf), 1)


def _direction(bull_conf: float, bear_conf: float) -> str:
    net = bull_conf - bear_conf
    if net >= _NET_THRESHOLD:
        return "bull"
    if net <= -_NET_THRESHOLD:
        return "bear"
    return "neutral"


def _build_user_prompt(context: str, opponent: DebateSide | None = None) -> str:
    """组装单轮输入：标的资料 +（第二轮起）对方观点。"""
    parts = [f"【标的资料】\n{context}"]
    if opponent is not None:
        label = "空方" if opponent.side == "bear" else "多方"
        lines = [f"【{label}上一轮观点】", f"核心论点：{opponent.thesis}"]
        if opponent.evidence:
            lines.append("论据：" + "；".join(opponent.evidence))
        if opponent.rebuttal:
            lines.append("对你的反驳：" + "；".join(opponent.rebuttal))
        lines.append("\n请逐条回应对你的质疑，并保持你自己的立场（不要为迁就对方而改变方向）。")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


async def _ask(side: str, system: str, user: str) -> dict | None:
    """调一次 LLM 并解析成 dict；任何失败都返回 None。"""
    try:
        text = await llm_service.complete(system, user)
    except Exception as e:  # noqa: BLE001 — 辩论是增强项，任何异常都只降级
        print(f"[debate] {side} 调用失败: {e}")
        return None
    return _parse_json_object(text)


async def run_debate(context: str, *, rounds: int = MAX_ROUNDS) -> DebateResult | None:
    """跑一场多空辩论，返回结构化结果；任何一环失败都返回 None（不影响主分析）。

    rounds=1：双方各自立论（2 次 LLM 调用）
    rounds=2：第二轮各自看到对方观点后逐条反驳（共 4 次）
    """
    settings = get_settings()
    if not settings.deepseek_api_key:
        # 无 Key 时静默降级 —— 调用方已经在用本地规则评分，辩论没有可用的推理后端
        return None

    rounds = 1 if rounds < 2 else MAX_ROUNDS

    # 第一轮：双方独立立论，并行发起（互不依赖，串行只是白等）
    bull_raw, bear_raw = await asyncio.gather(
        _ask("bull", _BULL_SYSTEM, _build_user_prompt(context)),
        _ask("bear", _BEAR_SYSTEM, _build_user_prompt(context)),
    )
    if bull_raw is None or bear_raw is None:
        # 缺一半的辩论没有意义（单边观点会被读成单边结论），整体降级
        return None

    bull = side_from(bull_raw, "bull")
    bear = side_from(bear_raw, "bear")
    completed = 1
    key_disagreement = str(bear_raw.get("key_disagreement", "")).strip()

    # 第二轮：各自拿到对方的第一轮观点后反驳
    if rounds >= 2:
        bull_raw2, bear_raw2 = await asyncio.gather(
            _ask("bull", _BULL_SYSTEM, _build_user_prompt(context, opponent=bear)),
            _ask("bear", _BEAR_SYSTEM, _build_user_prompt(context, opponent=bull)),
        )
        if bull_raw2 is not None and bear_raw2 is not None:
            bull = side_from(bull_raw2, "bull")
            bear = side_from(bear_raw2, "bear")
            completed = 2
            key_disagreement = (
                str(bear_raw2.get("key_disagreement", "")).strip()
                or str(bear_raw2.get("thesis", "")).strip()
            )
        # 第二轮失败：沿用第一轮（双方已有独立立论），不整体降级

    # key_disagreement 兜底链：轮次输出 → 空头对多头的第一条反驳 → 空头论点
    if not key_disagreement:
        key_disagreement = (bear.rebuttal or [bear.thesis])[0]

    evidence = _DEBATE_EVIDENCE
    return DebateResult(
        rounds=completed,
        bull=bull,
        bear=bear,
        divergence=_divergence(bull.confidence, bear.confidence),
        direction=_direction(bull.confidence, bear.confidence),
        key_disagreement=key_disagreement,
        evidence=evidence.as_dict(),
        executable=False,  # 恒为 False，与 _DEBATE_EVIDENCE.actionable 一致
        gate_note=f"观察池 · {evidence.label}：{evidence.summary}",
    )


def summarize(debate: DebateResult) -> str:
    """给主分析 LLM 看的一句话摘要 —— 只递分歧，不递结论。

    刻意不把 direction 喂给下游：辩论的倾向没有统计支撑，如果让主分析按它调整评分，
    等于让未经回测的结论间接进入了总分。下游只需要知道「这里有争议、争议在哪」。
    """
    if not debate.bull or not debate.bear:
        return ""
    return (
        f"多空研究员辩论（{debate.rounds} 轮）分歧度 {debate.divergence:.0f}/100，"
        f"核心分歧：{debate.key_disagreement}。"
        f"注意：这是 LLM 推理结果，没有统计回测支撑，不得作为评分依据，"
        f"只用于提示该股存在争议、需在风险提示中体现。"
    )


# ---------------------------------------------------------------------------
# TradingAgents ③ 交易员层：把辩论结论翻译成「可被风控检验」的计划草案
# ---------------------------------------------------------------------------
# 仓位硬上限（占总资金 %）—— 与 portfolio_service 的风险等级参数一致，
# 这里内联一份是因为辩论/计划阶段拿不到 user_id（深度分析未登录也可用），
# 终审层再按用户真实风险等级收紧（只会更严，不会更松）。
_POSITION_CAPS = {"保守": 15.0, "稳健": 20.0, "进取": 25.0, "激进": 35.0}
_DEFAULT_RISK_LEVEL = "稳健"

_TRADER_SYSTEM = """你是一位 A 股买方机构的交易员。研究员团队刚完成多空辩论，你的职责是：
把辩论结论翻译成一份**可被风控检验**的交易计划。你不是研究员，你不辩论——你只决定「做不做、做多少、错了怎么办」。

【纪律】
1. 只能引用辩论双方论据与系统技术位，严禁引入资料外的信息
2. 止损价必须低于入场触发价（看多计划），且必须尊重系统给出的技术止损位（只能更严，不能更松）
3. 仓位不超过给定的上限；辩论分歧度大时主动降低仓位
4. 辩论倾向为 neutral 或看空时，计划必须是 hold / reduce / avoid，严禁编造买入理由
5. 必须给出计划失效条件——出现什么信号说明论证已破
6. 这份计划会交给风控终审，他们会否决违反纪律的条目，不要试图绕过
7. **hold 不是安全默认，禁止用 hold 偷懒规避决策。** 仅当以下任一成立才允许 hold：(a) 辩论倾向 neutral/bear；(b) 无法给出有效入场价与止损价（止损价≥入场价）；(c) 风险收益比 < 1.5。
8. **当辩论倾向为 bull 且技术位有效（止损价 < 入场触发价 且 风险收益比 ≥ 1.5）时，必须给出 buy 或 add 计划，且 position_pct 必须大于 0。** 仓位按信号强度在区间内取值：信号强度 ≥ 7 → 取上限的 60%~80%；4 ≤ 强度 < 7 → 取上限的 40%~60%；强度 < 4 即便方向 bull 也按纪律 7 降为 hold。

【输出】只输出一个合法 JSON 对象，不要任何其他文字、注释或 Markdown 代码块标记：
{
  "action": "buy | add | hold | reduce | avoid",
  "entry_price": 入场触发价数字或 null,
  "stop_price": 止损价数字或 null,
  "target_price": 目标价数字或 null,
  "position_pct": 0到仓位上限的纯数字（如 4 表示 4%）；buy/add 时必须大于 0，严禁带 % 或「成」等单位,
  "batches": ["分批方案，每条一句话，1-3 条"],
  "rationale": "计划依据：引用辩论双方论据与技术位的具体数字，2-3 句",
  "invalidation": "计划失效条件，一句话"
}"""

_FM_SYSTEM = """你是 A 股买方机构的风控总监（基金经理终审）。交易员提交了一份交易计划，你的职责是**核对纪律**，不是重新研究。

【硬约束（违反任意一条即 rejected）】
1. 看多计划（buy/add）的止损价必须低于入场触发价
2. 仓位不得超过给定的仓位上限
3. 辩论倾向为 neutral/bear 时计划不得是 buy/add
4. 计划依据里出现「感觉」「应该会」「大概率」等无数据断言 → 整份计划可信度不足，rejected

【降级情形（demoted）】
- 计划方向可参考但仓位顶格、或止损贴近入场价（风险收益比 < 1.5）→ 修正仓位/止损后 demoted
- 分歧度 ≥ 60 → 仓位减半后 demoted

【批准（approved）】全部硬约束通过且无降级情形。

【输出】只输出一个合法 JSON 对象，不要任何其他文字、注释或 Markdown 代码块标记：
{
  "decision": "approved | demoted | rejected",
  "verdict_notes": ["逐条裁决理由，必须引用具体数字，2-4 条"],
  "final_position_pct": 终审后仓位数字（rejected 时为 0）,
  "final_stop_price": 终审后止损价数字或 null（只能比交易员的更严）
}"""


def _format_debate_for_trader(debate: DebateResult) -> str:
    """把辩论结论压成交易员的输入文本（只带数据与论据，不带证据等级标签）。"""
    def _fmt(side: DebateSide | None, tag: str) -> str:
        if side is None:
            return f"{tag}：缺席"
        lines = [f"{tag}（信心 {side.confidence:.0f}/100）：{side.thesis}"]
        lines += [f"  论据: {e}" for e in (side.evidence or [])[:4]]
        if side.rebuttal:
            lines += [f"  反驳: {r}" for r in side.rebuttal[:3]]
        return "\n".join(lines)

    return (
        f"{_fmt(debate.bull, '多头研究员')}\n\n"
        f"{_fmt(debate.bear, '空头研究员')}\n\n"
        f"分歧度: {debate.divergence:.0f}/100\n"
        f"核心分歧: {debate.key_disagreement}\n"
        f"辩论倾向: {debate.direction}"
    )


def _parse_plan(raw: dict, price: float) -> TradePlan:
    """把交易员 JSON 收敛成 TradePlan；数值越界一律取保守值。"""
    action = str(raw.get("action", "hold")).strip().lower()
    if action not in {"buy", "add", "hold", "reduce", "avoid"}:
        action = "hold"

    def _num(key: str) -> float | None:
        v = raw.get(key)
        try:
            return max(0.0, float(v)) if v is not None else None
        except (TypeError, ValueError):
            return None

    # 仓位解析：LLM 常输出 "4%" / "4成" / " 4 " 这类带单位/空白的值，
    # 裸 float() 会 ValueError → 静默归 0（表现就是前端「仓位 0%」）。
    # 先剥单位再解析；仍失败才是真 0，且看多计划归 0 时必须留痕（禁静默失效）。
    raw_pct = raw.get("position_pct", 0)
    if isinstance(raw_pct, str):
        cleaned = raw_pct.strip().replace("%", "").replace("％", "")
        if cleaned.endswith("成"):
            cleaned = cleaned[:-1]
            try:
                raw_pct = float(cleaned) * 10  # X成 → X*10%
            except (TypeError, ValueError):
                raw_pct = 0
        else:
            raw_pct = cleaned or 0
    try:
        pct = min(max(0.0, float(raw_pct)), 100.0)
    except (TypeError, ValueError):
        pct = 0.0
    if pct == 0 and action in {"buy", "add"}:
        print(f"[debate] 交易员计划 action={action} 但 position_pct 解析为 0（原始值: {raw.get('position_pct')!r}），请核查 LLM 输出格式")
    return TradePlan(
        action=action,
        entry_price=_num("entry_price"),
        stop_price=_num("stop_price"),
        target_price=_num("target_price"),
        position_pct=pct,
        batches=[str(b)[:80] for b in (raw.get("batches") or [])[:3] if str(b).strip()],
        rationale=str(raw.get("rationale", ""))[:400],
        invalidation=str(raw.get("invalidation", ""))[:200],
        source="trader",
    )


async def draft_trade_plan(
    debate: DebateResult,
    context: str,
    *,
    price: float,
    signal: dict | None = None,
) -> TradePlan | None:
    """交易员起草计划（TradingAgents ③）。任何一环失败返回 None。

    输入三样：辩论结论（结构化）、系统技术位（signal_service 的确定性输出）、
    原始 context 只给兜底（交易员纪律要求以辩论论据为主）。
    """
    if debate.bull is None or debate.bear is None:
        return None
    tech_lines = []
    if signal:
        tech_lines = [
            f"系统技术位（确定性计算，非 LLM 输出）：支撑 {signal['support']}，压力 {signal['resistance']}，"
            f"建议买入区 {signal['buy_point']}，止损位 {signal['stop_loss']}，"
            f"风险收益比 {signal['rr_ratio']}，信号强度 {signal['strength']}/10。",
            "你的止损不得松于系统止损位。",
        ]
    user = (
        f"{_format_debate_for_trader(debate)}\n\n"
        f"现价: {price}\n"
        + ("\n".join(tech_lines) + "\n\n" if tech_lines else "")
        + f"仓位上限: {_POSITION_CAPS[_DEFAULT_RISK_LEVEL]}%（总资金占比）\n"
        "请输出交易计划 JSON。"
    )
    raw = await _ask("trader", _TRADER_SYSTEM, user)
    if raw is None:
        return None
    return _parse_plan(raw, price)


# ---------------------------------------------------------------------------
# TradingAgents ④ 风控/基金经理终审：批准 / 降级 / 否决
# ---------------------------------------------------------------------------
def review_plan(
    plan: TradePlan,
    debate: DebateResult,
    *,
    signal: dict | None = None,
    risk_level: str = _DEFAULT_RISK_LEVEL,
) -> FundManagerVerdict:
    """对交易员计划做确定性风控核对（TradingAgents ④）。

    设计：硬约束判定**全部代码算**，LLM 不参与 —— 风控红线交给 LLM 自由裁量等于没有风控。
    场景 1（合规但止损过松于技术位）会 demote，这是刻意的：止损只能收紧不能放大，与
    portfolio_service._select_stop_price 同一铁律。
    """
    cap = _POSITION_CAPS.get(risk_level, _POSITION_CAPS[_DEFAULT_RISK_LEVEL])
    notes: list[str] = []
    violations: list[str] = []
    demotions: list[str] = []

    final_pct = plan.position_pct
    final_stop = plan.stop_price
    bullish = plan.action in {"buy", "add"}

    # --- 硬约束 1：看多计划必须带有效止损 ---
    if bullish:
        if plan.entry_price is None or plan.stop_price is None:
            violations.append("看多计划缺少入场价或止损价，风控无法评估亏损边界")
        elif plan.stop_price >= plan.entry_price:
            violations.append(
                f"止损价 {plan.stop_price} 不低于入场价 {plan.entry_price}，亏损边界无效"
            )
        else:
            risk_per_share = plan.entry_price - plan.stop_price
            rr = (
                (plan.target_price - plan.entry_price) / risk_per_share
                if plan.target_price and plan.target_price > plan.entry_price
                else None
            )
            if rr is not None and rr < 1.5:
                demotions.append(
                    f"风险收益比 {rr:.2f} < 1.5（入场 {plan.entry_price} / 止损 {plan.stop_price}"
                    + (f" / 目标 {plan.target_price}" if plan.target_price else "")
                    + "），仓位与止损需收紧"
                )
            # 止损只能比交易员的更严：贴技术止损再校一次
            if signal and signal.get("stop_loss"):
                tech_stop = float(signal["stop_loss"])
                if final_stop is not None and final_stop <= tech_stop:
                    pass  # 交易员止损不松于技术位（更低=更严），保留
                elif final_stop is not None:
                    demotions.append(f"止损上移至技术止损位 {tech_stop}（原 {final_stop} 过松）")
                    final_stop = tech_stop

    # --- 硬约束 2：仓位上限（只对看多计划生效 —— 减仓/回避不存在「手太大」的风险）---
    if bullish and final_pct > cap:
        demotions.append(f"仓位 {final_pct:.0f}% 超过「{risk_level}」等级上限 {cap:.0f}%，已压回")
        final_pct = cap

    # --- 硬约束 3：辩论方向与动作一致性 ---
    if bullish and debate.direction in {"neutral", "bear"}:
        violations.append(
            f"辩论倾向为 {debate.direction}（多头信心 {debate.bull.confidence if debate.bull else 0:.0f}"
            f" vs 空头 {debate.bear.confidence if debate.bear else 0:.0f}），"
            "没有共识方向却提交看多计划"
        )

    # --- 降级 4：高分歧 ---
    if debate.divergence >= 60 and bullish and final_pct > 0:
        halved = round(final_pct / 2, 1)
        demotions.append(f"分歧度 {debate.divergence:.0f}/100 ≥ 60，仓位 {final_pct:.0f}% 减半至 {halved}%")
        final_pct = halved

    if violations:
        return FundManagerVerdict(
            decision="rejected",
            verdict_notes=violations,
            final_position_pct=0,
            final_stop_price=None,
        )

    decision = "demoted" if demotions else "approved"
    return FundManagerVerdict(
        decision=decision,
        verdict_notes=demotions or ["全部硬约束通过：止损有效、仓位合规、辩论方向一致"],
        final_position_pct=final_pct,
        final_stop_price=final_stop,
    )
