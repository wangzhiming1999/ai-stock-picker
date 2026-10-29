"""测量口径登记表：「胜率」这个词在本系统内的唯一定义来源。

## 为什么需要单独一层

「验证」页同屏会出现 4 个都叫「胜率 / 命中率」的百分比：

| 出处 | 标的 | 持有期 | 分类数 | 有没有基准 |
|---|---|---|---|---|
| 大盘推衍 | 上证指数 | 预测日当日 | 3（含震荡） | 无 |
| 每日推荐 | 个股 | T+1 收盘 | 2 | 无 |
| 策略回测 | 组合 | 每个调仓期 | 2 | 有（沪深300） |
| 形态回测 | 个股 | N 个交易日 | 2（按方向） | 有（同区间同持有期） |

读者会很自然地把它们当成同一把尺子——并排放在同一屏、都叫「胜率」，看起来就该能比。
但它们**不可比、不可加**：持有期差 1 天 vs 20 天，标的差大盘 vs 个股，分类数差 2 vs 3，
一半有基准一半没有。这就是用户说的「数据不准确」里最隐蔽的一类：
数字各自没算错，但放在一起就会得出错误结论。

本模块把这些口径写死在代码里，由接口随数据一起下发；前端只负责展示，不自己解释。
新增任何「率」之前，先在这里登记口径 —— 没有登记的百分比不允许出现在界面上。
"""
from __future__ import annotations

