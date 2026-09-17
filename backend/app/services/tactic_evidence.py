"""形态证据等级：把「回测结论」变成展示层必须遵守的闸门。

## 为什么需要这一层

`pattern_service` 的 9 条技巧在 UI 上一律以「买点 / 卖点」呈现，但回测显示**没有任何一条**
达到统计显著。把「未验证的形态」和「已验证的形态」放在同一位置、用同一套文案，
等于用 UI 把猜测包装成结论 —— 这正是用户反馈的「数据不准确」在产品层的根源：
不是数字算错了，是**可信度没有被区分**。

## 分级口径（前端只认这几档，不要随意增加）

| tier | 判定规则 | 含义 |
|---|---|---|
| `verified` | n ≥ 30 且 \\|z\\| ≥ 1.96 且各持有期收益超额均为正 | 可作买卖点提示 |
| `preliminary` | n < 30 且超额方向一致为正；**或**口径不完整（拿不到收益，只能得到中间指标）但方向一致为正 | 只是线索，不足以支撑动作 |
| `unsupported` | n ≥ 30 但未达显著，或超额为负 / 符号不稳定 | 现有数据不支持该优势 |
| `unknown` | 尚未用当前实现回测过 | 无结论 |
| `not_testable` | 当前数据源无法回测 | 无结论，并写明原因 |

只有 `verified` 会进入 `ACTIONABLE_TIERS`。当前**一条都没有** —— 这是刻意的留白：
失败方向必须是「把可用的形态标成观察」，绝不能是「把没验证的形态标成买点」。

⚠️ 「中间指标」这一路（如 `limitup_relay` 的晋级率）要格外小心：**晋级率不是胜率**。
它只回答「能不能继续封板」，回答不了「买进去赚不赚钱」—— 两者之间隔着一次「能不能成交」。
这类条目一律停在 `preliminary`，**即便样本量已达门槛也不得升级为 `verified`**：
样本再多也补不上缺失的那个口径。

## 维护方式

本表是**唯一来源**：`pattern_service.ESCALATE_SELL_KEYS`、`_pack()` 挂的
`evidence/executable/gate_note`、`GET /api/market/tactics` 的角标全部由它推导。
每次重跑 `POST /api/backtest/tactic` 后更新 `EVIDENCE` 与 `SNAPSHOT`，
**不要只改文档不改这张表** —— 那正是本项目反复出现的「文档漂移」。

不在形态回测流程内的条目（如 `limitup_relay` 来自 `limitup_service.relay_backtest`）
登记在 `STRATEGY_EVIDENCE` 里，运行口径写在各自的 `provenance` 中，不进 `SNAPSHOT`
（`SNAPSHOT` 专指形态回测那一次跑批）。查询走 `get()` / `describe()`，两个命名空间都能命中。
"""
from __future__ import annotations

from dataclasses import dataclass

# 允许进入「买点 / 卖点」位置的等级。刻意只有 verified：
# 判定条件成立 ≠ 该形态被证明有效，前者是数学、后者需要统计证据。
ACTIONABLE_TIERS = frozenset({"verified"})

# 允许把「持有观察」升级为「建议减仓」的等级。减仓是仓位动作，误触发会让用户少赚，
# 门槛不能低于「可作为买卖点」。两者当前同集合，但语义不同，保留独立定义以便日后分化。
ESCALATION_TIERS = frozenset({"verified"})

TIER_LABEL = {
    "verified": "已验证",
    "preliminary": "初步",
    "unsupported": "未获支持",
    "unknown": "未验证",
    "not_testable": "不可回测",
}

# 展示层角标（短，避免撑破表格单元格）
TIER_BADGE = {
    "verified": "已验证",
    "preliminary": "初步",
    "unsupported": "观察",
    "unknown": "观察",
    "not_testable": "观察",
}


@dataclass(frozen=True)
class Evidence:
    """单条技巧的证据记录。"""

    tier: str
    summary: str
    provenance: str

    @property
    def label(self) -> str:
        return TIER_LABEL.get(self.tier, self.tier)

    @property
    def badge(self) -> str:
        return TIER_BADGE.get(self.tier, "观察")

    @property
    def actionable(self) -> bool:
        return self.tier in ACTIONABLE_TIERS

    def as_dict(self) -> dict:
        return {
            "tier": self.tier,
            "label": self.label,
            "badge": self.badge,
            "summary": self.summary,
            "provenance": self.provenance,
            "actionable": self.actionable,
        }


# 证据快照。改这张表时必须同步改这里 —— 它是「这套结论是什么时候、用什么口径跑出来的」。
SNAPSHOT = {
    "run_at": "2026-09-16",
    "pool": "42 只行业分散大中盘（tactic_backtest_service.DEFAULT_POOL）",
    "eval_bars": 250,
    "horizons": [5, 10, 20],
    "prefix_lookback": 390,
    "generated_by": "POST /api/backtest/tactic（walk-forward，命中后当日收盘入场，命中后 horizon 日内去重）",
    "note": (
        "同一口径复跑 2026-09-13 的结论：揉搓线洗盘的「唯一稳定正超额」**未能复现**"
        "（当年 +4.7/+6.0/+9.5pt，本次 +3.4/+2.3/+0.8pt）。"
        "当年的正值落在噪音范围内（z=1.05），说明它更像抽样波动而非稳定优势。"
        "两次口径差异：当年评估窗口更长（每只约 380 个评估日），本次为 240 个。"
    ),
}

