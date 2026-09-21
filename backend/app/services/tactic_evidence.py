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
    "pool": "42 只行业分散大中盘（tactic_backtest_service.TACTIC_BACKTEST_POOL）",
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
            "超额符号不稳定（胜率超额 −4.9 / +3.4 / +1.2pt）。"
            "⚠️ 这些数字出自**换手率补齐之前**的口径 —— 当时历史换手率拿不到，"
            "回测只覆盖了「涨幅 + 天量」两个条件。历史换手率已于 2026-09-21 接入回测"
            "（腾讯日线行索引 7），「换手率 >30%」现在是**生效的第三个条件**，命中数只会更少，"
            "所以上面这组数字**不能**再用来代表当前规则 —— 必须重跑后重新登记。"
        ),
        provenance=_RUN + "；该次跑批为旧口径（缺换手率条件）；换手率已接入，结论待重跑覆盖",
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
    # 筹码形态（2026-09-21 新增）：尚未回测，先挂 unknown 进观察池。
    # 数据链路：chip_service 自复刻东财 CYQ（已与 akshare 输出对齐，偏差 <2%）；
    # 历史回测路径：每日逐根 K 线复算 CYQ 可行但成本高（90 日 × 每根 120 窗口），
    # 待回测时若成本过高可只算命中日 ±1，或降采样评估。
    "chip_single_peak": Evidence(
        tier="unknown",
        summary=(
            "单峰密集（90 集中度 ≤0.07 且收敛、现价贴峰）尚未回测，无有效性证据。"
            "传统说法「单峰密集蓄势」未经本项目口径验证，仅作观察池登记。"
        ),
        provenance="2026-09-21 新增，数据=chip_service 自复刻 CYQ（与东财官方值偏差 <2%）",
    ),
    "chip_low_profit": Evidence(
        tier="unknown",
        summary=(
            "低位低获利盘（获利比例 ≤10% + 60 日低位区）尚未回测。"
            "注意「深跌=便宜」在本项目多次被证伪（跌停次日、低开再买均为负期望），"
            "此形态是否不同待回测回答。"
        ),
        provenance="2026-09-21 新增，数据=chip_service 自复刻 CYQ",
    ),
    "chip_transfer_up": Evidence(
        tier="unknown",
        summary=(
            "筹码转移向上（获利比例 10 日 +5pt、成本重心上移、无深回撤）尚未回测。"
            "「筹码转移」类说法样本口径差异大，必须用本项目统一口径跑过才算数。"
        ),
        provenance="2026-09-21 新增，数据=chip_service 自复刻 CYQ",
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
    # 与 limitup_relay 是**同一批涨停池数据的两种口径**：relay 是「封板能不能延续」（状态），
    # 这边是「明天开盘卖出能赚多少」（收益）。两者不可相互换算、不可相加。
    # 这是本项目所有验证里**唯一收益为正、且符号不随基准翻转**的方向 ——
    # 也正因如此更需要把边界写清楚，否则很容易被读成「打板稳赚」。
    "limitup_premium": Evidence(
        tier="preliminary",
        summary=(
            "**收益口径可回测，方向为正 —— 目前唯一没被否掉的方向。** "
            "两口径互证：涨停池口径（东财真实封板字段，14 个交易日 / n=758）期望 +2.00% / "
            "中位 +1.27% / 胜率 60.6%；日 K 口径（548 只 × 250 交易日 / n=4953）"
            "期望 +1.91% / 中位 +1.16% / 胜率 61.7% / 超额沪深300 +2.03%。"
            "同一批股票的**非涨停日**对照（n=10694）期望 −0.06% —— 组间对比干净，"
            "说明「涨停」这个条件本身贡献约 2 个百分点，不是股票池偏差。"
            "13/13 个月正期望；打平需胜率 35.3%（实际 51.4%），盈亏比结构健康"
            "（对比跌停那条：打平需 80.6% 而实际只有 4.5%）。"
            "**但收益大头落在买不进的档**：量比 <1（缩量一字/秒板）期望 +3.45%，"
            "随量比单调衰减到 ≥8（巨量）−0.03%；涨停池口径同向，换手 <5% +3.31% → ≥30% +0.40%。"
            "可成交口径（量比 ≥2）≈ +1.0%、超额 +1.1%、11/12 个月正。"
            "有区分度的筛选器：首封 ≤09:35 期望 +3.67%，"
            "**尾盘封板（≥14:00）是唯一负期望档（−0.48%，胜率 37.8%）**；"
            "炸板 ≥3 次降至 +0.68%；连板高度单调（首板 +1.61% < 2板 +3.37% < 3板 +4.13%）。"
            "**停在「初步」的原因是可成交性仍是代理口径**：涨停池快照没有量比字段，"
            "本项目也没有逐笔数据，真实可成交率未知，且未计滑点 —— "
            "按证据纪律，**不能只因为收益为正就升级为 verified**。"
        ),
        provenance=(
            "2026-09-18 两轮实测（临时脚本，跑完即删，未入库）："
            "① 涨停池口径 = 东财涨停池真实封板字段（fbt / fund / zbc / lbc / hs），"
            "窗口 2026-08-28 ~ 09-17 共 14 个交易日，事件 771 → 可用 758；"
            "② 日 K 口径 = 同一批 548 只代码 × 250 交易日自行识别涨停（收盘涨幅 ≥9.5%），"
            "事件 4832~5111，覆盖 2025-09 ~ 2026-09 共 13 个月。"
            "两口径统一减沪深300 同起止，并换中证1000 做符号翻转检验。"
            "⚠️ 股票池是「近 14 天涨停过的活跃股」回溯 250 天，非随机样本"
            "（组间对照可缓解但未消除）；窗口只有 1 年，量级不可外推。"
        ),
    ),
    # 与 limitup_relay 的镜像关系：那边是涨停池的状态延续率（缺收益口径），
    # 这边**拿得到收益**（跌停价可直接成交，次日开盘价可查），因此能算出真实期望 ——
    # 结论是负的，所以它是有明确结论的 unsupported，而不是「口径不完整」。
    "limitdown_repair": Evidence(
        tier="unsupported",
        summary=(
            "**收益口径可回测，结论为负。** 2026-08-31~09-17 共 133 个样本："
            "D 日跌停价买入 → D+1 集合竞价卖出，期望 −4.47%/次、胜率 4.5%、"
            "打平需 80.6% 胜率（均盈 +1.14% / 均亏 −4.74%），是典型的高胜率陷阱的反面 —— "
            "连胜率都不高。按「跌停板块」筛反而更差：同板块 ≥5 只跌停 −7.17%、"
            "2-4 只 −5.19%、仅 1 只 −4.04% —— 板块级同时跌停更像板块利空，不是个股错杀。"
            "「好买」与「次日修复」负相关：全天封死组期望 −6.23%、次日收盘仍跌停 26.7%；"
            "盘中开过板组 −4.25%、16.1%。竞价卖出是全天最差的时点 —— "
            "次日盘中最高价平均 +0.57%、50.4% 的样本曾转正，但覆盖不了平均低开；"
            "持有到 D+1 收盘 −3.94%、胜率 22.7%，仍为负。"
            "按当日跌停家数 / 板块跌停家数 / 连续跌停天数逐一切片，n≥8 的切片**无一为正期望**，"
            "说明这不是「没筛对条件」，而是这条路径本身为负。"
            "尾部：14.3% 的样本次日跌停开盘，其中 3 只一字跌停**卖不出去**（无法止损）。"
        ),
        provenance=(
            "2026-09-18 跑 limitdown_service.repair_backtest：东财跌停板池（getTopicDTPool）"
            "+ 腾讯日 K，有效窗口 2026-08-31 ~ 09-17 共 13 个交易日 / 133 个样本"
            "（跌停池与涨停池一样仅回溯约 15 个交易日，样本窗口天然受限）"
        ),
    ),
    # 盯盘 monitor 的支撑/压力/买卖点是**另一条独立于形态的建议链路**
    # （signal_service.compute_signals），此前没有登记在这里 —— 属于治理缺口本身。
    "strategy_scores": Evidence(
        tier="unsupported",
        summary=(
            "**四条策略分里两条的超额符号随基准翻转，按本项目回测铁律②视为零。** "
            "2025-01-02 ~ 2026-09-18，走查 walk-forward，取样宇宙 "
            "`backtest_service.STRATEGY_BACKTEST_POOL`（18 只），持仓 5 只 / 5 日调仓："
            "momentum +24.74%（vs 沪深300 **+7.99pp**、vs 同宇宙等权 +35.41pp，两基准同号）；"
            "trend +7.78%（vs 沪深300 **−8.97pp**、vs 同宇宙 +18.45pp，**符号翻转**）；"
            "volume +4.78%（vs 沪深300 **−11.97pp**、vs 同宇宙 +15.45pp，**符号翻转**）；"
            "value −29.94%（两基准均为负）。"
            "⚠️ 该宇宙自 2025 年以来跑输沪深300 达 27pp（同宇宙等权 −10.67%），"
            "**「跑赢自己的池」几乎不构成证据**；且此宇宙（18 只大票）与推荐实际面对的全市场"
            "（5400+ 只）不是同一个宇宙。因此只有 momentum 的方向值得继续观察，"
            "**不得据此声称推荐链路有效**。"
        ),
        provenance=(
            "2026-09-18 自建只读脚本（.workbuddy/tmp/strategy_grade_backtest.py）调用 "
            "backtest_service.run_backtest；数据源 akshare 腾讯日 K；"
            "未计手续费与滑点，未做显著性检验（单次跑批无 n/z）。"
        ),
    ),
    "monitor_levels": Evidence(
        tier="unsupported",
        summary=(
            "**买入侧口径完整、结论为负；卖出侧无信息量。** 42 只池 × 每只 250 个评估日 "
            "= 10500 个（股票,交易日）样本，2024-08 ~ 2026-09。按 `_advice` 分档，"
            "入场=当日收盘、出场=收盘、超额=减沪深300：「回踩可买」n=1790，"
            "超额 h5 −0.53%（z=−5.82）/ h10 −0.87%（z=−6.93）/ h20 −1.40%（z=−7.43），"
            "胜率 40~44%；挂单价次日可成交 66.3%，**成交之后** h10 −0.49%、胜率 42.1%，"
            "说明不是「买不进」，是买进了也不赚。「压力减仓」n=411 后续 h5 −0.02%、"
            "下跌概率 53% —— 与随机不可区分。修复定档基准后可触发的风控档"
            "（跌破支撑 14.6% / 突破 8.1% / 止损 0.9%）具备方向性：止损后 h5 相对基准 −1.31%，"
            "即止损挡住的确实是继续下跌。"
        ),
        provenance=(
            "2026-09-18 自建只读脚本（.workbuddy/tmp/monitor_grade_backtest.py）复刻 "
            "monitor._advice 分档阈值与 signal_service.compute_signals，"
            "数据源为腾讯日 K 640 根（含 OHLC）；未计滑点与手续费。"
            "对照：同口径下「持有观察」档超额 ≈ 0（h5 −0.06%），可作基准噪声尺度。"
        ),
    ),
    # 决策先锋（vanguard_service）：暗盘资金 / 趋势 / 活跃度 三维打分榜。
    #
    # 为什么只能是 preliminary 而不是 verified：这条榜**从来没有跑过收益回测**。
    # 三维分是「这一只票今天的资金 / 趋势 / 活跃度读数」，不是「买它之后能赚多少」的估计。
    # 而且其中两维本身依赖代理口径：
    #   ① 暗盘资金用的是东财 **主力净流入（超大单+大单）**，这是「大单口径」不是「暗盘」——
    #      A 股没有公开的暗盘成交数据，产品名与数据口径必须分开说。
    #   ② 板块强度用的是**当日横截面分位**（相对分位，不是绝对阈值），
    #      换一天就换一套基准，因此它天然不可跨日比较。
    # 按证据纪律，「有 n 且收益可回测」才可能升 verified；这条都不满足 → 永久停在「初步」。
    # 前端因此只允许把它渲染成**排序/筛选读数**，不得出现「可买入」一类动作话术。
    "vanguard_three_dim": Evidence(
        tier="preliminary",
        summary=(
            "**三维打分榜，非收益口径，因此不具备升级条件。** 三个维度分别是："
            "暗盘资金（东财批量资金流排行里的主力净流入额 / 净占比 / 超大单，"
            "⚠️ 数据口径是**大单口径**，A 股没有公开暗盘成交数据，产品名与口径不是一回事）、"
            "趋势（均线排列 / MA20 斜率 / 距 250 日高点 / MACD / 20 日涨幅 / 底部抬升）、"
            "活跃度（按市值分层的换手率 / 量比 / 成交额 / 近 5 日振幅 / 盘中 5 分钟涨跌）。"
            "综合分 = 三维加权（资金 0.40 / 趋势 0.35 / 活跃度 0.25；资金维不可用时"
            "把权重**重新归一化到可用维度**并显式标记，不拿 0 分冒充缺失）。"
            "同屏的「买卖时机」直接复用 `signal_service.compute_signals` 的结构位，"
            "其证据等级见 `monitor_levels` —— **买入侧实测为负**，故只能作价位参考。"
            "「板块强度」用当日横截面分位合成（资金 0.40 / 动量 0.35 / 广度 0.25），"
            "**分位换日即换基准，不可跨日比较**；「主力抱团」是涨停池板块聚集度与"
            "板块资金净流入的合读，同样不是收益率口径。"
        ),
        provenance=(
            "2026-09-21 首次实现（vanguard_service + /api/market/vanguard）。"
            "数据源：东财 clist 批量端点（fid=f62 资金流排行，非逐股请求）+ "
            "全市场快照（market_spot_cache / 东财 push2）+ 腾讯日 K 250 根 + 东财涨停池。"
            "**未跑任何收益回测，无 n、无 z、无基准超额** —— 这正是它停在「初步」的原因；"
            "升档的唯一路径是先做 walk-forward：以三维分为入场信号，按 T+1 铁律结算"
            "（出场 ≥ 买入日+1、减同期指数并换基准验符号翻转、只用开/收盘价、"
            "可成交性独立复核），样本 ≥30 且各持有期超额同号为正。"
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