# 口径字段含义固定，前端按 name/window/rule 三行展示：
#   name   界面上的名字（要能一眼看出标的与持有期）
#   target 标的
#   window 持有期 / 判定时点
#   bucket 分类数（决定「随机基线」的量级，直接影响命中率的解读）
#   benchmark 对比基准（「无」必须显式写出，不能留空 —— 空值看起来像忘了填）
#   rule   判定规则（可复核，含阈值）
#   unit   1 个样本代表什么
#   pitfall 这个口径最容易骗自己的地方
CALIBERS: dict[str, dict] = {
    "prediction": {
        "key": "prediction",
        "name": "大盘方向命中率（上证指数 · 单日 · 三分类）",
        "target": "上证指数",
        "window": "预测日当日（开盘前给出、收盘后结算）",
        "bucket": "三分类：上涨 / 下跌 / 震荡",
        "benchmark": "朴素基线：全部猜「震荡」（= 震荡日占比）。"
        "本口径预测的就是上证指数本身，无法「换基准」——换了就不是同一标的",
        "rule": "实际涨跌幅 ≥ +0.5% 记上涨、≤ −0.5% 记下跌、其余记震荡；与预测方向一致即命中。"
        "方向分落在中间带（3.8~6.2）即判「震荡」",
        "unit": "每条预测 = 1 个样本",
        "pitfall": "⚠️ **「震荡」是中间带的默认标签，而它天然是三分类里最好蒙对一个的** —— "
        "震荡命中率通常远高于上涨/下跌，整体命中率因此主要在反映「震荡日有多少天」，"
        "而不是「预测准不准」。实测线上 n=50：震荡 75%、整体 66%、上涨 0%（n=2）。"
        "所以**整体命中率必须减去朴素基线（无脑全猜震荡）才是能力**，"
        "API 的 `baseline_comparison.edge_over_baseline` 就是这个差值；"
        "另外 `directional_hit_rate`（剔除震荡后的方向命中率）才是真正在判断方向的样本，"
        "通常小得可怜（实测 n=14），不足 30 不判显著。"
        "随机基线也不是 50%（三分类 + 中性带），中性带宽度会直接放大或缩小命中率。",
    },
    "recommendation": {
        "key": "recommendation",
        "name": "个股推荐次日胜率（T+1 · 扣费 · 对比沪深300）",
        "target": "每日推荐入选个股（source ∈ llm/rule）",
        "window": "T+1 首个交易日收盘",
        "bucket": "二分类：跑赢指数 / 跑输指数",
        "benchmark": "沪深300（同区间买入持有，代码 sh000300）",
        "rule": "净收益 net_return = 次日收益率 − 交易成本（分项：佣金万2.5、最低5元/笔 + 过户费0.001%双向 "
        "+ 印花税0.05%仅卖出 + 滑点0.05%）；按 5 万元名义额基准折算双边约 0.15%。"
        "超额 excess_return = net_return − 沪深300 同区间收益；excess_return > 0 即命中（扣费后仍跑赢指数）。"
        "同表的 source='quad'（四维榜 Top10）与 source='watch'（观察层）各自单列统计，"
        "不并入本口径 —— 三者入选机制不同，命中率不可相加",
        "unit": "每条推荐 = 1 个样本",
        "pitfall": "未跑 v14 迁移或指数数据缺失时，excess_return 为空，主口径不可信，"
        "前端会标注「未跑赢指数」并回退展示旧的「次日上涨」口径（不扣费、不对比基准，会偏高）。"
        "⚠️ 最低佣金是绝对额：单笔名义额 < 5 万元时真实成本率高于 0.15%（如 300 元单笔仅佣金即 1.67%），"
        "百分比口径对小单偏乐观。"
        "即便新口径成立，也只比 1 个交易日、且基准是宽基指数 —— 普涨时宽基也涨，"
        "超额胜率会系统性偏低，不能直接读成「推荐质量差」；样本 < 30 只时不判显著。",
    },
    "strategy_backtest": {
        "key": "strategy_backtest",
        "name": "策略回测期胜率（组合 · 调仓周期 · 对比沪深300）",
        "target": "按策略选出的组合",
        "window": "每个调仓期（默认 5 个交易日）",
        "bucket": "二分类：该期组合正收益 / 负收益",
        "benchmark": "沪深300（同区间买入持有）",
        "rule": "调仓期末组合市值相对期初上涨即记为「正收益期」；胜率 = 正收益期占比。"
        "换仓交易逐笔扣费（佣金最低5元/笔 + 印花税/过户费），持有期市值为含费净值",
        "unit": "每个调仓期 = 1 个样本（不是每只票 1 个样本）",
        "pitfall": "样本数 = 回测区间的调仓次数，通常只有几十个；与「个股胜率」的样本单位不同，"
        "不能与形态/推荐胜率混算",
    },
    "tactic_backtest": {
        "key": "tactic_backtest",
        "name": "形态前向收益胜率（个股 · 持有 N 日 · 对比同区间基准）",
        "target": "命中该形态的个股",
        "window": "命中后 N 个交易日（默认 5 / 10 / 20）",
        "bucket": "二分类（按方向）：买入形态看涨 / 卖出形态看跌",
        "benchmark": "同股票池、同区间、同持有期的无条件表现",
        "rule": "命中当日收盘入场，持有 N 个交易日后的收益（扣双边成本约 0.15%，浮盈/浮亏路径读数为毛值）"
        "方向一致即命中；命中后 N 日内去重；"
        "并同时给出同区间同持有期的无条件基准胜率",
        "unit": "每次命中 = 1 个样本",
        "pitfall": "唯一带基准的口径，但样本量门槛最高（≥30 次才判显著），多数形态达不到；"
        "持有期与「次日胜率」不同，两层数字不能并列比较",
    },
    "limitup_relay": {
        "key": "limitup_relay",
        "name": "连板晋级率（T+1 口径：N 板 → 次日 N+1 板）",
        "target": "当日收盘时为 N 连板的个股",
        "window": "次日（D+1 收盘后的封板状态）",
        "bucket": "二分类：次日仍在涨停池且连板数恰好 +1 / 其余（含停牌、未涨停、涨停但高度未+1）",
        "benchmark": "无（这是封板状态的延续率，不是收益率口径，没有可对比的收益基准；"
        "连板高度之间的差异只是分层对比，不是基准超额）",
        "rule": "D 日涨停池中 lbc = N 的个股，若 D+1 日涨停池里该代码的 lbc 恰为 N+1 记为晋级；"
        "停牌或未封板一律记未晋级（保守处理，不剔除样本）",
        "unit": "每只个股每个交易日 = 1 个样本",
        "pitfall": "⚠️ 这是**封板状态的延续率，不是收益率**，两者之间隔着一次「能不能买到」。"
        "连板股次日常以一字板开盘，晋级了也可能根本成交不了；而未晋级时高开低走单日亏 10% 以上很常见。"
        "所以晋级率高 ≠ 策略能赚钱，本口径**不能**换算成胜率、期望收益或盈亏比。"
        "另外东财涨停池只回溯约 15 个交易日（3 周），样本窗口天然受限，不能当作长期统计；"
        "且上游是多节点集群（响应带 svr 标识），实测同一历史日期的连板数字存在分钟级不一致，"
        "复跑会有 1~2 个百分点的漂移 —— 因此只看量级与方向，不要盯小数。",
    },
    "limitdown_repair": {
        "key": "limitdown_repair",
        "name": "跌停次日修复收益（个股 · T+1 集合竞价卖出）",
        "target": "当日收盘跌停的个股（东财跌停板池全量）",
        "window": "D+1 集合竞价成交（同屏对照：D+1 收盘、D+1 盘中最高）",
        "bucket": "二分类：D+1 开盘价 > D 日跌停价（竞价为正）/ 其余",
        "benchmark": "无（不与指数对比，因此无法区分「跌得多」与「跑输」）",
        "rule": "D 日以跌停价（= D 日收盘价）买入，D+1 以集合竞价成交价卖出；"
        "收益 = D+1 开盘 ÷ D 收盘 − 1。未计手续费与滑点。"
        "D+1 若为进行中交易日则只用开盘价（已确定），收盘口径置空而不是用实时价冒充。",
        "unit": "每只跌停股每个交易日 = 1 个样本",
        "pitfall": "⚠️ 这是**负期望**口径，不是机会口径 —— 它存在的意义是劝阻，不是筛选。"
        "实测（2026-08-31~09-17，n=133）期望 −4.47%/次、胜率 4.5%、打平需 80.6% 胜率。"
        "「跌停能买到」不等于优势：能轻松买到恰恰说明抛压无人承接，"
        "且越容易买到（全天封死）次日越差（−6.23% vs 盘中开过板的 −4.25%）；"
        "按「跌停板块」筛反而最差（同板块 ≥5 只跌停 −7.17%），因为那是板块级利空而非个股错杀。"
        "次日盘中最高价平均 +0.57%、50.4% 曾转正，说明反抽确实存在，但覆盖不了次日平均低开。"
        "T+1 下最需要防范的是**连续跌停**：D+1 一字跌停时挂单也卖不出去（实测占 2.3%），"
        "该策略在尾部**没有止损能力**。窗口仅 13 个交易日，量级不可外推。",
    },
    "limitup_premium": {
        "key": "limitup_premium",
        "name": "涨停次日溢价（个股 · T+1 集合竞价卖出 · 涨停价买入）",
        "target": "当日涨停的个股（东财涨停板池全量，含首板）",
        "window": "D+1 集合竞价开盘（同屏对照：D+1 收盘 / D+2 收盘）",
        "bucket": "连续收益口径（不给三分类）：收益 = D+1 开盘 ÷ D 日涨停价 − 1",
        "benchmark": "同股票池的非涨停日对照（n=10694，实测期望 −0.06% —— 即「涨停」这个条件"
        "本身贡献约 2 个百分点，组间对比干净）；另用沪深300 / 中证1000 做符号翻转检验",
        "rule": "D 日以涨停价（= D 日收盘价）买入，D+1 以集合竞价成交价卖出，满足 T+1。"
        "分档只按**涨停池快照自带字段**归档（换手率 / 首封时间 / 炸板次数 / 连板高度），"
        "逐档给历史期望；其中「可成交档」定义为换手率 ≥ 5%。",
        "unit": "每只涨停股每个交易日 = 1 个样本",
        "pitfall": "⚠️ 收益大头落在**买不进**的档：换手 <5%（缩量一字/秒板）期望 +3.31%，"
        "但正是挂不上单的那一批；换手 ≥5% 档期望收窄到 +0.40% ~ +1.62%，这才是可执行的区间。"
        "所以本口径的输出必须**同时报期望与可成交性**，只报期望会诱导去追买不到的一字板。"
        "「可成交性」是**代理指标**（池快照没有量比字段，用换手率替代），真实成交率未知，"
        "也未计滑点与手续费 —— 证据等级因此只能到 preliminary，"
        "**不能只因为收益为正就升级为 verified**。"
        "股票池是「近 14 天涨停过的活跃股」回溯 250 天，非随机样本（组间对照可缓解但未消除）；"
        "窗口只有 1 年，量级不可外推。与 limitup_relay 的关系：那是封板延续率、这是收益率，"
        "两者不可相互换算、不可相加。",
        # 系统制定计划所需的两个派生字段：计划持有期 + 历史赢面。
        # 产品从「给读数」升级为「系统替用户定计划周期」——不让用户自选周期，
        # 证据显示打板是短线题材、T+1 赢面最高最稳，故系统统一制定为 T+1。
        "plan_horizon": "T+1（次日集合竞价卖出）",
        "win_rate": (
            "全样本历史次日胜率约 60–62%（涨停池口径 60.6% / 日K口径 61.7%）；"
            "但收益大头落在买不进的换手<5% 档（期望 +3.31%），真正可成交的换手≥5% 档"
            "期望收敛至约 +1.0%、11/12 月为正，对应可成交胜率约 55%+。"
            "preliminary：可成交性为代理口径（池快照无量比字段，用换手率替代），未计滑点与手续费。"
        ),
    },
    "seize_reseal": {
        "key": "seize_reseal",
        "name": "回封候选次日收益（个股 · T+1 开盘卖出 · 收盘价代理入场）",
        "target": "当日炸板（曾触涨停后开板）且收盘仍贴着涨停（距涨停 ≤3%）的个股",
        "window": "D+1 开盘卖出",
        "bucket": "连续收益口径：收益 = D+1 开盘 ÷ D 日收盘价 − 1",
        "benchmark": "无独立对照组；与 limitup_premium（涨停价买入，期望 +2%）同屏时**必须分开报**，"
        "两者不可比、不可相加",
        "rule": "D 日以收盘价买入（雷达盘中 sighting 价格不可回溯，用收盘价做保守代理），"
        "D+1 以开盘价卖出；候选 = 炸板池中收盘距涨停 ≤3% 的票",
        "unit": "每只炸板股每个交易日 = 1 个样本",
        "pitfall": "⚠️ 实测为**负期望**（2026-09-09 ~ 09-30，n=81：期望 −0.72%、中位 −0.43%、"
        "胜率 32.1%；贴板 ≤1% 档更差 −1.06%）。炸板本身是分歧信号，收盘贴板不等于次日修复。"
        "该口径只用于风险提示，不构成抢封板机会；与「刚封板」档（limitup_premium 口径为正）"
        "严格区分。代理口径（收盘价 ≠ 盘中可成交价）使数字有偏，但方向性结论（负）与代理误差同量级，"
        "不足以翻正。",
    },
    "agent_plan": {        "key": "agent_plan",
        "name": "Agent 计划命中率（个股 · 持有 N 日 · 计划入场价基准）",
        "target": "终审通过（approved/demoted）且被采纳进模拟盘的 agent 交易计划",
        "window": "计划产出日后 N 个交易日收盘（默认 5）",
        "bucket": "二分类（按方向）：买入计划看涨 / 减仓计划看跌",
        "benchmark": "无（对照组是同期未采纳计划的同样结算，不是指数）",
        "rule": "计划入场价为基准，N 个交易日后收盘价上涨（买入类）即命中；"
        "计划未给出入场价的行不参与 pnl 统计；样本 < 5 条不计算命中率",
        "unit": "每条被结算的计划 = 1 个样本",
        "pitfall": "样本积累极慢（每条要等 N 个交易日才结算），前期命中率全是噪声；"
        "「未采纳对照组」的数字不能和采纳组直接相减得出因果结论 —— 采纳与否是用户选择，"
        "两组计划本身不同质；且 LLM 计划只在用户显式开启辩论时产出，样本存在选择偏差",
    },
    "dark_flow": {
        "key": "dark_flow",
        "name": "明暗背离形态（中小单代理 · 单日横截面）· G/S 计数与持续性 streak",
        "target": "全市场主力净额两端榜扫描（约 600 只）中出现明暗背离形态的个股",
        "window": "单日横截面（收盘口径）；streak = 自积累快照（v21）里连续交易日同一形态的天数",
        "bucket": "G（拆单吸筹嫌疑）/ S（拉高派发嫌疑）/ 无形态",
        "benchmark": "无（形态计数与连续天数不是收益率口径，没有可对比的收益基准）",
        "rule": "G = 明盘流出 + 中单流入 + 涨幅 −5%~3%；S = 明盘流入 + 中单流出 + 涨幅 ≥3%；"
        "噪声闸门 |中单净额/成交额| ≥ 2%。streak 按有快照的交易日序列数同一形态的连续出现，"
        "历史不足时降级单日并显式标注",
        "unit": "每票每日 = 1 个样本；持续性分布的样本 = 历史连续段（episode）个数",
        "pitfall": "⚠️ 中单是「散户 + 拆单主力」的混合体，不是真实暗盘；阈值启发式、未回测校准；"
        "恒定 unsupported —— 不是买卖建议。streak 只是形态重复出现的天数，"
        "**不能**读成「越连续越会涨」或换算成胜率/期望收益；"
        "「当日无形态」会断连续段，而缺采日（表未建/未跑 cron）会被跳过 —— "
        "两种断档含义不同，看 streak 时要连 sample_days 一起看",
    },
}