_RUN = "2026-09-16 复跑：42 只池 · 每只 640 根日线 · 240 个评估日 · 持有 5/10/20 日"

EVIDENCE: dict[str, Evidence] = {
    "cycle_resonance": Evidence(
        tier="preliminary",
        summary=(
            "口径修复后首次能真正回测：命中 5 次，胜率超额 +35.7 / +37.1 / +39.1pt（5/10/20 日），"
            "收益超额 +4.63 / +1.97 / +1.99；但 n=5 远低于判定显著所需的 30 次，"
            "统计量不可靠。属「值得跟踪的线索」，不是结论。"
            "（2026-09-13 时该技巧因日线 640 根上限无法计算月线 MACD，等同不可用）"
        ),
        provenance=_RUN + "；且 2026-09-16 才改为按周期取真实周线/月线",
    ),
    "intraday_divergence": Evidence(
        tier="not_testable",
        summary="需要分钟级历史 K 线，当前数据源只提供日线历史，无法回测。",
        provenance="数据源能力限制（长期有效）",
    ),
    "wash_scrub": Evidence(
        tier="unsupported",
        summary=(
            "样本充足（命中 67/42/36 次）但没有优势：胜率超额仅 +3.4 / +2.3 / +0.8pt，"
            "z = 0.56 / 0.30 / 0.10，收益超额 +0.18 / +0.03 / +0.43 —— 全部落在噪音里。"
        ),
        provenance=_RUN,
    ),
    "guillotine": Evidence(
        tier="unsupported",
        summary=(
            "方向性胜率超额稳定为正（+13.3 / +11.5 / +11.8pt），但**收益超额为负或≈0**"
            "（−0.06 / −0.87 / +3.50），且 n=22 未达显著。"
            "即「命中后确实更容易跌」，但按它减仓并不比什么都不做更好 —— 只能作风险提示。"
        ),
        provenance=_RUN,
    ),
    "volume_floor": Evidence(
        tier="preliminary",
        summary=(
            "阈值放宽到 30% 后开始出信号，胜率超额 +11.2 / +17.1 / +59.1pt，收益超额 +0.41 / +4.04 / +11.37；"
            "但命中仅 9/5/5 次，20 日那个 z 值是小样本退化产物（5 次全对），不可采信。"
        ),
        provenance=_RUN + "（阈值为 30% 校准后口径）",
    ),
    "volume_peak": Evidence(
        tier="unsupported",
        summary=(
            "超额符号不稳定（胜率超额 −4.9 / +3.4 / +1.2pt），且「换手率 >30%」缺少历史数据、"
            "回测只覆盖了「涨幅 + 天量」两个条件，现有数字不能代表完整规则。"
        ),
        provenance=_RUN + "；换手率条件按数据缺失处理",
    ),
    "macd_zone_cross": Evidence(
        tier="unsupported",
        summary=(
            "样本充足（命中 254/231/181 次）且三个持有期全为负：胜率超额 −2.2 / −1.4 / −4.4pt，"
            "收益超额 −0.27 / −0.46 / −1.00。零轴上下方的区分没有带来任何优势。"
        ),
        provenance=_RUN,
    ),
    "ma10_break": Evidence(
        tier="unsupported",
        summary=(
            "样本充足（命中 453/406/287 次），胜率超额 +3.4 / +3.0 / −0.2pt，"
            "z = 1.42 / 1.19 / −0.07 均未达显著，20 日转负 —— 约 400 次命中仍无优势，"
            "说明这不是样本不足而是效果不存在。"
        ),
        provenance=_RUN,
    ),
    "ma20_slope": Evidence(
        tier="unsupported",
        summary=(
            "5 日与 10 日收益超额为负（−0.26 / −0.35），胜率超额 −5.4 / −5.0pt；"
            "当前 5%~20% 的「黄金区间」口径跑不赢基准，需重新校准区间或放弃该技巧。"
        ),
        provenance=_RUN,
    ),
}

