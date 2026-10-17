"""今日总指令：把各链路结论排成一张行动清单（C）。

## 它解决什么

项目里方向、仓位、板块、持仓、涨停情绪分散在五处，用户要自己在脑子里合成
「今天到底该干什么」。本模块把它们汇成**一张按风险优先排序的清单**。

## ⚠️ 为什么不做加权合成分

这是本模块最重要的设计约束：方向分、仓位上限、板块四态、个股信号、涨停情绪
**高度相关** —— 它们是同一轮行情的不同切面。把它们加权相加，等于把同一个信号
放大 N 倍（``MEMORY-FEATURES`` 第 7.5 节点名的问题， regime 打分踩过）。

所以本模块：

* **不产出任何「综合分」「健康度」「今日评分」**；
* 各项**并列**展示，每项自带口径（``caliber``）与免责；
* 显式声明**不可比、不可加**（``incomparable_note``）——
  用户把「仓位 1 成」和「板块加速流入 1 个」并排看到时，
  必须知道这两件事不是同一把尺子上的两个数。

## 排序

按 ``decision.DECISION_ORDER``（sell → reduce → buy → add → hold → skip）：
风险处置先于开仓。这不是「重要性打分」，是**该先动谁**的答案。

## 输入

全部复用 briefing 已聚合的数据，**不新取数**（避免给首屏加延迟）。
"""
from __future__ import annotations

from app.services import decision

#: 各项的来源标识（前端用于分组与图标，不作为排序依据）
SOURCE_ORDER = ("holding", "position", "board", "morning", "limitup")


def _item(
    source: str,
    action: str,
    headline: str,
    detail: str,
    caliber: str,
    *,
    trigger: str | None = None,
) -> dict:
    """组装一条清单项。动作一律走 decision 契约，不自造中文。"""
    d = decision.normalize(action)
    return {
        "source": source,
        "action": d,
        "label": decision.DECISION_LONG_LABEL[d],
        "headline": headline,
        "detail": detail,
        "caliber": caliber,
        "trigger": trigger,
        "order": decision.DECISION_ORDER.get(d, 99),
    }


def build_action_list(
    position_plan: dict | None = None,
    holding_decisions: list[dict] | None = None,
    sector_follow: dict | None = None,
    morning_stocks: list[dict] | None = None,
    limitup_advice: dict | None = None,
) -> dict:
    """汇生成本日行动清单。

    任何一块数据缺失时**跳过该项**（不是填「无」也不是猜）——
    缺失与「今天没事发生」必须可区分，否则用户会把接口失败读成市场平静。
    """
    items: list[dict] = []

    # ① 持仓决策（风险处置，排最前）
    for d in holding_decisions or []:
        action = (d.get("decision") or {}).get("action")
        if action not in ("sell", "reduce"):
            continue      # hold / skip 不进清单 —— 它们不需要「行动」
        name = d.get("name") or d.get("code") or "持仓"
        items.append(
            _item(
                "holding",
                action,
                f"{name} · {decision.DECISION_LABEL[action]}",
                (d.get("decision") or {}).get("reason") or "",
                "口径：锚定结构位（支撑/压力/止损位），不用现价系数；样本为你的持仓。",
                trigger=(d.get("decision") or {}).get("trigger"),
            )
        )

    # ② 仓位上限（A 的结构化决策）
    if position_plan:
        cap = position_plan.get("position_cap")
        items.append(
            _item(
                "position",
                position_plan.get("action") or "hold",
                f"总仓位最多 {cap} 成" if cap is not None else "总仓位上限待定",
                position_plan.get("reason") or "",
                "口径：方向分 + 情绪温度的降档合成，只降不上调；"
                "是风险控制框架，不是收益预测。",
                trigger=position_plan.get("trigger"),
            )
        )

    # ③ 板块资金（只点名加速流入的，且不评分）
    if sector_follow and sector_follow.get("available"):
        longs = [s.get("name") for s in (sector_follow.get("sectors") or []) if s.get("state") == "follow_accel"]
        if longs:
            items.append(
                _item(
                    "board",
                    "add",
                    f"资金进场板块：{'、'.join(longs[:3])}",
                    "这些板块近 5 日主力净额累计为正且今日边际加速。",
                    "口径：东财板块级资金流（超大单+大单口径，非真实席位）；"
                    "当日横截面分位，换日即换基准、不可跨日比较。",
                )
            )

    # ④ 早盘推荐（买什么）
    stocks = morning_stocks or []
    with_buy = [s for s in stocks if s.get("buy_point")]
    if with_buy:
        names = "、".join(str(s.get("name") or s.get("code")) for s in with_buy[:3])
        items.append(
            _item(
                "morning",
                "buy",
                f"到价才成交：{names}",
                f"共 {len(with_buy)} 只给了挂单价（结构位，不随现价漂移）。",
                "口径：买入侧锚定结构位；实测超额为负，是价位参考不是买入指令。",
            )
        )

    # ⑤ 涨停环境（能不能碰连板）
    if limitup_advice:
        level = str(limitup_advice.get("level") or "")
        if level:
            # hunt/watch/avoid 是**环境质量**档位，不是买卖动作 ——
            # 映射到 skip/hold，不用 add/buy（那会把「环境允许」读成「该买了」）
            mapped = "hold" if level == "hunt" else "skip"
            # 标题字段是 `title`（limitup_service.play_advice），不是 label
            title = str(limitup_advice.get("title") or limitup_advice.get("label") or level)
            reasons = limitup_advice.get("reasons") or []
            detail = "；".join(str(r) for r in reasons[:3]) or str(limitup_advice.get("note") or "")
            items.append(
                _item(
                    "limitup",
                    mapped,
                    f"连板环境：{title}",
                    detail,
                    "口径：涨停池情绪温度（炸板率/梯队断层），证据档未获支持，"
                    "只说明环境能不能碰，不是买点。",
                )
            )

    items.sort(key=lambda x: (x["order"], SOURCE_ORDER.index(x["source"]) if x["source"] in SOURCE_ORDER else 99))

    return {
        "items": items,
        # 显式的不可比声明 —— 用户把各项并排看到时必须知道它们不是同一把尺子
        "incomparable_note": (
            "以上各项来自不同链路、不同口径（持仓看结构位、仓位看方向分与情绪、"
            "板块看资金流横截面、推荐看结构位、连板看情绪温度），"
            "彼此不可比、不可相加，也不构成「今日评分」。排序只表示该先动谁。"
        ),
        "caveats": [
            "本清单是结构读数汇总，不是投资建议；未定义收益口径前不产出买卖指令。",
            "任一项取数失败时该项缺席（不是「今天没事」），请注意与空仓状态区分。",
        ],
    }