# 不可比声明：前端应原样展示，不要改写成本地的等价说法。
INCOMPARABLE_NOTE = (
    "这几种「胜率」的标的、持有期、分类数与是否对比基准都不同，数字之间**不可比较、不可相加**。"
    "同屏展示只为各自看趋势，任何一个数字都不能单独作为「策略有效」的结论 ——"
    "判断有效性必须看它自己的基准超额与样本量。"
)


def describe(key: str) -> dict:
    """取某口径的完整定义；未登记时返回带明显标记的占位，避免前端静默显示半个口径。"""
    item = CALIBERS.get(key)
    if item is None:
        return {
            "key": key,
            "name": "未登记口径",
            "target": "",
            "window": "",
            "bucket": "",
            "benchmark": "",
            "rule": "",
            "unit": "",
            "pitfall": "该指标的口径未在 calibers 中登记，请不要据此下结论。",
            "registered": False,
        }
    return {**item, "registered": True}


def all_keys() -> list[str]:
    return list(CALIBERS)


def note() -> str:
    return INCOMPARABLE_NOTE


# ─────────────────────────────────────────────────────────────────────────
# 四问守卫（2026-10-17）
# ─────────────────────────────────────────────────────────────────────────
# ## 为什么在 calibers 之上再加这一层
#
# `calibers` 登记的是**口径定义**（标的/持有期/分类数/基准/规则），
# 解决的是「这个数字是什么意思」。但它挡不住另一类错误：
# **同一个口径下，样本不同、分布不同、可成交性不同，数字照样不可比。**
#
# 真实踩过的三个例子：
#   ① 同参数回测三次得 +28.20% / +14.37% / +30.94% —— 差异全来自「这次跑成了几只」。
#      池子不完整时，任何收益数字都不能当结论。
#   ② 涨停次日溢价里收益大头在**买不进**的档（换手<5% 期望 +3.31%），
#      真正可成交档收窄到 +1%。只报期望会诱导去追买不到的一字板。
#   ③ 「月均 5%」历史达成率仅 17.6%、亏损窗口 39.2%、中位数只有 +4.1%。
#      均值被少数窗口撑起来，中位数才是真实分布。
#
# 这三件事的共同点：**不是口径错，是口径对了但样本/分布/可执行性没交代。**
# 所以四问是独立的第二道闸 —— 口径决定「能不能比」，四问决定「这个数字本身站不站得住」。
#
# ## 四问的判据（硬编码，阈值集中在这里）
#
# 问的是四件任何「率」都必须交代的事，顺序即从易到难：
#   1. 有 n 吗          —— 样本量决定这是统计还是噪声（沿用既有 30/100 两档）
#   2. 中位数还是均值    —— 均值可被少数极端样本撑起来，中位数是分布锚
#   3. 卖点能成交吗      —— 买不进的胜率不是胜率，是事后诸葛亮
#   4. 换基准符号翻转吗  —— 符号翻转说明收益来自贝塔而非选股能力
#
# ## 纪律
#   · 缺数据一律 `None` + `answered=False`，**永不折算成「通过」**（与前端「缺结构位显示 —」同源纪律）。
#   · 四问全过才 `verdict="credible"`；有任一项明确不过 → `"inflated"`；
#     只是答不上来 → `"unknown"`。三者互斥，前端据此上不同强度的提示色。
#   · 这个模块**不判定策略好坏**，只判定数字是否具备被解读的资格。