# 非形态策略的证据登记，与 EVIDENCE 分**命名空间**。
#
# 为什么不合并：`EVIDENCE` 的 key 必须与 `pattern_service.TACTICS` 一一对应，
# 这条不变量由 `test_tactic_evidence.test_every_tactic_is_registered` 锁定，
# 它保证「每个形态都登记了证据」这个检查真的成立。把 limitup_relay 这类
# 策略混进去，那条检查就退化成「表和自己相等」，守卫直接失效。
#
# 两条约束对两个命名空间同样适用：
# 1. 未 verified 一律 actionable=False（能否进买点位置）；
# 2. 只有收益口径可回测的条目才允许升到 verified —— 见文件头的「中间指标」说明。
STRATEGY_EVIDENCE: dict[str, Evidence] = {
    # 口径与形态回测完全不同：来自 limitup_service.relay_backtest（涨停池交集），
    # 因此不进 SNAPSHOT（SNAPSHOT 专指形态回测那一次跑批）。口径见 calibers.limitup_relay。
    "limitup_relay": Evidence(
        tier="preliminary",
        summary=(
            "晋级率口径可回测、方向为正：首板→2板 16.3%（n=601）、2板→3板 33.3%（n=99）、"
            "3板→4板 40.0%（n=35），连板之后继续连板的概率约为首板的两倍。"
            "但**收益口径不可回测** —— 涨停池只给收盘封板状态，拿不到次日实际成交价"
            "（连板股常以一字板开盘，晋级了也未必买得到）。晋级率是必要非充分条件，"
            "不能换算成胜率或期望收益，故停在「初步」，**样本量再大也不升级**。"
            "另一条反向线索：板块聚集度越高，首板晋级率反而越低"
            "（同板块 ≥5 家 9.2% / n=98，3-4 家 15.0% / n=147，1-2 家 18.8% / n=356），"
            "即「追最热的板块」在现有数据下**没有得到支持**，可能是情绪一致后的退潮前兆。"
        ),
        provenance=(
            "2026-09-17 首跑 limitup_service.relay_backtest：东财涨停池，"
            "有效窗口 2026-08-28 ~ 09-16 共 13 个交易日对 / 764 个样本"
            "（接口仅回溯约 15 个交易日，样本窗口天然受限）"
        ),
    ),
}

# 两个命名空间的 key 必须互斥：`_lookup` 是短路求值（先 EVIDENCE 后 STRATEGY_EVIDENCE），
# 重名会让策略记录被形态静默覆盖。导入期直接炸掉，比运行到 UI 上才发现好。
_OVERLAP = set(EVIDENCE) & set(STRATEGY_EVIDENCE)
if _OVERLAP:  # pragma: no cover - 导入期自检
    raise RuntimeError(f"tactic_evidence：EVIDENCE 与 STRATEGY_EVIDENCE 存在重复 key {sorted(_OVERLAP)}")


def _lookup(key: str) -> Evidence | None:
    """跨命名空间查记录。

    刻意**每次重新查**、不做导入期合并快照：`EVIDENCE` 需要在运行时被替换
    （`test_actionable_tier_unlocks_execution` 就用 monkeypatch 模拟「某形态已验证」，
    以锁定闸门双向有效）。冻结的合并字典会让那条测试变成死开关。
    """
    return EVIDENCE.get(key) or STRATEGY_EVIDENCE.get(key)


def get(key: str) -> Evidence:
    """取证据记录；未登记的技巧按最保守的 `unknown` 处理（不给动作）。

    形态（`EVIDENCE`）与策略（`STRATEGY_EVIDENCE`）两个命名空间都能命中。
    """
    return _lookup(key) or Evidence(
        tier="unknown", summary="该技巧尚未登记证据等级。", provenance="未登记"
    )


def tier_of(key: str) -> str:
    return get(key).tier


def is_actionable(key: str) -> bool:
    """是否允许出现在「买点 / 卖点」位置。"""
    return get(key).actionable


def is_escalatable(key: str) -> bool:
    """是否允许把「持有观察」升级为「建议减仓」。"""
    return get(key).tier in ESCALATION_TIERS


def describe(key: str) -> dict:
    return get(key).as_dict()


def gate_note(key: str) -> str:
    """命中但证据不足时给展示层的替代文案（替代「可分批建仓」这类动作话术）。"""
    ev = get(key)
    if ev.actionable:
        return ""
    return f"观察池 · {ev.label}：{ev.summary}"


def survey() -> dict:
    """整体覆盖情况，供接口/文档自查用。"""
    counts: dict[str, int] = {}
    for ev in EVIDENCE.values():
        counts[ev.tier] = counts.get(ev.tier, 0) + 1
    return {
        "total": len(EVIDENCE),
        "actionable": sum(1 for ev in EVIDENCE.values() if ev.actionable),
        "by_tier": counts,
        "snapshot": SNAPSHOT,
    }


def strategy_survey() -> dict:
    """非形态策略的证据覆盖情况。

    刻意与 `survey()` 分开：`survey()` 只统计 `EVIDENCE`（形态），
    它的 total 被守卫测试锁定为形态数量；把策略算进去会让那个断言失去意义。
    """
    counts: dict[str, int] = {}
    for ev in STRATEGY_EVIDENCE.values():
        counts[ev.tier] = counts.get(ev.tier, 0) + 1
    return {
        "total": len(STRATEGY_EVIDENCE),
        "actionable": sum(1 for ev in STRATEGY_EVIDENCE.values() if ev.actionable),
        "by_tier": counts,
    }
