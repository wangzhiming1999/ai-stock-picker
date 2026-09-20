# 迭代日志 Changelog

> 格式参考 [Keep a Changelog](https://keepachangelog.com/)，版本号遵循产品里程碑（V1 ~ V5.x）。
> 代码仓库版本见 `backend/app/main.py` 的 `version` 字段，**当前为 `0.2.0`，对应产品里程碑 V1–V5.20**。
>
> 说明：历史条目按 ROADMAP 的「已完成」章节整理；里程碑日期以 ROADMAP 末次更新（2026-09-02）为最新基准，早期里程碑未逐日记录，具体提交时间以 git 历史为准。

---

## [Unreleased]

### Added
- **涨停次日溢价读数：把「唯一没被否掉的方向」做成产品读数**（2026-09-20）
  > 背景：项目所有验证里只有打板方向收益为正（两口径互证 n=758 / n=4953），
  > 但它此前只是 `LimitUpBar` 里的一根温度计。本轮把它做成可读的分档读数 ——
  > 同时把「收益大头落在买不进的档」这个反直觉事实摆在明面上。
  - 新增 `limitup_service.premium_readout` / `premium_summary`：
    按涨停池自带字段（换手率 / 首封时间 / 炸板次数）分档给次日溢价历史读数
    （D 日涨停价买入 → D+1 集合竞价卖出，满足 T+1），**零额外行情请求**
  - **可成交档与不可成交档分开报**：换手 <5%（缩量一字/秒板）期望最高（+3.31%）
    但正是挂不上单的那批；换手 ≥5% 档期望收窄到 +0.40% ~ +1.62%，这才是可执行区间。
    合并成单一数字等于把「看得见吃不着」的收益算进用户预期
  - 风险标记：**首封 ≥14:00 是唯一负期望档（−0.48%，胜率 37.8%）**；炸板 ≥3 次降至 +0.68%
  - 登记 `calibers.limitup_premium`（含「可成交性是代理口径、不可升级 verified」的 pitfall）
    与 `tactic_evidence.STRATEGY_EVIDENCE['limitup_premium']` = `preliminary`
  - 前端 `LimitUpBar.PremiumSection`：分档行 + 占比条 + 可展开成分股 + 口径行；
    文案无动作词，负期望档走琥珀（红绿只表达方向）
  - `calibers` 测试新增基准白名单不变量：只有真正做过基准对照的口径才允许写基准
    （`limitup_premium` 用「同股票池的非涨停日」做组间对照，n=10694 期望 −0.06%，故有资格）
- **证据台账：一处回答「哪些结论能动手」**（2026-09-20）
  > 项目有 8 条 K 线形态 + 6 条结构化口径，可信度由 `tactic_evidence` 统一裁决，
  > 但要知道「到底什么能用」得跨 4 个页面拼信息。台账把它们聚合成一张表。
  - 新增 `services/evidence_ledger.py` + `GET /api/market/evidence-ledger`：
    每条口径的证据等级 / 样本出处（provenance）/ 是否可执行 + 各等级覆盖计数 +
    **观察期自积累进度**（涨停池累积表已攒够几个交易日）
  - 只读聚合，无回测、无行情请求；数字全部来自登记表与跑批快照，
    因此可与 README / ROADMAP 逐条对照 —— 台账的存在意义正是杜绝「文档说 A、代码说 B」
  - 前端 `EvidenceLedgerPanel`（挂「选机会 → 验证」屏顶部）：先给结论
    （当前 14 条口径 0 条达可执行档），再往下看各口径自己的数字，避免误读
  - `limitup_service.accumulated_stats()`：累积表观察期进度读数
    （`days` / `rows` / 起止日期；表未建或未配置时静默降级）

### Changed
- **盯盘链路瘦身：日 K 取数 900 → 400 根，周/月线移出常规轮询**（2026-09-20）
  > 2026-09-18 诊断结论：两次提交把每轮盯盘的取数放大到 4 次/只，冷缓存一轮 13.9s。
  > 本轮修掉其中「可证的两条」，把请求量与失败可见性一起收口。
  - `monitor._KLINE_DAYS` 900 → 400：900 根是「从日线重采样月线」旧口径的遗留
    （V5.20 改为按周期直接取数后已无用），而单只响应 60.5KB → 约 27KB。
    400 = 最长技巧需求（天量见天价 320 根）+ 缓冲，注释写明不要为多周期共振调回去
  - 新增 `data_service.peek_history()`：**只读 K 线缓存、不发请求**；
    `pattern_service.load_period_histories(cache_only=)` / `load_tactic_periods(cache_only=)`
    透传。盯盘常规轮询改走 `cache_only=not force` —— 周/月线只在用户点「立即刷新」时真拉，
    并把 `periods.loaded` / `cache_only` 随返回体下发（区分「未加载」与「未命中」）

### Fixed
- **行情源：个股批量分批 + 重试 + 失败不再伪装成空数据**（2026-09-20）
  > 根因链：`_fetch_qq_spot` 原本「一次请求 + 零重试 + 异常吞成 `{}`」，
  > 一次抖动就让整批行情变空列表，上层表现是 `HTTP 200 + count:0 + missed:[全部]`——
  > 把行情源故障伪装成「这些票没有数据」。
  - **分批**：`_QQ_SPOT_BATCH = 50` —— 单次 symbol 过多会被腾讯静默截断
    （不报错、只是返回行数变少）；**重试**：每批 2 次 + 线性退避；空响应同样重试
  - **失败语义**：全部批次失败抛 `RuntimeError`；部分失败返回成功部分并打日志
  - `get_spot_quote(codes, *, strict=False)`：默认保持既有降级行为（18 个调用方零影响），
    `strict=True` 时把故障抛给调用方 —— **盯盘改用 strict**，
    行情源整体故障时走 502 明确报错，而不是「今天没什么可操作的」
  - **限流器修正**：key 由 `request.client.host` 改为读 `x-forwarded-for` 首个地址
    （Vercel 代理后前者语义不保证）；轮询类只读端点
    （`/api/market/monitor`、`/api/market/spot-status`、`/api/alerts/unread`）
    改用 120/分钟 的独立配额 —— 实测通用 60/分钟 会被「20s 轮询 + 立即刷新连点」打到，
    而那是正常使用而非滥用
- **盯盘「部分失败」对用户可见**（2026-09-20）
  - 未出结果的票按原因分类下发：`missed_detail.quote_missing` / `history_missing` /
    `signal_missing`（三者含义不同：行情源问题 / K 线取数失败 / 客观历史不足），
    新增 `partial` + `notice`（后端生成一句话说明，含总数与各原因只数）
  - `MonitorPanel` 新增提示条：此前 `missed` 前端**完全不读**，
    「少 3 只」与「全部失败」都只表现为列表变短
  - 修掉 `refresh()` 开头无条件 `setErr("")` 的问题 —— 它会把上一轮失败提示
    在 20s 后的下一次轮询里立刻抹掉，用户只看到一闪而过的红字
  - 新增测试 `test_spot_resilience.py`（17 例：分批 / 重试 / 空响应重试 /
    部分失败保留 / strict 语义 / peek 不触网 / cache_only 不触网 / miss 分类 / 限流键）；
    `test_limitup_premium.py`（18 例：档位边界到秒 / 可成交性 / 三条纪律）；
    后端用例 455 → **490**

### Fixed
- **新浪市值单位修正（万元→元），修复 Sina 降级窗口四维榜池空**（2026-09-18）
  > 根因：新浪快照 `mktcap`/`nmc` 单位是「万元」，此前直接按「元」契约落
  > `market_spot_cache`，下游 `/1e8` 后 `market_cap_yi` 全体缩小 1e4 倍
  > （安徽凤凰 125418.24 万元 → 0.0012 亿），全部卡在 `60<=mc<=3000` 硬筛
  > → 候选池为空（502「候选池为空」）。该 bug 自 09-03 quad 上线即存在，
  > 只在东财被风控、降级新浪的窗口暴露。实测修复后 quad refresh 200，
  > pool=40 / Top10 正常产出。
  - `spot_service._num` 增加 `scale` 参数；`_frame_from_sina` 对 mktcap/nmc ×1e4，
    对齐东财 f20/f21 的「元」契约
  - quad_service 移除临时诊断 RuntimeError（root-cause 定位后撤掉），恢复干净池空文案
  - 测试：新增回归测试锁定换算链（万元→元→亿 + 800 亿样本过市值硬筛）；全量 455 例通过（双入口复验）

### Added
- **推荐/四维榜结算闭环补口**（2026-09-18）
  > 「四维牛股 / 每日推荐质量好差」此前在系统内部不可见：quad 快照写了 `quad_snapshots`
  > 但结算只读 `daily_recommendations`（quad 从未被结算）；空推荐日提前 return 不落库
  > （胜率三项恒 total=0）。本轮补上两条落库口 + 口径拆分。
  - **四维榜接入结算**：`quad_service._save_quad_to_recommendations()` 把 Top10 以
    `source='quad'` 落 `daily_recommendations`（reason=上榜摘要，幂等跳过同日已有 code），
    复用既有 `settle_daily_recommendations` 次日收盘结算 —— quad 从此有可验证的命中率
  - **空推荐日观察层落库**：`recommend_service.save_watchlist()` 以 `source='watch'` 落
    观察层（reason=拦截原因），空日/非空日都落；同日已有推荐行则跳过（防同票双行）
  - **口径拆分**：winrate `recommendation` 主口径只算 `llm/rule`，新增 `by_source`
    细分（quad / watch 各自单列）；`calibers.recommendation` 登记补充三者不可相加的声明
  - 测试：`test_recommend_closure.py` 9 例（quad 落库/幂等/跳过已荐/缺价/静默降级 +
    watch 落库/幂等/已荐跳过/降级）+ `test_calibers.py` 增 3 例（主口径排除 quad/watch /
    旧数据无 source 仍计入）；全量 453 例通过（双入口复验）- **四维榜全市场快照接入 _get_spot 三层回退**（2026-09-18）
  > `quad_service._full_spot()` 直连 `fetch_spot_frame`，是全项目唯一绕过
  > 「内存 5min → Supabase `market_spot_cache` 6h → 真拉+跨实例冷却」的全市场消费者
  > —— 行情源一抖就 502，而 Supabase 里明明有热快照。
  - `market._rows_from_spot_frame` 保留富字段（pe/pb/turnover/量比/市值/5分钟涨跌）
    随快照落库；旧 5 字段缓存行由 `quad_service._normalize_shared_row` 归一化 +
    既有腾讯批量补全兜底（每 60 只一请求）
  - `quad_service.get_full_spot()`：统一入口，走 `_get_spot`（与全站共享缓存与冷却）；
    冷却期快速失败（冷却文案直接透出，不再伪装成「候选池为空」）；`_full_spot` 保留
    给无法 await 的路径并标注勿用
  - `regime_service.fetch_breadth` 同源切换（市场宽度与四维榜共享快照；冷却失败返回
    None 不拖垮方向预测 —— 原有契约不变）
  - 测试：`test_quad_spot_fallback.py` 9 例（必须走 _get_spot / 冷却异常传播 /
    新旧两代缓存行归一化 / 腾讯补全产出候选 / 宽度同源与失败吞并 / 富字段落库）；
    全量 453 例通过
- **盘中监控外部调度（GitHub Actions）**（2026-09-18）
  - `.github/workflows/intraday-monitor.yml`：交易时段每 5 分钟触发 `POST /api/cron/monitor`
    （Vercel Hobby 只有 2 个 cron 名额，已被 daily/quad 占用；monitor 挂不上平台调度）
  - 覆盖预警评估落库 + 连板自动建仓窗口（北京 9:15~9:45 = UTC 1:15~1:45，窗口内多次触发
    由后端窗口判定兜底去重）；concurrency 不取消上一轮（预警落库不能丢）
  - 需在仓库 Secrets 配 `MONITOR_CRON_SECRET`（或 `MONITOR_ADMIN_TOKEN`），
    与 Vercel 环境变量同值；未配置时 workflow 跳过并警告，不会白跑
- **连板接力闭环：每日落库 + 模拟盘自动建仓 + 简报/盯盘接入**（2026-09-18）
  > 连板晋级率此前只有「封板延续率」口径（不是收益率），且东财涨停池只回溯 ~15 个交易日，
  > 样本窗口永远 3 周、不会随时间变长。本轮把三件事串起来：数据自积累 → 模拟盘跑真实可成交收益
  > → 简报/盯盘直接给结论。
  - **每日落库**：`supabase-schema-v10.sql` 新增 `limitup_daily_snapshot`（UNIQUE(trade_date, code) 幂等）；
    `limitup_service.save_daily_snapshot()` 挂进 `get_snapshot`（顺手写）与每日 cron（收盘兜底），
    `relay_backtest` 读路径优先用累积表补齐接口回溯窗口外的空池日期（返回体新增 `accumulated_days`）
    —— 表未建 / Supabase 未配置全部静默降级，实时链路零影响
  - **模拟盘自动建仓**：`sim_service.auto_relay_buy_for_user / auto_relay_buy_all`
    —— T 日 `play_advice=="hunt"` 且 relay tier1（三因子全达标）才执行；T+1 开盘价成交
    （竞价挂开盘价口径）；**一字板开盘（high==low 且开盘即涨停 ≥9.5%）记 missed 不假装成交**；
    预算 `RELAY_BUDGET_PCT=10%` 整手向下取整；同 (user, code, trade_date) 幂等判重。
    触发挂在 `POST /api/cron/monitor` 开盘窗口 9:15–9:45（9:25 后开盘价才确定，9:45 后追高失真）
  - **v10 顺带修复**：`sim_trades.source` CHECK 约束此前只有 manual/briefing/recommend ——
    v9 起 agent 采纳路径写 `source='agent'` 实际会被 DB 约束静默拒绝（潜在 bug），本次一并放宽为
    `('manual','briefing','recommend','agent','limitup_relay')`；`TradeRequest` 正则与前端 `simTrade` 类型同步
  - **简报接入**：`briefing_service._build_limitup_block` 注入 `limitup` 块 —— 早盘直接回答
    「今天环境能不能碰连板」（三档结论 + 资金面最强分组 + 免责句）；
    登录用户持仓 ∩ 当日连板股按 relay_score 升序给盯盘提示（封板质量最弱的排最前）；
    `DailyBriefing` 新增「连板梯队」区、`MonitorPanel` 新增「持仓连板对照」条
    —— 措辞全部透传后端结论（分层是强弱读数不是买卖指令），前端不发明新话术
  - 测试：`test_sim_relay_auto_buy.py` 7 例（hunt+tier1 双闸门 / 一字板 missed / 仓位换算 /
    幂等 / 未初始化 / 预算不足 / 单票失败不拖垮）+ `test_limitup_snapshot_store.py` 8 例
    （落库行映射 / 缺值兜底 / 累积回补 / 未配置降级）；全量 427 例通过
- **技术债清理：下线 ma20_slope 负超额技巧**（2026-09-18）
  - 两轮回测（2026-09-13 / 09-16）收益与胜率超额均为负（−0.26/−0.35pt、−5.4/−5.0pt），
    「黄金区间」口径跑不赢基准 —— 从 `TACTICS` 移除（扫描/回测/面板不再出现，9→8 条）；
    `RETIRED_TACTICS` 登记下线名单，detect 函数与证据记录保留（历史结论可追溯、日后重新校准可复用回测链路）
  - 守卫测试同步重定义：`EVIDENCE ⊇ TACTICS`（不要求相等）+ 下线 key 必须有 detector + 必须留证据
- **Agent 执行闭环 + 决策记忆（TradingAgents 第五层：track record）**（2026-09-18）
  > 背景：四层链路（分析师 → 多空辩论 → 交易员计划 → 风控终审）此前「跑完即散」，
  > 没有任何表记录「agent 说买 → 实际结果如何」——agent 自己的结论没有 n，违反证据纪律。
  > 本轮补上执行闭环（P0）与决策记忆（P1），agent 第一次拥有自己的战绩单。
  - 新增 `services/agent_decision_service.py` + `supabase-schema-v9.sql`（`agent_decisions` 表，幂等）：
    深度分析产出终审结论时自动落对照行（rejected 直接落、approved/demoted 落 ignored 待采纳）；
    **表未建时全链路静默降级**，不影响任何现有功能（与 market_spot_cache 同策略，迁移可选）
  - **一键采纳建仓**：`POST /api/sim/from-plan` —— 校验 status=ignored + verdict∈{approved,demoted} +
    action∈{buy,add}，按 `final_position_pct × total_capital ÷ entry` 换算整手数（不足 1 手明确报错），
    `sim_service.buy(source="agent")` 成交后回填 `sim_trade_id`；`sim_trades.source` CHECK 扩入 `agent`
    - 同票同日同用户幂等落库（`record_for_user_if_absent`）；采纳接口带用户归属二次校验
  - **到期自动结算**：每日 cron 合并执行 `sim_service.settle_agent_decisions()`（不新增 cron，
    Hobby 限制）—— data_date + 5 个交易日（`trade_calendar.shift_trading_days` 新增）后按收盘价
    结算 pnl/hit + 代码模板反思（不额外调 LLM）；停牌顺延；**未采纳计划同样结算**（对照组）
  - **P1 决策记忆**：`_assemble_context` 注入该票最近已结算决策（`memory_block` 只含事实与偏差，
    不含指令词，测试锁定）；无样本/表未建返回空串零影响
  - **口径纪律**：calibers 新增 `agent_plan`（命中率基准=计划入场价、窗口=N 交易日、
    **样本 <5 不计算命中率**、采纳组与对照组不同质不可相减归因）；stats 随数据下发 caliber；
    前端 SimPanel「Agent 决策记录」区只展示不下发的数字，绝不自己算
  - 前端：`TradePlanBlock` 终审通过且为建仓计划时显示「按此计划建仓模拟盘」一键（decisionId 缺失/
    旧缓存隐藏）；SimPanel 增 Agent 决策区（状态徽章 adopted=蓝 / rejected=中性，pnl 走 pnlTone，
    命中率不占红绿）；`simTrade` source 类型扩 `agent`
  - 测试：`test_agent_decision_service.py` 16 例（落库状态机、幂等、结算方向化口径、
    无入场价降级、反思无指令词、记忆块、<5 样本不给命中率、口径必下发）；全量 417 例通过（双入口复验）
- **跌停池观察层：跌停次日修复收益实测 —— 结论为负，因此只读不推**（2026-09-18）
  > 起因是一个很常见的想法：「每天挑跌停的票低吸，次日竞价修复就卖出」。
  > 本项目第一次用**真实收益口径**把它跑了出来 —— 结果是负期望，于是这个功能的产品形态
  > 从「抄底候选列表」改成了「抛压温度 + 代价读数」。
  - 数据源新增东财跌停板池 `getTopicDTPool`（与涨停池同域不同端点，风控特征一致）；
    ⚠️ 该端点的 `sort` **必须用 `zdp:asc`** —— 照抄涨停池的 `fbt:asc` 会返回**空池**（实测踩过）
  - 新增 `services/limitdown_service.py`：跌停池 / 连跌梯队 / 板块聚集（60s 短缓存）+
    **次日修复收益回测**（D 日跌停价买入 → D+1 集合竞价 / 收盘 / 盘中最高三种卖出口径）
  - 新增 `GET /api/limitdown/snapshot`、`GET /api/limitdown/repair?days=N`
    （口径 `limitdown_repair`，新登记进 `calibers`，被 `test_calibers` 的覆盖守卫锁定）
  - **实测结论（2026-08-31 ~ 09-17，13 个交易日 / 133 个样本）**：期望 **−4.47%/次**、
    竞价卖出胜率 **4.5%**、打平需 **80.6%** 胜率（均盈 +1.14% / 均亏 −4.74%）
  - **三个反直觉发现**：
    ① 「跌停能买到」不是优势而是弱势信号 —— 全天封死组（随时买得到）期望 −6.23%、次日仍跌停 26.7%，
       盘中开过板组 −4.25% / 16.1%，即**越好买次日越差**；
    ② 按「跌停的板块」筛反而最差 —— 同板块 ≥5 只跌停 −7.17% / 2-4 只 −5.19% / 仅 1 只 −4.04%，
       说明板块级同时跌停是**板块利空**而非个股错杀；
    ③ 竞价卖出是全天最差时点 —— 次日盘中最高价平均 +0.57%、50.4% 曾转正（反抽真实存在），
       但覆盖不了平均低开；持有到收盘 −3.94% 仍为负。按当日跌停家数 / 板块家数 / 连跌天数
       逐一切片，**n≥8 的切片无一为正期望**
  - 尾部风险：14.3% 的样本次日跌停开盘，其中 3 次一字跌停**挂单也卖不出去** ——
    T+1 之下这条路径在最需要止损的时刻没有止损能力
  - 证据等级登记为 **`unsupported`**（不是「还没跑」，而是「有明确结论且为负」），
    `actionable` 恒为 false；`calibers.limitdown_repair.pitfall` 写明「这是负期望口径，不是机会口径」
  - 前端 `LimitDownBar`：与 `LimitUpBar` 对称的全局常驻温度带（**同样不进 NAV**）——
    折叠态只报跌停家数 / 连跌家数 / 最集中板块 / 跌停涨停比；展开态把
    「期望 −4.47% + 离打平还差 76.1 个百分点」摆在最显眼处，位置标签只占中性 / 琥珀，
    全程无动作词；`limitDownLogic.ts` 抽出纯逻辑（胜率缺口 / 涨跌停比 null 语义 / 带样本量门槛的极值切片）
  - 后端测试 355 → 399（+44：字段错位（`fba` 非 `fund`、`days` 非 `lbc`）/ 单位换算 /
    收益统计打平线 / `ret_close=None` 不得当 0 / 负期望策略不得 actionable）；前端测试 9 → 19（+10）
- **深度分析：TradingAgents ③④层 —— 交易员计划 + 风控终审**（2026-09-18）
  > 把昨天上线的多空辩论接完下游：辩论结论第一次变成「可被风控检验的交易计划」，
  > 补齐 TradingAgents 四层链路（分析师 ✓ / 辩论 ✓ / 交易员 ✓ / 风控 ✓）。
  - `models`：新增 `TradePlan`（动作/入场/止损/目标/仓位/分批/依据/失效条件）与
    `FundManagerVerdict`（approved / demoted / rejected + 逐条裁决理由 + 终审仓位/止损）
  - `debate_service.draft_trade_plan`：交易员起草计划（辩论双方论据 + 系统技术位为输入，
    prompt 明示「止损不得松于技术止损位」）；LLM 失败 / 辩论缺席一律返回 None 降级
  - `debate_service.review_plan`：**风控终审全部代码判定，不走 LLM** ——
    止损 ≥ 入场 → rejected；仓位超风险等级上限 / 止损松于技术位 / 风报比 < 1.5 / 分歧度 ≥ 60 →
    demoted（压回仓位或收紧止损）；辩论方向 neutral/bear 却提交看多计划 → rejected；
    减仓/回避等防御方向不吃看多约束
  - 仓位铁律与 `portfolio_service._select_stop_price` 同源：止损只能收紧不能放大；
    风险等级上限内联同一张表（保守 15 / 稳健 20 / 进取 25 / 激进 35）
  - `analysis.py`：SSE 新增 `trade_plan_start` / `trade_plan_done` 事件；
    主链路与缓存补跑路径都产出 ③④ 层；结果挂 `StockAnalysis.trade_plan` / `fund_manager_verdict`
  - 前端 `TradePlanBlock`：动作徽章（走 `actionBadge` 方向语义）+ 终审徽标
    （通过=蓝 / 降级=琥珀 / 否决=中性灰，质量判定不占红绿）+ 关键价位格 + 分批方案 +
    逐条裁决理由；否决时仍展示计划与理由（「为什么被否」比藏起来更有用）；
    旧缓存缺字段时整块隐藏
  - 后端测试 335 → 350（+15：parse 收敛语义 / 终审三档 / 降级路径 / 技术位注入 prompt）

### 连板追踪：全局情绪常驻条 + 涨停池晋级率回测（2026-09-17）
  > 目标：回答「追连板能不能吃到鱼腹的利润」。新增独立行情源东财涨停板池
  > `push2ex.eastmoney.com`（与被风控的 `push2` 完全独立域名，单请求拿全市场涨停池 +
  > 连板数 + 板块 + 封单，风控压力比 60 页分页快照低两个数量级），支持 `date=` 回溯。
  - 新增 `services/limitup_service.py`：涨停池 / 炸板池抓取（60s 短缓存）→ 三层聚合：
    连板梯队（>5/4/3/2/首板，看断层）、板块热度（按行业分组，看主线）、
    情绪温度（涨停数 / 炸板率，看能不能打板）；个股输出「鱼腹候选 / 鱼尾警示」位置标注（**不是买点**）
  - 新增 `GET /api/limitup/snapshot`（情绪条快照 + 梯队 + 板块 + 位置标注）、
    `GET /api/limitup/relay?days=N`（N 连板 → 次日晋级率回测，口径 `limitup_relay`）
  - **晋级率回测关键发现**（2026-08-28 ~ 09-16，13 个交易日对 / 764 样本）：
    首板→2板 16.3%（n=601）、2板→3板 33.3%（n=99）、3板→4板 40.0%（n=35）——
    连板之后继续连板的概率约为首板的两倍；但**反向线索**：同板块涨停家数越多，
    首板晋级率越低（≥5 家 9.2% vs 1-2 家 18.8%），「追最热板块」未获支持
  - ⚠️ 涨停池**只回溯约 15 个交易日**，超窗口日期返回空池；晋级率是「封板延续率」
    不是收益率（连板股常一字板开盘，晋级了也未必买得到），证据等级 `preliminary`，
    **不进 `ACTIONABLE_TIERS`**
  - `tactic_evidence` 拆出 `STRATEGY_EVIDENCE` 独立命名空间（策略 ≠ K 线形态，
    保持 `EVIDENCE` 与 `pattern_service.TACTICS` 一一对应的守卫不变量）；后端测试 256 → 300
  - 前端新增 `components/LimitUpBar.tsx` 全局常驻条（涨停家数 / 炸板率 / 最高板 / 主线板块，
    点击展开梯队与板块详情 + 回测表），挂载在 App header 下方；纯逻辑抽 `limitUpLogic.ts`（梯队断层检测）带 node:test
- **深度分析：多空研究员对辩（借鉴 TradingAgents 的对抗机制）**（2026-09-17）
  > 目标：给深度分析补上「同一份资料被反向解读时是否站得住」这一层信息。
  > 机制抄自 TauricResearch/TradingAgents（arXiv 2412.20138）的研究员团队层 —— 对照其
  > 「分析师 → 多空辩论 → 交易员 → 风控」四层链路，本项目已有其中三层
  > （signal/trend_template/pattern = 分析师、llm_service = 交易员、tactic_evidence = 风控），
  > 缺的就是辩论。**是移植机制，不是引依赖**：直接 pip install 上游框架会撞三处硬约束 ——
  > langgraph 生态撑大 Serverless 部署体积、其 A 股数据源走东财直连（IP 封禁头号风险源）、
  > 一次 5~10 次串行 LLM 调用顶到 Vercel maxDuration 300s 墙角。
  - 新增 `services/debate_service.py`（0 个新运行时依赖，复用 openai SDK）：
    多头 / 空头研究员各立论 → 第二轮互看对方观点逐条反驳，固定 2 轮 = 4 次调用，并行发起
    - **分歧度口径 = min(多头信心, 空头信心)**：两边同时笃定才是真争议；
      刻意不用 |bull-bear|（会把「多头碾压」和「空头碾压」混成同一个数字）
    - `key_disagreement`（核心分歧点）由第二轮空方输出，兜底链：轮次输出 → 空头第一条反驳 → 空头论点
    - **降级不抛异常**：无 Key / LLM 失败 / JSON 解析失败一律返回 None，不影响主分析；
      第二轮失败沿用第一轮（rounds=1）
    - `summarize()` 只向主分析递「分歧」，刻意不递「倾向」—— direction 无统计支撑，
      若被主分析照单全收，等于让未回测的结论间接进了总分
  - **证据闸门纪律**：辩论结论证据等级固定取 `tactic_evidence` 的 `unknown` 档
    （label/badge/actionable 全部由唯一来源推导，不手写文案），`executable` 恒为 False ——
    展示层不得把它放进买点位置，只能作分歧与风险提示
  - 接线：`AnalysisRequest.debate` 开关（默认关，每只票多 2 轮 LLM 调用）；
    SSE 新增 `debate_start` / `debate_done` 事件；`llm_service` 抽出共用 `get_client()` +
    非流式 `complete()`；深度分析 context 组装抽为 `_assemble_context()`（主链路与缓存补跑共用）；
    开辩论但命中旧缓存时就地补跑并回写，避免开关「看起来不生效」
  - 前端：`DebateBlock`（分歧度走 `divergenceTone` 质量色，多/空立场标签走 upTone/downTone，
    gate_note 原样展示）；AnalysisDrawer 加开关（ref 持有，避免开关变化重跑分析）
  - 测试：`test_debate_service.py` 16 例（闸门不可执行、min 分歧口径、四类降级路径、
    summarize 不外泄倾向、第二轮 prompt 必含对方论点）；全量 318 例通过
- **V5.20 · 产品可信度：多周期共振修复 + 形态证据闸门 + 胜率口径登记**（2026-09-16）
  > 目标：解决用户反馈的「数据不准确」。这一轮修的不是算错的数字，而是**可信度没有被区分**：
  > 一条数学上永远不可能命中的形态、一批没有统计支持的买卖点、四个都叫「胜率」却互相不可比的数字。
  - **多周期共振此前在任何股票、任何时点都不可能命中**（口径级 bug，非行情原因）：
    腾讯历史 K 线端点日线硬上限 **640 根**，从 640 根日线重采样最多得到 ~33 根月线，
    而 MACD(12,26,9) 需要 slow+signal = **35 根**才成形 → `detect_cycle_resonance` 恒返回
    `insufficient_data`，既不命中也不报错。实测同一端点在**相同主机**上支持 `week`（300 根）/ `month`
    （120 根，回溯至 2016-10）：改为按周期直接取数即可，不是新增数据源
    - `data_service.get_history(code, days, period="day"|"week"|"month")`；周线 6h / 月线 24h 长缓存
    - `pattern_service.needed_periods()` / `load_tactic_periods()`：**只有声明了 `extra_periods`
      的技巧才产生额外请求**（当前仅多周期共振），其余技巧零额外流量；全部走 `gather_limited` 闸门
    - 5 个调用面统一取周期数据：`check_codes`（扫描）、`analysis.py`（深度分析）、`briefing_service`（简报）、
      `portfolio_service`（持仓）、`routes/monitor`（盯盘）—— 保证同一只票在各页面结论一致
    - `history_days` 900 → 120、`warmup` 750 → 60：原值只服务于「重采样出月线」的旧口径，
      且 750 的预热期让该技巧在回测里被**静默跳过**（`stocks_evaluated = 0`）
    - 实测（600519 / 000001）：三周期各得真实 K 线 120/300/120 根，平安银行月线金叉被正确识别
  - **形态证据闸门**：新增 `services/tactic_evidence.py`，把回测结论变成展示层必须遵守的闸门
    - 5 档分级：`verified`（n ≥ 30 且 \\|z\\| ≥ 1.96 且各持有期收益超额为正）/ `preliminary` /
      `unsupported` / `unknown` / `not_testable`；**只有 `verified` 允许进入买卖点位置**，当前**一条都没有**
    - `_pack()` 统一挂 `evidence` / `executable` / `gate_note`，因此扫描 / 深度分析 / 盯盘 / 持仓 / 简报
      拿到的可信度标签必然一致；`executable = 命中 && 证据达标`
    - `ESCALATE_SELL_KEYS` 改为由登记表**推导**（原来手写的空集合，存在「表里写了已验证、代码里仍是空集」的静默不一致风险）
    - 新增 `GET /api/market/tactic-evidence`：分级口径 + 覆盖计数 + 证据快照（跑批日期 / 股票池 / 持有期）
    - 前端收口为共享组件 `components/TacticHit.tsx`：未验证的命中**不使用方向色**（红绿只表达方向，
      用它渲染未验证形态会被读成「该动手了」），改中性「观察」角标 + 观察池说明；
      修复 `TacticPanel` 条件清单里 ✓/✗ 占用红绿的问题（通过项属质量语义）
  - **回测口径修复 + 复跑**（`tactic_backtest_service`）：
    - 新增 `_PREFIX_LOOKBACK = 390`：评估窗口之外必须留足「相对量」所需的历史
      （天量要区间最大量、地量要 60 日高点）。原实现由 `warmup` 隐式决定，
      改 `warmup` 会连带改变其他技巧的回测结果
    - 新增 `_PeriodCursor`：周线/月线按评估日**切片回放**，并把进行中那根的收盘替换为当日收盘
      （接口返回的是该周期最终收盘，直接用等于偷看未来）
    - 历史长度覆盖不了预热期时改为**明说**「未纳入评估」，不再混进「0 次命中」
    - **复跑结论（42 只池 · 每只 640 根日线 · 240 个评估日 · 持有 5/10/20 日，`failed = 0`）**：
      没有任何形态达到统计显著。多周期共振首次有信号（n=5，胜率超额 +35.7/+37.1/+39.1pt，z≈2.0），
      但样本远不足；**揉搓线洗盘的「唯一稳定正超额」未能复现**（当年 +4.7/+6.0/+9.5pt → 本次 +3.4/+2.3/+0.8pt，
      z=0.56/0.30/0.10），当年的正值落在噪音范围内
  - **胜率口径登记**：新增 `services/calibers.py`，把「胜率」这个词在本系统内的定义写死
    - 「验证」页同屏有 **4 个都叫「胜率 / 命中率」**的数字：大盘单日命中（三分类、含 ±0.5% 中性带）、
      推荐 T+1（二分类、无基准）、策略回测（调仓期、对比沪深300）、形态回测（N 日前向、对比同区间基准）。
      标的 / 持有期 / 分类数 / 有无基准全不同，**不可比较、不可相加**
    - 每个统计块随接口下发自己的 `caliber`（标的 / 窗口 / 分类数 / 基准 / 判定规则 / 样本单位 / 易骗点）；
      `caliber_note` 给出不可比声明
    - 前端新增共享组件 `components/CaliberNote.tsx`；不可比声明统一在 `VerifyPanel` 顶部只写一次，
      各面板展示自己的口径；策略回测的「胜率」标签改为「期胜率」（样本单位是调仓期而不是个股）
  - 新增测试：`tests/test_tactic_periods.py`（12 例，含「周/月线切片不偷看未来」「小样本不再静默跳过」）、
    `tests/test_tactic_evidence.py`（18 例，含「闸门双向可用：verified 要能解锁动作」）、
    `tests/test_calibers.py`（17 例，含「真正使用该胜率的接口都带口径」）。后端用例 **202 → 256**
  - 文档：README schema 版本与测试章节已同步
- **V5.19 · 行情源护栏：并发闸门 + 跨实例冷却 + 强制刷新闸门 + 可运行的测试/CI**（2026-09-16）
  - **并发闸门**：新增 `services/concurrency.py`，所有「按 code 逐只打行情源」的批量拉取统一走
    `gather_limited` / `limited()`，进程级上限 `FETCH_CONCURRENCY = 8`。此前 6 处调用**并发无上限**
    （策略扫描 30 只候选 → 30 个并发请求直打行情源），是 IP 级风控的主要触发条件。
    收口点：`routes/market._apply_strategy`、`pattern_service`（日线 / 分钟线）、`recommend_service`、
    `portfolio_service`、`winrate_service`、`routes/monitor`（原各自 `Semaphore(12)` / `(8)`，已统一配额）、
    `quad_service`（原 `Semaphore(12)`）、`tactic_backtest_service`（原 `_FETCH_CONCURRENCY`）
  - **跨实例冷却**：行情源失败标记从进程内变量改为落 `market_source_state` 表（新增 `supabase-schema-v8.sql`），
    冷却窗口对全部 Serverless 实例生效。原实现下「A 实例已被风控、B 实例仍去撞行情源」，
    每个请求空等数十秒才 502 并持续刷新封禁窗口。**表未建时静默降级为纯进程内冷却**，不影响上线
  - **新增接口 `GET /api/market/spot-status`**：返回剩余冷却秒数 / 快照年龄与规模 / 冷却窗口参数，
    供前端在强制刷新前判断能否安全触发
  - **前端强制刷新闸门**（新增 `lib/spotGuard.ts`）：二次确认 + 冷却倒计时。
    `confirmForceRefresh()` 给「强制刷新」类按钮（冷却拦截 + 代价说明确认 + 确认后本地 60s 节流）；
    `ensureNotCooling()` 给盯盘「立即刷新」这类高频核心动作（只拦冷却，不弹确认，不打断盘中节奏）
  - **修掉 3 处硬编码 `force: true`**：`ScanPanel` 策略选股 / 全市场扫描、`TacticPanel` 形态扫描
    此前**每次点击都跳过两层缓存直打行情源** —— 这是 2026-09-15 那次全站 502 的前端侧根因。
    现在默认走缓存（内存 5min → Supabase 6h），需要最新数据用面板上的「强制刷新」（过闸门）
  - **前端错误详情统一**：新增 `errorFrom(res, fallback)`，26 处「只抛状态码」的接口改为读取后端 `detail`。
    此前用户只看到 `502`，看不到「行情源被风控，冷却中（63s 后重试）」，
    会把临时冷却误判成服务故障而反复重试 —— 恰好是延长封禁的动作
  - **后端测试可运行**：新增 `backend/pytest.ini` 与 `backend/requirements-dev.txt`（pytest / pytest-asyncio）。
    此前 19 个测试文件既无依赖声明也无 pytest 配置，换台机器无法复现，「测试」等于不存在；
    测试依赖刻意与 `requirements.txt` 分开，避免撑大 Vercel Serverless 安装体积
  - **前端单测跑起来了**：`scanPanelLogic.test.ts` 此前因 package.json 没有 `test` script 而永远跑不起来。
    实测 Node 内置 `node --test`（Node ≥ 22.18 内置类型擦除，可直接跑 `.ts`）即可，**无需引入 vitest**
  - **新增 `npm run typecheck`**：固定走 `tsconfig.app.json` + `tsconfig.node.json`，
    避免再踩「根 tsconfig 是 references 模式、tsc 空跑永远 exit 0」的坑
  - **新增 CI**（`.github/workflows/ci.yml`）：后端 `pytest` + 前端 `typecheck` / `test` / `build`
  - 新增测试：`tests/test_concurrency.py`（6 例，含「配额跨并发批次共享」「策略扫描峰值并发受限」两条回归）
    与 `tests/test_market_spot_cache.py` 新增 6 例冷却共享 / 降级用例。后端用例 **190 → 202**
- **V5.18 形态校准 + 新增 3 条技巧 + 建议闸门**（2026-09-13）
  - **回测闸门**：新增 `pattern_service.ESCALATE_SELL_KEYS`，只有回测达到显著（`confidence == "significant"`）的卖出形态才允许把「持有观察」升级为「建议减仓」。首次回测无形态达标，闸门为空 —— 断头铡刀不再自动触发减仓建议
  - **文案降级**：断头铡刀 / 天量见天价的命中提示从「无条件减仓 70% / 清仓离场」改为风险提示口径（回测未显示显著超额）
  - **地量阈值校准**：原文 20% 在 42 只大中盘、16380 个时点上 **0 次命中**（地量条件仅成立 7 次）；扫描 0.2/0.3/0.4/0.5 后调整为 **30%**（9 次命中、胜率超额 +18pt，样本不足待样本外验证；0.4/0.5 信号变多但超额迅速衰减）
  - **新增 3 条技巧**（来自用户补充的风控 / 均线规则）：
    - MACD 零轴金叉：零轴上方金叉为强势买点，零轴下方金叉需放量 30% 才轻仓试错
    - MA10 三日失守：跌破 10 日均线后连续 3 日无力收回
    - 均线斜率主升：原文「15°–35°」角度**不是尺度不变量**（依赖图表纵横比），改用 MA20 的 20 日变化率 5%~20% 分档，阈值为初值待校准
  - 三条新技巧首轮回测**均无显著超额**：零轴金叉与基准无差异（z=0.02）、MA10 三日失守 +2.4pt（z=1.18）、均线斜率黄金区间为**负超额（−3.6pt）** → 仅作候选池展示，不驱动任何仓位动作
  - 组合建议新增「仓位分层参考：5 成蓝筹底仓 + 3 成主线成长 + 2 成现金后手」
- **V5.17 形态回测验证 + 简报接入**（2026-09-13）
  - 新服务 `tactic_backtest_service`：对 6 条技巧做 **walk-forward 回测**（只用「截至当日」的 K 线判定，命中后按当日收盘价入场），统计其后 N 个交易日的前向表现
  - 统计口径（避免「胜率 70%」式自欺欺人）：胜率**按方向定义**（买入形态看涨、卖出形态看跌）· **必须与同区间同持有期基准对比**（牛市里任何买入信号胜率都高）· 命中后 horizon 个交易日内**去重**（同一波行情只计一次）· 命中样本 < 8 次不给结论（`insufficient_data`）
  - 不可回测 / 数据缺失项**明说**：分时背离需分钟级历史（数据源只提供日线）→ `not_backtestable`；天量见天价的「换手率 >30%」无历史换手率 → 按数据缺失处理
  - 接口 `POST /api/backtest/tactic`（`tactic` / `codes` / `horizon_days` / `eval_bars`）
  - 前端「选股扫描 → 看实战形态」新增**回测验证面板**：命中/样本、胜率 vs 基准、胜率与收益超额、期间最大浮盈浮亏、按个股明细
  - 简报接入：`build_today` 新增 `tactics` 块（持仓形态信号优先、关注池买点其次），首屏直接可见形态命中
  - 持仓 / 关注池统一补形态：`portfolio_service`、`briefing_service` 的日线取数提到 900 根；卖出形态（断头铡刀等）自动把「持有观察」升级为「建议减仓」并写入持仓 tips
  - **回测实测结论**（42 只行业分散大中盘、每只 400 根、持有 5/10/20 日，2026-09-13）：
    - 揉搓线洗盘是**唯一有稳定正超额**的技巧：胜率超额 +4.7 / +6.0 / +9.5pt（随持有期递增），命中分散在多只票上；但 z=1.05 未达显著，方向可信、幅度未证实
    - 断头铡刀的**收益超额为负**：命中后平均反而上涨 +2.18%（基准 +0.22%），作为「无条件减仓 70%」的纪律在该股票池上跑不赢什么都不做
    - 地量见地价按原文「缩量至前期均量 20%」直译后 **0 次命中**（16380 个时点中地量条件仅成立 7 次）——大市值股票几乎不可能缩到 20%，需校准阈值或承认只适用于小盘股
    - 多周期共振受**数据源硬限制**：腾讯日 K 上限约 640 根，月线 MACD 需约 735 根，绝大多数股票无法计算（仅个别次新股能出信号）
  - 统计升级：样本分层（<10 不给结论 / <30 不判显著 / ≥30 且 \|z\|≥1.96 判显著）+ 比例之差 z 检验；股票池扩到 42 只；回测结果按「数据日 + 参数」落库复用
- **V5.16 实战形态规则引擎**（2026-09-13）
  - 新服务 `pattern_service`：把 6 条实战技巧沉淀为**可复核的确定性条件检查**（逐条 `conditions` + `passed/total` + `action`），不做黑箱打分、不承诺胜率
  - 技巧清单：
    - 周期共振：多周期共振买入（日/周/月 MACD 金叉；周/月线由日线收盘重采样得出）、分时背离逃顶（日内价格创新高但 MACD 未同步创新高）
    - K 线组合：揉搓线洗盘（长上影＋长下影、实体接近，3 日内突破上影高点为加仓点）、断头铡刀（MA5/10/20 粘合后大阴线跌破三线且跌幅 >5%）
    - 量价关系：地量见地价（长期下跌后缩量 ≤ 前期均量 20%，3 日内放量 2 倍确认）、天量见天价（短期涨幅 ≥50% 后放历史天量、换手 >30%）
  - 数据层：`data_service.get_history` 补全日线 OHLC（腾讯 `qfqday` 本就返回开高低，此前解析时被丢弃），并夹逼保证 `high ≥ max(open, close) ≥ min(open, close) ≥ low`
  - 接口：`GET /api/market/tactics`（技巧清单）、`POST /api/market/tactic-scan`（按技巧扫描全市场或指定股票池，候选上限按所需日线长度自适应）、`GET /api/market/tactic-check?code=`（单票逐条体检）
  - 前端：选股扫描新增「看实战形态」视图（`TacticPanel`），按分类与买卖方向分组，展示命中技巧 + 操作提示，可展开逐条核对条件
  - 接入：同一引擎复用到**深度分析卡**（`StockAnalysis.tactics` → 形态命中块，并注入 LLM 上下文）与**盯盘监控**（每只票的形态标签 + 决策条「形态命中 N」）；两处都只回传命中的技巧
  - 取数：深度分析日线由 260 根提到 900 根（月线 MACD 所需），但技术信号 / 趋势模板 / LLM 上下文一律改用最近 260 根切片，既有输出不变；盯盘日 K 由 120 根提到 900 根（30 分钟缓存，请求次数不变）
  - 约束：仅「全部条件成立」才返回命中，数据缺失记 `insufficient_data` 且不计为通过；所有文案标注「算法推导，不构成投资建议」
- **V5.15 盯盘监控 · 多周期（5/15/30/60 分钟）日内决策**（2026-09-09）
  - 数据源：新增腾讯分钟 K 线（`ifzq.gtimg.cn/.../mkline`，含 OHLC），支持 1m/5m/15m/30m/60m，盘中 60s / 休市 600s 差异化缓存
  - 新服务 `intraday_service`：当日 VWAP（成交量加权均价）、日内高低点、分钟均线（5/20）、分钟布林带、分钟量比 → 日内买卖指令
  - 日内指令：破日内低 / 放量破日内高 / 破日内高待确认 / 回踩分钟均线（买）/ 冲高上轨减仓 / 反抽 VWAP 走 / 日内空头压制 / 日内胶着观望
  - 日内止损压在 1.5% 以内（周期越短越紧：5m 0.3%~0.8%，15m 0.5%~1.1%），与日线 3% 级别止损区分
  - `/api/market/monitor` 新增 `interval` 参数（1d/5m/15m/30m/60m）；任何周期都返回 `daily` 日线战略锚点，避免日内与波段反着做；分钟数据不可用时自动降级为日线并置 `degraded`
  - 前端：日线 / 15 分 / 5 分 周期切换（记忆选择）、日内列显示 VWAP 与日内高低、分钟模式展示日线锚点与当日有效提示
- **V5.14 盯盘监控 · 买卖决策化**（2026-09-09）
  - 后端 `/api/market/monitor` 每条指令附「可执行挂单计划」：`plan.buy` / `plan.sell` / `plan.stop` / `plan.target` / `plan.position_pct` / `plan.urgency`，外加一句话指令 `advice.do`
  - 结果按「止损 → 卖出 → 买入 → 观望」排序，需要操作的排最前
  - 新增顶层 `summary`：待操作只数 + 止损/卖出/买入计数 + 最紧急清单（前端「现在要不要动」决策条）
  - 请求新增 `costs: {code: cost}`：传入持仓成本后指令带浮盈浮亏，硬止损取「技术止损 与 成本 -7%」更紧者；浮盈 ≥12% 提示止盈、浮亏 ≤-7% 提示逼近止损
  - 预警规则新增 `buy_point`（回踩到买点，≤触发）/ `sell_point`（冲高到卖点，≥触发）
  - 前端盯盘面板：今日决策条 + 「只看要操作的」过滤 + 挂单计划列（买/卖/止损价位）+ 一键设到价提醒 + 一键导入自选股/持仓（持仓带成本）

### Changed
- **深度分析抽屉改为非模态：分析期间主界面可继续操作**（2026-09-18）
  > 一次分析要跑几十秒到几分钟（多只票 + 可选多空辩论）。旧实现是全屏遮罩
  > （`fixed inset-0` + `bg-slate-950/70 backdrop-blur`）加 `body overflow: hidden`，
  > 等待期间主界面既点不动也滚不动 —— 与「日内操作指令台」的定位直接冲突：
  > 用户要的是一边等结果一边继续看行情，不是被锁在抽屉里干等。
  - 去掉遮罩与背景滚动锁，外层 `pointer-events-none` / 面板 `pointer-events-auto`：主界面照常可点可滚
  - 面板新增**收起**（`PanelRightClose` / Esc）：收成右下角常驻胶囊，**分析继续在后台跑**，
    胶囊实时显示「已完成 2/3 只」与当前状态，点开还原；`role` 从 `dialog/aria-modal` 降级为 `region`
  - 「关闭」（X）语义保持「真的关掉」：运行中先中止并 toast 说明，另补卸载时 `abort()`
    —— 旧实现关闭只是把组件摘掉，SSE 仍在后台空烧 token
  - 面板宽度可拖拽调整（左边缘，记忆在 `localStorage: ai:analysisDrawerWidth`）：默认 768px、
    下限 360px，且永远给主界面留 ≥260px；移动端面板高度让出 4rem 给底部导航，
    否则收起前的面板会把导航压住、连 tab 都切不了
  - Esc 语义按非模态重新定义：运行中 Esc **只收起**（不中断不丢结果），空闲才关闭；
    主界面正在输入框/文本域打字时不响应 —— 不做这个判断，用户在主搜索框按 Esc 想清空会被抽屉抢走
  - 验证：`tsc -p tsconfig.app.json` / `vite build` 通过，`npm test` 19 例通过

### Fixed
- **全市场行情源稳定性**（2026-09-11）
  - 新增 `backend/app/services/spot_service.py`：东财多域名轮换（`82.push2` 不可用时自动切 `push2/48/1/…`）+ 浏览器 UA/Referer + 页间节流 + 退避重试，解决 akshare `stock_zh_a_spot_em` 硬编码单域名、无 UA、无重试导致的 `('Connection aborted.', RemoteDisconnected(...))`
  - 兜底源更正为**新浪**（原注释误写为「腾讯」），并识别其 HTML 风控页给出可读错误，替代 `Can not decode value starting with character '<'`
  - 全市场快照统一字段命名（新增 `市盈率-动态` 等），`market` / `quad_service` / `opportunity_service` 三处重复的「东财 → 备用源」逻辑收敛到同一入口
  - 强制刷新 60s 节流 + 行情源失败 180s 冷却：避免高频 force 触发 IP 级风控，也避免风控期间每个请求都空等数十秒后才 502

### 🚧 进行中
- **V6 预警中心（站内提醒）**：数据层（`alert_rules` / `alert_events`）· 规则引擎（price_above / price_below / stop_loss / buy_point / support_break / resistance_break / volume_surge）· Cron 串行扫描 · 接口与前端铃声角标（见 ROADMAP 第三节）

### 📋 计划中
- **V6.5 外部推送**：Server酱（微信）/ 钉钉机器人 / Email / Webhook
- **V7 组合分析与风控**：行业分散度 / 相关性矩阵 / Beta / 波动率 / 仓位优化（马科维茨 / 风险平价）
- **V8 投资复盘 & 社交化**：交易记录 / 收益归因 / 周报月报 / 公开分享 / 跟单社区
- **V9 AI 增强**：个股 RAG 问答 / 财报速读 / 公告监控 / 行业研究图谱
- **V10 实时行情**：盘口十档 / 资金流向 / 个股异动雷达

---

## [V5.13] — 盘中节奏卡（2026-09-02）

### Added
- 盘前（9:00–9:25）「盘前预读」：今日大方向预读（复用 predict_tomorrow）+ 隔夜外盘（美股三大指数，6s 超时降级）
- 尾盘（14:45–15:00）每只持仓「挂单价 + 挂单方向 + 挂单建议」（减仓挂现价上方 0.5% 卖出、加仓回踩支撑买入）
- 尾盘窗口红色脉冲「收盘前必须完成挂单」紧急条
- 简报 payload 新增 `is_premarket` / `is_tail_urgent` 标记驱动前端时段渲染

---

## [V5.11 / V5.12] — 首屏指令化（2026-09-02）

### Added
- 今日作战简报卡：时点感知 + 大方向 + 建议仓位 + 早盘买什么 + 尾盘怎么操作
- 行动闭环：早盘关注池「加自选」一键、尾盘持仓卡「设提醒」一键
- 信号可信度标签：买点 / 止损 / 建议手数标注「算法推导」+ 风险自担声明
- 移动端首屏重点：尾盘时段尾盘卡先于关注池；关注池单列、按钮触控友好

### Changed
- 首屏清理冗余：原「大盘推衍」「每日推荐」折叠为默认收起的明细面板，首屏只留简报

---

## [V5.10] — 历史与大盘可读性

### Added
- 历史批次展示股票名称（后端 join `analysis_results` 附带 `stocks` / `names`）
- 大盘推衍卡片内嵌上证指数走势图（新接口 `GET /api/market/prediction/index-history`）

### Fixed
- 搜索框 loading 图标定位修正

---

## [V5.9] — 自选股 + 机会选股

### Added
- 自选股看板：`watchlist_service` / `WatchlistPanel`，增删、批量导入、实时涨跌
- 早盘竞价机会（9:15–9:30）：开盘强势、博当日大涨
- 尾盘机会（14:45–15:00）：尾盘异动、博次日高开
- 全市场实时快照短缓存 60s（东财优先、腾讯兜底）

---

## [V5.8] — 交易日历（时间敏感体系）

### Added
- `trade_calendar` 表（akshare 拉取 ±2 年，Supabase 持久化）
- 交易日映射服务：`last_trading_day` / `next_trading_day` / `is_trading_day` / `session_label`
- 北京时区交易时段：盘前 / 集合竞价 / 早盘 / 午休 / 午后 / 尾盘 / 收盘后
- 预测 / 推荐缓存 key 改为最近交易日（非自然日）；`target_date` 自动跳过周末与法定节假日
- 提示词升级：显式「交易日 T/T+1」语义 + 复盘研报风格 + 多空分水岭；上下文注入 `data_date` / `target_date`

---

## [V5.7] — 登录持久化 + 品牌

### Added
- `BrandLogo` 组件：渐变方块 + 脉冲光环 + 渐变文字
- Supabase Auth 客户端：cookie + localStorage 双重持久化 + auto refresh token
- `AuthContext` 改用 `onAuthStateChange` 自动同步 session

---

## [V5.6] — UI 体验升级（主流库）

### Added
- lucide-react 图标库、framer-motion 动画、sonner 全局 Toast
- AuthModal 升级为 Radix 风格无障碍弹窗动画

### Changed
- 构建分包：echarts / motion / vendor 独立 chunk，首屏 JS 1.4MB → 119KB
- `vercel.json` 缓存策略：index.html no-cache 根治部署白屏，assets 长期缓存

---

## [V5.5] — UI 布局重构（4 Tab 按场景分组）

### Added
- 发现好股：每日推荐 / 大盘推衍 / 板块热榜（一键勾选直达分析）
- 选股扫描：策略选股 / 全市场扫描 / 胜率看板 / 策略回测
- 深度分析：AI 综合分析（勾选联动自动开跑）
- 我的：持仓管理 + 历史记录（未登录显示登录引导）
- 面板折叠 + 状态记忆、记忆上次 Tab、头部全局股票搜索、移动端底部 Tab 导航
- Tab 常驻：切 Tab 组件不卸载，数据只加载一次，切换秒开

---

## [V5] — 持仓管理

### Added
- 用户持仓 CRUD（Supabase 持久化，按用户隔离）
- 风险等级：保守 / 稳健 / 进取 / 激进 + 总资金设置
- 持仓建议：仓位上限 / 信号强度 / 风报比 / 止损位
- 持仓盈亏展示：现价 / 市值 / 盈亏 / 技术信号

---

## [V4] — 策略回测

### Added
- 回测引擎：历史 K 线 → 策略信号 → 模拟调仓 → 收益 / 回撤 / 夏普 / 胜率
- 5 种策略：动量 / 趋势 / 低估值 / 放量 / 综合
- 默认股票池 18 只 + 历史数据缓存
- 前端回测面板：收益曲线 + 指标卡片（对比沪深 300 基准）

---

## [V3] — 数据闭环

### Added
- 预测记录 + 推荐记录持久化（Supabase 表）
- 胜率看板：预测命中率 + 推荐次日胜率
- 每日结算 Cron：Vercel Cron 收盘后自动结算
- 数据库建表：v1 / v2 / v3 全部 5 张表

---

## [V2] — 选股工具化

### Added
- 策略选股：动量 / 趋势 / 低估值 / 放量 四种策略一键扫描
- 技术信号：压力位 / 支撑位 / 买入点 / 卖出点 / 止损位 / 风险收益比 / 信号强度
- 明日大盘推衍：上证指数技术信号 + LLM 次日走势预测
- 持有建议：短期 / 中期 / 长期分维度研判
- 股票名称搜索：名称 / 代码模糊联想
- 每日收盘推荐：策略候选 + LLM 精选 10 只（含推荐理由 / 置信分）
- 每日缓存：推荐 / 推衍一天只跑一次（可强制刷新）

---

## [V1] — 基础平台

### Added
- LLM 驱动的个股四维分析（基本面 / 技术面 / 资金面 / 消息面）
- A 股全市场扫描 + 行业板块查看
- Supabase 登录注册 + 历史记录持久化
- Vercel 部署（前后端分离 + 代理）