# 样本量两档（与 `_sample_status` 同源，30 判显著、100 判稳定）。
MIN_SAMPLE = 30
STRONG_SAMPLE = 100

# 中位数与均值之差超过这个百分点（绝对值），说明分布被极端样本拉偏。
# 1 个百分点是「一个正常持仓周期的波动量级」—— 超过它，均值就不可单独引用。
MEDIAN_MEAN_GAP_PCT = 1.0

# 相对倍数判据（2026-10-17 加，起因见下）。
#
# ## 为什么绝对差不够用
# 上线首日就撞了两次：
#   · `+38.5%` 单个极端样本把均值从 1.44 拉到 2.25 —— 相对抬升 56%，
#     但绝对差只有 0.8 < 1.0，判成「未明显偏斜」。
#   · 39 次 +1% + 1 次 +40% ⇒ 中位 1.0、均值 1.95 —— 绝对差 0.95 < 1.0，同样漏过。
# 两次都是「低均值场景」：绝对差被小的基线压住，恰恰是分布最该被质疑的那种情况。
#
# ## 为什么改成复合判据而不是调小阈值
# 单纯把 1.0 调到 0.9 只会把这两个案例变成「刚好通过」，下一个案例照样漏 ——
# 阈值问题的本质是**单一绝对刻度覆盖不了不同量级**。
# 复合判据（绝对差 OR 相对倍数）覆盖两类真实失真：
#   · 高收益口径被一个涨停板拉偏（绝对差大）
#   · 低收益口径被一个小样本极端值拉偏（相对倍数大）
# 取 OR 而非 AND：任一指标显示偏斜就该提示，守卫偏向多报（保守）而非漏报。
MEDIAN_MEAN_RELATIVE = 1.3

