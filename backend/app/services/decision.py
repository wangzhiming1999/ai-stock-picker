"""统一决策契约：用户可见的动作词只有 6 个，各模块不得自造措辞。

为什么需要这个模块
------------------
此前项目里并存 4 套动作枚举 —— `TradePlan.action`（buy/add/hold/reduce/avoid）、
盯盘 `advice.action`（buy/sell/hold/stop）、涨停带 `play_advice.level`
（hunt/watch/avoid），以及 portfolio / pattern / sandu / trend 直接拼中文串
（「持有观察」「建议减仓」「可关注」「继续跟踪」…）。

后果是前端只能靠正则去猜「建议减仓」这四个字是什么意思
（见 `frontend/src/lib/tone.ts::actionBadge`），
而用户在页面上看到的是 9 种说法表达同一件事，读起来像「系统也没主意」。

本模块是动作词的**唯一来源**：

- ``DECISIONS`` —— 允许出现在用户可见文案里的动作，共 6 个；
- ``skip``（不参与）是**一等公民**。证据不足时输出的应当是「不参与」这个明确结论，
  而不是降级成「观察 / 关注 / 留意 / 继续跟踪」这类没有结论的措辞。
  「不参与」必须带 reason 说明为什么不做，以及什么条件满足才转成动作 —— 空仓也是决策。
- ``normalize()`` —— 把历史遗留的中文串 / 英文标记归一化到 6 态，供灰度期共存。

纪律（不得违反）
----------------
- 动作词只描述「我打算做什么」，不表达价格方向。
- 负期望策略仍不得出现买入类动作（见 ``test_limitdown_service`` /
  ``test_limitup_premium`` 的证据闸门测试）；``normalize`` 只是映射函数，
  它识别出 ``buy`` 不代表允许输出买入文案。
- 免责句（「不是买入指令」「仅供参考」）不属于模棱两可，**不得**因为本次收口而删除。
"""

from __future__ import annotations

from typing import Literal, get_args

Decision = Literal["buy", "add", "hold", "reduce", "sell", "skip"]

#: 全部合法动作（顺序即 `DECISION_ORDER` 的语义序，不是优先级）
DECISIONS: tuple[str, ...] = get_args(Decision)

#: 用户可见标签。改这里就等于改全站文案，**不要在调用点另写中文**。
DECISION_LABEL: dict[str, str] = {
    "buy": "买入",
    "add": "加仓",
    "hold": "持有不动",
    "reduce": "减仓",
    "sell": "卖出",
    "skip": "不参与",
}

#: 长标签：用在有空间的位置。「不参与」带上原因才叫决策，否则又变成一个模糊词。
DECISION_LONG_LABEL: dict[str, str] = {
    **DECISION_LABEL,
    "skip": "不参与（空仓等待）",
}

#: 处置优先级：风险处置先于开仓。数值小 = 更该立刻看。
DECISION_ORDER: dict[str, int] = {
    "sell": 0,
    "reduce": 1,
    "buy": 2,
    "add": 3,
    "hold": 4,
    "skip": 5,
}

#: 开仓类动作。这两类若说不出「什么价才动手」，就不算一条决策。
ENTRY_DECISIONS: tuple[str, ...] = ("buy", "add")

#: 归一化规则，**有序**：命中即返回。
#:
#: 顺序不能乱：「持有观察」同时含「持有」与「观察」，必须由 hold 先吃掉；
#: 「暂不参与」含「暂不」，由 skip 收；「建议减仓」不能被 buy 的规则误伤。
_NORMALIZE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("sell", ("卖出", "清仓", "止损", "sell", "stop")),
    ("reduce", ("减仓", "止盈", "降仓", "reduce")),
    ("add", ("加仓", "补仓", "add")),
    ("buy", ("买入", "建仓", "开仓", "打板", "buy")),
    ("hold", ("持有", "hold")),
    (
        "skip",
        (
            "不参与", "空仓", "观望", "观察", "跟踪", "关注", "留意",
            "回避", "放弃", "只看", "暂不", "等待", "avoid", "skip",
        ),
    ),
)


def is_decision(value: str | None) -> bool:
    """是否已是合法动作标记（用于判断上游是否已按契约产出）。"""
    return isinstance(value, str) and value in DECISIONS


def normalize(raw: str | None, *, default: str = "skip") -> str:
    """把任意历史措辞归一化到 6 态。

    识别不了时返回 ``default``，默认为 ``skip`` —— 宁可判成「不参与」，
    也不能把一段读不懂的文案渲染成开仓信号。

    >>> normalize("建议减仓")
    'reduce'
    >>> normalize("持有观察")
    'hold'
    >>> normalize("可考虑逢低分批关注")
    'skip'
    """
    text = (raw or "").strip()
    if not text:
        return default
    if text in DECISIONS:
        return text
    lowered = text.lower()
    for action, words in _NORMALIZE_RULES:
        if any(w in text or w in lowered for w in words):
            return action
    return default


def label(action: str | None, *, long: bool = False) -> str:
    """动作的展示文案。未知动作按 ``skip`` 渲染，不抛异常（前端宁可不动作）。"""
    d = action if is_decision(action) else normalize(action)
    table = DECISION_LONG_LABEL if long else DECISION_LABEL
    return table.get(d or "skip", DECISION_LABEL["skip"])


def make(
    action: str | None,
    *,
    reason: str = "",
    trigger: str | None = None,
    invalidation: str | None = None,
) -> dict:
    """组装一条完整决策（四要素）。

    ``reason`` 说清为什么是这个动作，``trigger`` 说什么条件下动作才成立，
    ``invalidation`` 说什么信号出现说明这条结论已作废 —— 缺一不可，
    因为「什么条件下转成别的动作」正是它区别于模糊措辞的地方。

    本函数不做业务降级（例如「买入但没说触发价」要不要退回不参与，属于各链路
    自己的证据纪律），只负责归一化与组装。
    """
    d = normalize(action)
    return {
        "action": d,
        "label": DECISION_LONG_LABEL[d],
        "reason": reason,
        "trigger": trigger,
        "invalidation": invalidation,
    }