# 可成交比例下限：低于它，胜率里就有相当一部分是「当时买不进」的。
TRADABLE_MIN_RATIO = 0.5

# 四问的固定问法（前端按这个顺序渲染，不要改文案顺序而不同步前端）
QUESTION_LABELS = {
    "sample": "有 n 吗",
    "median": "中位数还是均值",
    "tradable": "卖点能成交吗",
    "benchmark_sign": "换基准符号翻转吗",
}

VERDICT_NOTE = {
    "credible": "四问全部有交代，这个数字具备被解读的资格（仍不代表策略有效，只代表数字本身可信）。",
    "inflated": "四问里有明确的失真项 —— 这个数字在被修正之前不能当作能力证据。",
    "unknown": "四问里有答不上来的项 —— 这个数字只能当观察，不足以支撑结论。",
}


def _median(values: list[float]) -> float | None:
    """中位数；空样本返回 None（不返回 0）。"""
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[mid], 2)
    return round((ordered[mid - 1] + ordered[mid]) / 2, 2)


def four_questions(
    *,
    n: int,
    median: float | None = None,
    mean: float | None = None,
    tradable_ratio: float | None = None,
    benchmark_sign_flips: bool | None = None,
    sign_flip_labels: tuple[str, str] | None = None,
) -> dict:
    """判定一个「率」是否具备被解读的资格。返回结构见下方注释。

    每个问项的返回值形如::

        {"key": "sample", "label": "有 n 吗", "answered": True,
         "passed": False, "value": "n=12", "detail": "样本不足 30，只能当噪声看"}

    `passed=None` 表示这一问**无法回答**（缺数据），与 `passed=False`（回答了但不通过）
    是三态区分 —— 把它混成 False 会让「没数据」看起来像「检查没过」。

    参数全部可缺省：调用方只需给出它真的算得出来的那些，其余留空即可。

    ## `sign_flip_labels`

    第四问的通用文案是「换基准后收益符号翻转 / 收益来自贝塔」——
    这对**有收益**的口径是对的，但对「预测指数方向」这类**没有收益**的口径
    就是错的（它压根不涉及收益，说「收益来自贝塔」会误导）。

    所以允许调用方覆盖这四个字符串：`(翻转时value, 翻转时detail)`。
    只改文案、不改判定 —— 与 `four_questions_with_notes` 同一个纪律。
    """
    items: list[dict] = []

    # 问一：有 n 吗
    items.append({
        "key": "sample",
        "label": QUESTION_LABELS["sample"],
        "answered": True,
        "passed": n >= MIN_SAMPLE,
        "value": f"n={n}",
        "detail": (
            f"样本 {n} 只，低于 {MIN_SAMPLE} 的显著门槛，只能当噪声观察"
            if n < MIN_SAMPLE
            else f"样本 {n} 只，达到 {MIN_SAMPLE} 的显著门槛"
            + ("（≥100 可视为稳定）" if n >= STRONG_SAMPLE else "")
        ),
    })

    # 问二：中位数还是均值（两值都没有 → 答不上来）
    if median is None and mean is None:
        items.append({
            "key": "median",
            "label": QUESTION_LABELS["median"],
            "answered": False,
            "passed": None,
            "value": None,
            "detail": "未提供中位数与均值，无法判断分布是否被极端样本拉偏",
        })
    else:
        if median is None or mean is None:
            items.append({
                "key": "median",
                "label": QUESTION_LABELS["median"],
                "answered": False,
                "passed": None,
                "value": f"中位 {median if median is not None else '—'} / 均值 {mean if mean is not None else '—'}",
                "detail": "中位数与均值只给出一边，无法判断分布形态",
            })
        else:
            gap = round(abs(median - mean), 2)
            # 相对倍数 = 均值 / 中位数（中位数是分布锚）。
            # ⚠️ 分母必须是**中位数**，不能用 max(|median|,|mean|) ——
            #    那样算出来的比值恒 ≤ 1，判据形同虚设（这是实现时踩过的坑）。
            # 中位数为 0（或贴着 0）时倍数没有意义，改判绝对差。
            if abs(median) > 0:
                ratio = round(abs(mean) / abs(median), 2)
                ratio_meaningful = True
            else:
                ratio = None
                ratio_meaningful = False
            skewed = gap > MEDIAN_MEAN_GAP_PCT or (
                ratio_meaningful and ratio > MEDIAN_MEAN_RELATIVE
            )
            # 第三条判据：中位数与均值符号相反（2026-10-20 加）。
            #
            # ## 为什么前两条盖不住这一类
            # 线上实测（`/api/market/winrate` 主口径 n=48）：中位 −0.43%、均值 +0.41%。
            #   · 绝对差 = 0.84 < 1.0        → 不报
            #   · 相对倍数 = 0.41 / 0.43 = 0.95 < 1.3 → 不报
            # 于是判出「分布未明显偏斜」。但这组合的含义是**过半交易跑输指数、
            # 正期望完全靠少数尾部样本** —— 是分布最该被质疑的形态，不是最健康的形态。
            #
            # ## 根因：比值判据在异号时天然失效
            # `|mean| / |median|` 把符号丢了。只要 |均值| ≤ |中位数| 就恒 ≤1，
            # 与两者是否同号无关。这和「分母写成 max(|median|,|mean|) ⇒ 比值恒 ≤1」
            # 是同一类错误：**算出来的仍是个数，但那数不再表达它本来要表达的事**。
            #
            # 中位数为 0 时乘积为 0，不触发（贴 0 的正常分布已在上面退回只看绝对差）。
            sign_mismatch = median * mean < 0
            skewed = skewed or sign_mismatch
            if skewed:
                why = []
                if gap > MEDIAN_MEAN_GAP_PCT:
                    why.append(f"相差 {gap} 个百分点")
                if ratio_meaningful and ratio > MEDIAN_MEAN_RELATIVE:
                    why.append(f"均值是中位数的 {ratio} 倍")
                if sign_mismatch:
                    why.append("中位数与均值符号相反")
                items.append({
                    "key": "median",
                    "label": QUESTION_LABELS["median"],
                    "answered": True,
                    "passed": False,
                    "value": f"中位 {median}% / 均值 {mean}%",
                    "detail": (
                        f"{'、'.join(why)}，均值被少数极端样本拉偏"
                        f"（{'中位数为正、均值为负' if median > 0 else '中位数为负、均值为正'}"
                        "）—— 过半样本的方向与均值相反，请引用中位数"
                        if sign_mismatch
                        else f"{'、'.join(why)}，均值被少数极端样本拉偏，请引用中位数"
                    ),
                })
            else:
                items.append({
                    "key": "median",
                    "label": QUESTION_LABELS["median"],
                    "answered": True,
                    "passed": True,
                    "value": f"中位 {median}% / 均值 {mean}%",
                    "detail": (
                        f"相差 {gap} 个百分点、均值/中位 {ratio} 倍，分布未明显偏斜"
                        if ratio_meaningful
                        else f"相差 {gap} 个百分点，中位数为 0 只看绝对差，分布未明显偏斜"
                    ),
                })

    # 问三：卖点能成交吗（None → 答不上来；<1 说明还有买不进的档）
    if tradable_ratio is None:
        items.append({
            "key": "tradable",
            "label": QUESTION_LABELS["tradable"],
            "answered": False,
            "passed": None,
            "value": None,
            "detail": "未提供可成交比例 —— 买不进的样本也会被算进胜率",
        })
    else:
        ratio_pct = round(tradable_ratio * 100, 1)
        enough = tradable_ratio >= TRADABLE_MIN_RATIO
        items.append({
            "key": "tradable",
            "label": QUESTION_LABELS["tradable"],
            "answered": True,
            "passed": enough,
            "value": f"可成交 {ratio_pct}%",
            "detail": (
                f"可成交比例 {ratio_pct}%，低于 {int(TRADABLE_MIN_RATIO * 100)}% —— "
                "胜率里含相当一部分「当时买不进」的样本"
                if not enough
                else f"可成交比例 {ratio_pct}%，多数样本买得进"
            ),
        })

    # 问四：换基准符号翻转吗（None → 答不上来）
    if benchmark_sign_flips is None:
        items.append({
            "key": "benchmark_sign",
            "label": QUESTION_LABELS["benchmark_sign"],
            "answered": False,
            "passed": None,
            "value": None,
            "detail": "未做基准符号翻转检验，无法区分「选股能力」与「大盘贝塔」",
        })
    else:
        _bad_value, _bad_detail = sign_flip_labels or (
            "符号翻转",
            "换基准后收益符号翻转 —— 收益来自贝塔而非本口径的选股能力",
        )
        items.append({
            "key": "benchmark_sign",
            "label": QUESTION_LABELS["benchmark_sign"],
            "answered": True,
            "passed": not benchmark_sign_flips,
            "value": _bad_value if benchmark_sign_flips else "对照未失守",
            "detail": (
                _bad_detail
                if benchmark_sign_flips
                else "与对照基线相比未失守（详见本口径的对照说明）"
            ),
        })

    answered = [i for i in items if i["answered"]]
    failed = [i for i in answered if i["passed"] is False]
    if failed:
        verdict = "inflated"
    elif len(answered) < len(items):
        verdict = "unknown"
    else:
        verdict = "credible"

    return {
        "verdict": verdict,
        "verdict_note": VERDICT_NOTE[verdict],
        "answered_count": len(answered),
        "total_questions": len(items),
        "failed_keys": [i["key"] for i in failed],
        "unanswered_keys": [i["key"] for i in items if not i["answered"]],
        "items": items,
    }


def four_questions_with_notes(
    notes: dict[str, str] | None = None, **kwargs
) -> dict:
    """在四问结果上追加口径专属的补充说明（不改变任何判定）。

    ## 为什么需要这一层

    通用文案讲的是「这一问为什么答不上来」（缺什么数据），但有些口径
    答不上来的**原因本身**就是要传达的核心信息。典型是 `limitup_relay`：
    它的可成交性答不上来，不是因为忘了测，而是因为**测不了且这正是它的头号陷阱**
    —— 连板股次日常以一字板开盘，晋级了也成交不了；没晋级却可能单日亏 10% 以上。
    也就是说：「晋级率高」与「能赚钱」之间隔着的那个东西，恰好就是这一问。

    判据纪律：`notes` 只允许**追加**文字，不得改变 `verdict` / `passed` ——
    否则「补充说明」就成了绕过守卫的后门（说几句好话就把 inflated 变成 credible）。
    """
    result = four_questions(**kwargs)
    if not notes:
        return result
    for item in result["items"]:
        extra = notes.get(item["key"])
        if extra:
            item["detail"] = f"{item['detail']}｜{extra}"
    return result


def median_of(values: list[float]) -> float | None:
    """对外暴露的中位数（空样本 → None），供各服务在组装四问时复用。"""
    return _median(values)
