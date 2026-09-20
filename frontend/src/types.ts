export interface StockQuote {
  code: string;
  name: string;
  price: number;
  change_pct: number;
  turnover?: number;
  volume?: number;
  pe?: number;
  pb?: number;
  market_cap?: number;
}

export interface StockHistory {
  dates: string[];
  closes: number[];
  volumes?: number[];
}

export interface StockInfo {
  code: string;
  name: string;
  quote?: StockQuote;
  history?: StockHistory;
}

export interface NewsItem {
  title: string;
  url?: string;
  date?: string;
  source?: string;
}

export interface ScoreDimension {
  name: string;
  score: number;
  comment: string;
}

export interface TradeSignal {
  price: number;
  support: number;
  resistance: number;
  buy_point: number;
  sell_point: number;
  stop_loss: number;
  rr_ratio: number;
  strength: number;
  bb_upper?: number;
  bb_lower?: number;
  ma5?: number;
  ma20?: number;
  ma60?: number;
  low60?: number;
  high60?: number;
}

export interface StrategyAssessment {
  name: string;
  source: string;
  status: "passed" | "watch" | "failed" | "insufficient_data";
  score: number;
  passed: number;
  total: number;
  action: string;
  conditions: Array<{ label: string; passed: boolean }>;
}

export interface DebateSide {
  side: "bull" | "bear";
  thesis: string;
  evidence: string[];
  rebuttal: string[];
  confidence: number;
}

export interface DebateResult {
  rounds: number;
  bull: DebateSide | null;
  bear: DebateSide | null;
  /** 分歧度 0-100，口径 = min(多头信心, 空头信心)：两边都笃定才是真争议 */
  divergence: number;
  /** 辩论后的倾向：bull | bear | neutral。仅供展示，不得当作买卖依据 */
  direction: "bull" | "bear" | "neutral";
  key_disagreement: string;
  evidence?: {
    tier: string;
    label?: string;
    badge?: string;
    summary?: string;
    actionable?: boolean;
  };
  /** 恒为 false：辩论结论没有回测支撑，不得进入买卖点位置 */
  executable: boolean;
  gate_note: string;
}

/** 交易员基于辩论结论起草的交易计划（TradingAgents ③层）。
 *  是否采纳由 fund_manager_verdict 终审决定，本结构自身不携带执行许可。 */
export interface TradePlan {
  /** buy | add | hold | reduce | avoid */
  action: string;
  entry_price?: number | null;
  stop_price?: number | null;
  target_price?: number | null;
  /** 建议仓位占总资金 % */
  position_pct: number;
  batches: string[];
  rationale: string;
  invalidation: string;
}

/** 基金经理终审结论（TradingAgents ④层）：approved | demoted | rejected。
 *  硬约束（止损有效/仓位上限/辩论方向一致）全部由后端代码判定，非 LLM 裁量。 */
export interface FundManagerVerdict {
  decision: "approved" | "demoted" | "rejected";
  verdict_notes: string[];
  final_position_pct: number;
  final_stop_price?: number | null;
}

export interface StockAnalysis {
  code: string;
  name: string;
  overall_score: number;
  summary: string;
  dimensions: ScoreDimension[];
  risks: string[];
  suggestions: string[];
  signal?: TradeSignal;
  strategy?: StrategyAssessment;
  /** 命中的实战形态（全部条件成立才算命中） */
  tactics?: TacticResult[];
  /** 多空研究员辩论（仅在请求开启 debate 时有值） */
  debate?: DebateResult;
  /** 交易员计划 + 终审结论：辩论成功才产出；旧缓存缺省 undefined，前端须降级隐藏 */
  trade_plan?: TradePlan;
  fund_manager_verdict?: FundManagerVerdict;
  /** 本次分析在 agent_decisions 里落的对照行 id（一键采纳建仓用；旧缓存/未登录无值） */
  agent_decision_id?: number;
  holding_advice?: string;
}

export type SSEEventType =
  | "status"
  | "stock_start"
  | "debate_start"
  | "debate_done"
  | "trade_plan_start"
  | "trade_plan_done"
  | "delta"
  | "stock_done"
  | "stock_error"
  | "batch_saved"
  | "done"
  | "error";

export interface SSEEvent {
  type: SSEEventType;
  message: string;
  payload?: {
    code?: string;
    name?: string;
    result?: StockAnalysis;
    results?: StockAnalysis[];
    batch_id?: number;
  } | null;
}

// ---------- 市场筛选 ----------

export interface Industry {
  label: string;
  name: string;
  company_count: number;
  change_pct: number;
  avg_price: number;
}

export interface ScanStock {
  code: string;
  symbol: string;
  name: string;
  price: number;
  change_pct: number;
  amount_yi: number;
}

export interface ScanResult extends StockQuote {
  amount_yi?: number;
}

export interface StrategyStock {
  code: string;
  name: string;
  price: number;
  change_pct: number;
  pe?: number;
  pb?: number;
  turnover?: number;
  market_cap_yi?: number;
  strategy_score: number;
  tags: string[];
  indicators?: Record<string, number>;
}

export type StrategyName = "momentum" | "trend" | "value" | "volume";

export interface OpportunityStock {
  code: string;
  name: string;
  price: number;
  change_pct: number;
  amount_yi: number;
  volume_ratio: number;
  turnover: number;
  pe: number;
  amplitude: number;
  change_5min: number;
  score: number;
  stage: "auction" | "closing";
}

export interface OpportunityResult {
  stage: "auction" | "closing";
  stage_label: string;
  goal: string;
  items: OpportunityStock[];
  cached?: boolean;
  needs_scan?: boolean;
  source?: "cache" | "live" | "auto" | "manual";
  trade_date?: string;
  generated_at?: string | null;
  count?: number;
}

export interface StrategyDef {
  name: StrategyName;
  label: string;
  desc: string;
}

export interface StockSearchResult {
  code: string;
  name: string;
  price: number;
  change_pct: number;
}

export interface DailyRecommendation {
  code: string;
  name: string;
  price: number;
  change_pct: number;
  reason: string;
  confidence: number;
  /** 关联 daily_recommendations.id，模拟盘买卖可回写 related_reco_id */
  id?: string | null;
  tags?: string[];
  trigger?: string;
  invalidation?: string;
  target?: string;
  risk_reward?: number;
  valid_until?: string;
}

export interface DailyRecommendResult {
  /** 数据日：行情收盘对应的最近交易日 */
  date: string;
  /** 目标关注日：下一个交易日（T+1） */
  target_date?: string;
  source: "llm" | "rule" | "empty";
  recommendations: DailyRecommendation[];
  watchlist?: Array<{
    code: string;
    name: string;
    price: number;
    change_pct: number;
    score: number;
    tags?: string[];
    /** 拦截原因（风控硬门槛 + 策略势头），卡片要如实展示，不能只给买入指令 */
    status: string;
    /** 拦截原因的结构化列表，供前端逐条转成白话 */
    blockers?: string[];
    /** 解锁条件：满足什么才值得重新评估（旧字段名为 trigger） */
    unlock?: string;
    trigger?: string;
    /** 现价口径的盈亏比 / 上行空间 / 下行风险（%），用来解释「为什么不买」 */
    rr_ratio?: number | null;
    upside_pct?: number | null;
    downside_pct?: number | null;
    valid_until?: string;
  }>;
  candidates: number;
  /** 观察层数量（被拦下但接近条件的标的） */
  watch_candidates?: number;
  rejected?: number;
  message?: string;
  generated_at?: string;
}

/** 四维牛股榜：基本面/技术面/资金面/消息面 */
export interface QuadScores {
  fundamental: number;
  technical: number;
  capital: number;
  news: number;
}

export interface QuadStock {
  rank: number;
  code: string;
  name: string;
  price: number;
  change_pct: number;
  turnover: number | null;
  pe: number | null;
  market_cap_yi: number | null;
  overall_score: number;
  scores: QuadScores;
  tags: string[];
  comments: { fundamental: string; technical: string; capital: string; news: string };
}

export interface QuadRankResult {
  date: string;
  source: "rule";
  pool_size: number;
  /** 四维全部 >=7 的只数 */
  strict_count: number;
  items: QuadStock[];
}

/** 决策周期：1d 日线（战略） / 5m 15m 30m 60m 分钟线（日内战术） */
export type MonitorInterval = "1d" | "5m" | "15m" | "30m" | "60m";

/** 盯盘监控：实时行情 + 技术信号 → 操作指令
 *  日线与分钟线的信号字段不同，除公共字段外均为可选 */
export interface MonitorSignal {
  support: number;
  resistance: number;
  stop_loss: number;
  strength: number;
  volume_ratio: number | null;
  // —— 日线字段 ——
  buy_point?: number;
  sell_point?: number;
  rr_ratio?: number;
  ma20?: number;
  ma60?: number;
  high60?: number;
  low60?: number;
  // —— 分钟线（日内）字段 ——
  vwap?: number | null;
  day_open?: number | null;
  day_high?: number | null;
  day_low?: number | null;
  ma_fast?: number | null;
  ma_slow?: number | null;
  bb_upper?: number | null;
  bb_lower?: number | null;
  trend?: "up" | "down" | "flat";
  bars?: number;
  session?: string;
}

/** 日线战略锚点：用分钟周期决策时也要能看到大方向 */
export interface MonitorDaily {
  support: number;
  resistance: number;
  buy_point?: number;
  sell_point?: number;
  stop_loss: number;
  strength: number;
  ma20?: number;
  ma60?: number;
}

/** 可执行价位：打开就知道挂多少 */
export interface MonitorPlan {
  /** 建议买入/低吸价 */
  buy: number;
  /** 建议卖出/止盈价 */
  sell: number;
  /** 铁止损价 */
  stop: number;
  /** 目标位（压力位） */
  target: number;
  /** 建议仓位 % */
  position_pct: number;
  urgency: "high" | "mid" | "low";
}

export interface MonitorAdvice {
  action: "stop" | "sell" | "buy" | "hold";
  label: string;
  tone: "danger" | "warn" | "good" | "neutral";
  hint: string;
  /** 一句话指令，如「挂 39.80 买入 · 30% 仓」 */
  do: string;
  plan: MonitorPlan;
  dist: { to_stop: number; to_support: number; to_resistance: number };
  /** 传入持仓成本后回带的浮动盈亏 % */
  pnl_pct?: number | null;
  /** swing=日线波段 / intraday=日内（分钟周期） */
  scope?: "swing" | "intraday";
  period?: MonitorInterval;
  session_note?: string;
}

export interface MonitorStock {
  code: string;
  name: string;
  price: number;
  change_pct: number;
  turnover: number | null;
  quote_at?: string | null;
  signal: MonitorSignal;
  advice: MonitorAdvice;
  /** 日线战略锚点（任何周期都返回） */
  daily: MonitorDaily;
  /** 命中的实战形态（只有全部条件成立才返回） */
  tactics?: TacticResult[];
}

/** 顶层决策摘要 */
export interface MonitorSummary {
  total: number;
  act_now: number;
  /** 形态命中的只数 */
  tactic_hits?: number;
  stop: number;
  sell: number;
  buy: number;
  hold: number;
  top: {
    code: string;
    name: string;
    price: number;
    action: MonitorAdvice["action"];
    label: string;
    tone: MonitorAdvice["tone"];
    do: string;
  }[];
}

export interface MonitorResult {
  updated_at: string;
  quote_at?: string | null;
  freshness_seconds?: number | null;
  freshness?: "live" | "stale" | "closed" | "unknown";
  market_open?: boolean;
  poll_interval_seconds?: number;
  count: number;
  missed: string[];
  /**
   * 部分失败：true 时 `missed` 非空。界面**必须**提示「少了几只、为什么」——
   * 否则「少 3 只」与「行情源全挂」在列表上都只表现为变短，用户会把故障读成
   * 「今天没什么可操作的」（这正是 2026-09-18 那轮诊断的结论）。
   */
  partial?: boolean;
  /** 后端生成的一句话说明（总数 + 各原因只数），前端原样展示，不要自己拼 */
  notice?: string;
  /** 未出结果的原因分类：行情源问题 / K 线取数失败 / 客观历史不足，三者含义不同 */
  missed_detail?: {
    quote_missing: string[];
    history_missing: string[];
    signal_missing: string[];
  };
  /**
   * 周线/月线加载状态。`loaded=false` 表示「多周期形态未加载」（轮询只读缓存），
   * 与「该形态未命中」完全不是一回事，不要混为一谈。
   */
  periods?: { loaded: boolean; cache_only: boolean };
  /** 本次决策实际使用的周期 */
  interval: MonitorInterval;
  /** 分钟数据不可用、已降级为日线决策 */
  degraded?: boolean;
  summary?: MonitorSummary;
  items: MonitorStock[];
}

/** 持仓导入：解析候选（预览用，字段可能缺失） */
export interface ParsedHolding {
  code: string;
  name: string;
  cost_price: number | null;
  shares: number | null;
  valid?: boolean;
}

export interface ParsedImportResult {
  items: ParsedHolding[];
  warnings: string[];
}

/** 价格预警规则 */
export type AlertType = "stop_loss" | "breakdown" | "price_target" | "buy_point" | "sell_point";

export interface AlertRule {
  id: number;
  user_id: string;
  code: string;
  name: string;
  type: AlertType;
  threshold: number;
  enabled: boolean;
  note: string;
  created_at: string;
}

/** 价格预警事件 */
export interface AlertEvent {
  id: number;
  user_id: string;
  rule_id: number | null;
  code: string;
  name: string;
  title: string;
  message: string;
  price: number | null;
  severity: "info" | "warn" | "danger";
  is_read: boolean;
  created_at: string;
}

export interface BacktestResult {
  strategy: string;
  start: string;
  end: string;
  initial_capital: number;
  final_value: number;
  total_return: number;
  annual_return: number;
  max_drawdown: number;
  sharpe: number;
  win_rate: number;
  periods: number;
  benchmark_return: number | null;
  equity_curve: { date: string; value: number; holdings: string[] }[];
  pool_size: number;
  /** 口径：这里是「调仓期」胜率，样本单位是期不是票 */
  caliber?: Caliber;
}

export interface UserProfile {
  user_id: string;
  risk_level: string;
  total_capital: number;
}

export interface WatchStock {
  id: number;
  code: string;
  name: string;
  created_at: string;
  price?: number | null;
  change_pct?: number | null;
  turnover?: number | null;
  volume?: number | null;
  pe?: number | null;
  market_cap?: number | null;
  offline?: boolean;
}

export interface WatchSummary {
  total: number;
  up: number;
  down: number;
  flat: number;
  avg_change?: number | null;
}

export interface WatchlistData {
  watchlist: WatchStock[];
  summary?: WatchSummary | null;
}

export interface WatchImportResult {
  added: number;
  skipped: number;
  errors: string[];
}

export interface Holding {
  id: number;
  user_id: string;
  code: string;
  name: string;
  cost_price: number;
  shares: number;
  buy_date?: string | null;
  note?: string;
  created_at: string;
  current_price?: number | null;
  market_value?: number;
  pnl?: number | null;
  pnl_pct?: number | null;
  signal?: TradeSignal | null;
}

export interface HoldingsData {
  holdings: Holding[];
  total_value: number;
  total_cost: number;
  total_pnl: number;
  total_pnl_pct: number;
}

export interface HoldingAdviceItem {
  code: string;
  name: string;
  price?: number | null;
  cost_price: number;
  pnl_pct?: number | null;
  position_pct: number;
  strength: number;
  rr_ratio: number;
  support?: number | null;
  resistance?: number | null;
  stop_loss?: number | null;
  action: string;
  tips: string[];
}

export interface PortfolioAdvice {
  risk_level: string;
  risk_desc: string;
  total_capital: number;
  total_value?: number;
  total_pnl_pct?: number;
  portfolio_tips: string[];
  holdings_advice: HoldingAdviceItem[];
  generated_at: string;
}

/**
 * 测量口径定义（后端 calibers 是唯一来源）。
 *
 * 界面同屏会出现多个都叫「胜率」的数字，标的/持有期/分类数/基准各不相同，
 * 阅读时极易默认可比。渲染这些数字时必须同时展示它自己的口径。
 */
export interface Caliber {
  key: string;
  /** 名字自带标的与持有期，例如「个股推荐次日胜率（T+1 · 无基准）」 */
  name: string;
  target: string;
  window: string;
  /** 分类数（决定随机基线的量级） */
  bucket: string;
  /** 对比基准；无基准时会显式写「无…」 */
  benchmark: string;
  rule: string;
  unit: string;
  /** 这个口径最容易骗自己的地方 */
  pitfall: string;
  /** false 表示后端未登记该口径，不要据此下结论 */
  registered?: boolean;
}

export interface WinrateStats {
  prediction: {
    total: number;
    hit: number;
    hit_rate: number | null;
    by_direction: Record<string, { total: number; hit: number; hit_rate: number | null }>;
    sample_status?: "insufficient" | "developing" | "established";
    caliber?: Caliber;
  } | null;
  recommendation: {
    total: number;
    hit: number;
    hit_rate: number | null;
    sample_status?: "insufficient" | "developing" | "established";
    caliber?: Caliber;
    /** 按来源细分的结算数（quad=四维榜 / watch=观察层）；与主口径不可相加 */
    by_source?: Record<string, { total: number; hit: number; hit_rate: number | null; sample_status?: string }>;
  } | null;
  snapshot: {
    snapshot_date: string;
    prediction_rate: number | null;
    recommend_rate: number | null;
  } | null;
  /** 不可比声明：多种口径的数字不能比较、不能相加 */
  caliber_note?: string;
}

export interface PredictionStats {
  total: number;
  settled: number;
  hit: number;
  hit_rate: number | null;
  by_direction: Record<string, { total: number; hit: number; hit_rate: number | null }>;
}

export interface PredictionRecord {
  id: number;
  created_at: string;
  target_date: string;
  direction: string;
  direction_raw: string;
  direction_score?: number;
  probability?: string;
  expected_low?: number;
  expected_high?: number;
  summary?: string;
  actual_change?: number;
  actual_direction?: string;
  hit?: boolean;
  settled_at?: string;
}

export interface IndexHistory {
  index: string;
  dates: string[];
  opens: number[];
  highs: number[];
  lows: number[];
  closes: number[];
  volumes: number[];
  latest: number | null;
  change_pct: number | null;
  days: number;
}

/**
 * 市场状态识别结果。
 *
 * method：rule = 仅确定性规则；rule+hmm = 规则判定得到 HMM 印证，此时才带
 * state_persistence / expected_duration；neutral = 数据不足。
 * hmm_state 为 HMM 的独立意见，用于复核两者是否一致（不一致时以规则为准）。
 */
export interface MarketRegime {
  state: string; // 上行 / 震荡 / 下行
  regime_score: number; // 0-10
  method: string; // rule | rule+hmm | neutral
  hmm_state?: string | null;
  hmm_state_probs?: Record<string, number>;
  state_probs?: Record<string, number>;
  state_persistence?: number | null;
  expected_duration?: number | null;
  features?: Record<string, number>;
  note?: string | null;
}

/** 市场宽度（涨跌家数 / 涨停跌停 / 成交额环比）。 */
export interface MarketBreadth {
  up_count: number;
  down_count: number;
  flat_count: number;
  up_down_ratio: number;
  limit_up_count: number;
  limit_down_count: number;
  total_amount_yi: number;
  amount_change_pct: number | null;
  breadth_score: number;
  sample_size: number;
}

/** 方向分的合成明细，用于复核「方向是怎么来的」。 */
export interface DirectionModel {
  evidence_score: number;
  regime_state?: string;
  regime_score?: number;
  regime_method?: string;
  breadth_score?: number | null;
  llm_score?: number | null;
  llm_direction?: string | null;
  llm_contribution: number;
  raw_score: number;
  prev_score?: number | null;
  final_score: number;
}

export interface MarketPrediction {
  index: string;
  date: string;
  source: "llm" | "rule";
  summary: {
    direction: string;
    direction_score: number;
    expected_range?: { low: number; high: number };
    probability?: string;
    key_levels?: Record<string, number | undefined>;
    summary: string;
    drivers?: string[];
    trading_advice?: string;
    /** LLM 的原始方向文案（如「震荡偏强」）；对外标签以 direction 为准 */
    llm_direction?: string | null;
    direction_model?: DirectionModel;
  };
  technical: {
    price: number;
    day_change: number;
    vol_ratio: number;
    ret5: number;
    ret20: number;
    position_60d: number;
    signal?: TradeSignal;
    regime?: MarketRegime;
    breadth?: MarketBreadth | null;
    evidence_score?: number;
    data_date?: string;
    target_date?: string;
  };
}

// ---------- 历史记录 ----------

export interface AnalysisBatch {
  id: number;
  created_at: string;
  codes: string;
  mode: "mock" | "llm";
  total: number;
  avg_score: number | null;
  /** 该批次的股票（含名称），由后端附带上 */
  stocks?: { code: string; name: string; overall_score?: number }[];
  /** 便捷字段：名称串，如"贵州茅台、五粮液" */
  names?: string;
}

export interface AnalysisBatchDetail extends AnalysisBatch {
  results: StockAnalysis[];
}

// ---------- 模拟盘（V5 Paper Trading） ----------

/** 模拟盘成交流水（sim_trades） */
export interface SimTrade {
  id: number;
  user_id: string;
  code: string;
  name: string;
  side: "buy" | "sell";
  price: number;
  shares: number;
  fee: number;
  amount: number;
  executed_at: string;
  trade_date: string;
  source: "manual" | "briefing" | "recommend";
  related_reco_id?: string | null;
  note?: string;
}

/** 模拟盘账户总览 */
export interface SimAccount {
  cash: number;
  total_capital: number;
  market_value: number;
  total_value: number;
  realized_pnl: number;
  unrealized_pnl: number;
  total_pnl: number | null;
  total_pnl_pct: number | null;
  positions_cnt: number;
  initialized: boolean;
}

/** 模拟盘聚合持仓 */
export interface SimPosition {
  code: string;
  name: string;
  shares: number;
  avg_cost: number;
  current_price?: number | null;
  market_value?: number | null;
  unrealized_pnl?: number | null;
  pnl_pct?: number | null;
}

export interface SimPositionsData {
  positions: SimPosition[];
  realized_pnl: number;
  open_count: number;
}

/** 净值快照（portfolio_snapshots） */
export interface SimSnapshot {
  date: string;
  total_value: number;
  total_pnl: number;
  total_pnl_pct: number;
  cash: number;
  market_value: number;
}

/** 收益统计 */
export interface SimPerformance {
  snapshots: SimSnapshot[];
  realized_pnl: number;
  unrealized_pnl: number;
  total_pnl: number | null;
  total_pnl_pct: number | null;
  by_source: Record<string, { trades: number; buy_shares: number; sell_shares: number; buy_amount: number; sell_amount: number }>;
}

export interface SimTradesData {
  trades: SimTrade[];
  total: number;
  limit: number;
  offset: number;
}

// ---------- Agent 决策闭环 ----------

/** 一条 agent 决策记录（agent_decisions 行） */
export interface AgentDecision {
  id: number;
  code: string;
  name?: string;
  data_date: string;
  action: string;
  verdict: "approved" | "demoted" | "rejected";
  entry_price?: number | null;
  stop_price?: number | null;
  target_price?: number | null;
  position_pct: number;
  horizon_days: number;
  status: "adopted" | "ignored" | "rejected";
  sim_trade_id?: number | null;
  settled_at?: string | null;
  settle_price?: number | null;
  settle_basis?: string | null;
  pnl_pct?: number | null;
  hit?: boolean | null;
  reflection?: string;
  created_at: string;
}

/** 闭环统计（口径 agent_plan，随数据下发） */
export interface AgentPlanStats {
  adopted: { settled: number; hits: number; hit_rate: number | null; avg_pnl_pct: number | null; sample_note: string | null };
  ignored_control: { settled: number; hits: number; hit_rate: number | null; avg_pnl_pct: number | null; sample_note: string | null };
  caliber: { key: string; name: string; window: string; rule: string; unit: string; pitfall: string; registered: boolean };
}

export interface AgentDecisionsData {
  decisions: AgentDecision[];
  stats: AgentPlanStats | null;
}


// ---------- 今日作战简报（V6 体验重构） ----------

/** 早盘关注的一只票（含技术信号与建议仓位） */
export interface BriefingStock {
  code: string;
  name: string;
  price?: number;
  change_pct?: number;
  reason: string;
  confidence?: number;
  /** 关联 daily_recommendations.id，模拟盘一键买入时回写 related_reco_id 闭合胜率环 */
  id?: string | null;
  buy_point?: number | null;
  stop_loss?: number | null;
  sell_point?: number | null;
  strength?: number | null;
  rr_ratio?: number | null;
  suggest_amount?: number | null;
  suggest_shares?: number | null;
  risk_level?: string;
  trigger?: string;
  invalidation?: string;
  target?: string;
  valid_until?: string;
  /** 命中的实战形态（全部条件成立） */
  tactics?: TacticResult[];
}

/** 尾盘持仓操作项 */
export interface BriefingHolding {
  code: string;
  name: string;
  price?: number;
  cost_price?: number;
  pnl_pct?: number;
  position_pct?: number;
  strength?: number;
  rr_ratio?: number;
  support?: number | null;
  resistance?: number | null;
  stop_loss?: number | null;
  action: string;
  tips: string[];
  /** 尾盘挂单价（算法推导，非成交价） */
  limit_price?: number | null;
  /** 挂单方向：卖出 / 买入 / null */
  order_action?: string | null;
  /** 挂单建议文案 */
  order_hint?: string;
  /** 命中的实战形态（卖出形态会同步升级持仓建议） */
  tactics?: TacticResult[];
}

/** 隔夜外盘指数（盘前预读） */
export interface OverseasIndex {
  name: string;
  price: number;
  change_pct: number;
}

export interface Briefing {
  session: string;
  is_trading_day: boolean;
  /** 当前是否盘前时段（9:00–9:25），决定是否展示盘前预读 */
  is_premarket: boolean;
  /** 当前是否尾盘时段（14:45–15:00），决定是否展示"收盘前必须动" */
  is_tail_urgent: boolean;
  target_date?: string;
  /** morning | tail | closed —— 当前时段首屏主卡 */
  phase: "morning" | "tail" | "closed";
  generated_at: string;
  market: {
    index?: string;
    direction: string;
    direction_score: number;
    position_pct: number;
    position_suggestion: string;
    summary?: string;
    trading_advice?: string;
    key_levels?: Record<string, number | undefined>;
    pre_market?: {
      overseas?: OverseasIndex[] | null;
      note?: string | null;
    };
  };
  morning: {
    stocks: BriefingStock[];
    source?: string;
    candidates?: number;
  };
  tail: {
    holdings: BriefingHolding[];
    summary?: string | null;
    need_login: boolean;
    risk_level?: string;
  };
  /** 当日复盘（登录用户）：持仓盈亏快照 + 今日预警 + 一句话总结 */
  review?: {
    holdings_pnl?: {
      total_pnl?: number | null;
      total_pnl_pct?: number | null;
      count?: number;
      best?: { name: string; pnl_pct?: number | null } | null;
      worst?: { name: string; pnl_pct?: number | null } | null;
    } | null;
    alerts_today?: { title: string; message: string; severity: string }[] | null;
    actions?: string | null;
    summary?: string | null;
  } | null;
  /** 形态命中汇总：关注池（买点向）+ 持仓（卖点/风险向） */
  tactics?: BriefingTactics;
  /** 连板结论块：环境三档 + 资金面最强分组 + 持仓连板盯盘提示；后端获取失败为 null/缺省 */
  limitup?: BriefingLimitUp | null;
}

/** 简报连板块（briefing_service._build_limitup_block 产出）。 */
export interface BriefingLimitUp {
  trade_date?: string;
  session?: string;
  /** 三档操作建议（环境层，不是个股指令） */
  play_advice?: LimitUpPlayAdvice;
  /** 分层总括一句话（含「不是买入指令」免责） */
  headline?: string;
  /** 资金面最强档摘要（当日有连板股时才有） */
  top_tier?: {
    label: string;
    names: string[];
    codes: string[];
    rate: number;
    rate_n: number;
  } | null;
  sentiment?: LimitUpSentiment;
  evidence?: TacticEvidence;
  caliber?: Caliber;
  /** 持仓 ∩ 当日连板股，按 relay_score 升序（封板质量最差的优先提示） */
  holdings_relay?: BriefingHoldingRelay[] | null;
}

/** 持仓里的连板股：盯盘减仓优先级提示。 */
export interface BriefingHoldingRelay {
  code: string;
  name: string;
  boards: number;
  score: number;
  tier_label?: string;
  tier_note?: string;
  rate: number;
  hint: string;
}

// ---------- 实战形态（pattern_service） ----------

/** 技巧分类 */
export type TacticCategory = "周期共振" | "K线组合" | "量价关系" | "均线与指标" | "风控铁律";

/** 技巧方向：buy=买点 / sell=卖点或止损 */
export type TacticDirection = "buy" | "sell";

/** 形态证据等级：回测能否支持该形态作为操作依据 */
export type TacticEvidenceTier =
  | "verified"
  | "preliminary"
  | "unsupported"
  | "unknown"
  | "not_testable";

/** 单条技巧的证据记录（后端 tactic_evidence 是唯一来源） */
export interface TacticEvidence {
  tier: TacticEvidenceTier;
  /** 完整等级名：已验证 / 初步 / 未获支持 / 未验证 / 不可回测 */
  label: string;
  /** 展示层角标短名：已验证 / 初步 / 观察 */
  badge: string;
  /** 一句话依据（含量化结论） */
  summary: string;
  /** 证据来源：回测口径与样本 */
  provenance: string;
  /** 是否允许出现在买点 / 卖点位置（仅 verified 为 true） */
  actionable: boolean;
}

/** 技巧定义（GET /api/market/tactics） */
export interface TacticDef {
  key: string;
  name: string;
  category: TacticCategory;
  direction: TacticDirection;
  desc: string;
  /** daily=日线判定 / intraday=分钟线判定 */
  source: "daily" | "intraday";
  /** 取数时预留的最少日线根数 */
  history_days: number;
  /** 判定真正需要的预热根数（回测 walk-forward 从这一根开始） */
  warmup: number;
  /** 除日线外还需按周期取数的周期（多周期共振为 week/month） */
  extra_periods: string[];
  evidence: TacticEvidence;
  /** 是否允许出现在买点 / 卖点位置 */
  actionable: boolean;
}

/** 单条形态条件（逐条可复核） */
export interface TacticCondition {
  name: string;
  passed: boolean;
  detail: string;
  /** false 表示数据缺失、无法判定，不应视为通过 */
  available?: boolean;
}

/** 单只票在某个技巧上的判定结果 */
export interface TacticResult {
  key: string;
  name: string;
  category: TacticCategory;
  direction: TacticDirection;
  desc: string;
  /** 全部条件成立才为 true */
  matched: boolean;
  status: "matched" | "watch" | "failed" | "insufficient_data";
  score: number;
  passed: number;
  total: number;
  /** 一句话操作提示（算法推导，非投资建议） */
  action: string;
  conditions: TacticCondition[];
  metrics?: Record<string, number | string | null>;
  /**
   * 证据等级 / 可执行标记 / 观察池说明。
   *
   * 三者**可缺省**：`stock_analysis_cache` 里存有改造前写入的形态结果，
   * 那些行没有这几个字段。渲染时必须走 `TacticHit` 的兜底，不要直接取 `.evidence.label`。
   */
  evidence?: TacticEvidence;
  /** 命中 **且** 证据支持动作。false / 缺省时只能进观察池，不得展示为买点 / 卖点 */
  executable?: boolean;
  /** executable 为假时的观察池说明（替代动作话术） */
  gate_note?: string;
}

/** 单只票的形态体检结果（GET /api/market/tactic-check） */
export interface TacticStock {
  code: string;
  name: string;
  price: number | null;
  change_pct: number | null;
  turnover?: number | null;
  tactics: TacticResult[];
  /** 扫描结果附带：命中技巧中的最高分 */
  best_score?: number;
  /** 仅在有「证据达标」的命中时非空 */
  best_action?: string;
  /** 无证据达标命中时的观察池说明 */
  best_gate_note?: string;
  /** 本次命中的技巧里有几条证据达标 */
  executable_hits?: number;
}

/** 形态扫描结果（POST /api/market/tactic-scan） */
export interface TacticScanResult {
  count: number;
  /** 本次实际检查的候选只数 */
  checked: number;
  items: TacticStock[];
}

/** 形态证据等级总览（GET /api/market/tactic-evidence） */
export interface TacticEvidenceSurvey {
  total: number;
  /** 当前允许作为买卖点的技巧条数 */
  actionable: number;
  by_tier: Partial<Record<TacticEvidenceTier, number>>;
  /** 证据快照：这批结论是什么时候、用什么口径跑出来的 */
  snapshot: {
    run_at: string;
    pool: string;
    eval_bars: number;
    horizons: number[];
    prefix_lookback: number;
    generated_by: string;
    note: string;
  };
}

/** 证据台账（GET /api/market/evidence-ledger）—— 只读聚合，回答「哪些结论能动手」。 */
export interface EvidenceLedger {
  generated_at: string;
  counts: Partial<Record<TacticEvidenceTier, number>>;
  /** 各等级的含义，由后端给出（前端不要自己写一套说法） */
  tier_meaning: Record<string, string>;
  tier_order: TacticEvidenceTier[];
  /** 达到可执行档（verified）的口径 key —— 当前为空数组，这是刻意的留白 */
  actionable_keys: string[];
  actionable_count: number;
  items: EvidenceLedgerItem[];
  pattern_survey: TacticEvidenceSurvey;
  strategy_survey: {
    total: number;
    actionable: number;
    by_tier: Partial<Record<TacticEvidenceTier, number>>;
  };
  /** 观察期自积累进度：涨停池累积表已攒够几个交易日 */
  observation: {
    limitup_accumulated: {
      configured: boolean;
      days: number;
      rows: number;
      first_date: string | null;
      last_date: string | null;
    };
    note: string;
  };
  /** 一句话总结（含「0 条可执行」的诚实表述） */
  headline: string;
}

export interface EvidenceLedgerItem {
  key: string;
  /** pattern=K 线形态 / strategy=结构化策略口径 */
  namespace: "pattern" | "strategy";
  tier: TacticEvidenceTier;
  label: string;
  badge: string;
  actionable: boolean;
  summary: string;
  provenance: string;
}

/** 简报里的形态命中汇总 */
export interface BriefingTactics {
  /** 早盘关注池命中（偏买点） */
  morning: Array<{ code: string; name: string; tactics: TacticResult[] }>;
  /** 持仓命中（偏卖点/风险） */
  holdings: Array<{ code: string; name: string; tactics: TacticResult[] }>;
  summary?: string | null;
}

/** 形态回测：单条技巧的统计（POST /api/backtest/tactic） */
export interface TacticBacktestItem {
  key: string;
  name: string;
  category: TacticCategory;
  direction: TacticDirection;
  desc: string;
  status: "ok" | "insufficient_data" | "not_backtestable";
  note?: string | null;
  horizon_days: number;
  /** 评估时点数（基线样本量） */
  eval_points: number;
  /** 去重后的命中次数 */
  signals: number;
  stocks_evaluated: number;
  win_definition?: string | null;
  win_rate?: number | null;
  avg_return?: number | null;
  median_return?: number | null;
  avg_max_gain?: number | null;
  avg_max_drawdown?: number | null;
  baseline_win_rate?: number | null;
  baseline_avg_return?: number | null;
  /** 形态胜率 − 基准胜率（百分点） */
  edge_win_rate?: number | null;
  /** 方向调整后的收益超额（百分点） */
  edge_return?: number | null;
  /** 两个比例之差的 z 检验值 */
  z_score?: number | null;
  /** ≥30 次命中且 |z| ≥ 1.96 才为 true */
  significant?: boolean | null;
  /** insufficient / preliminary / significant / not_significant */
  confidence?: string;
  /** 一句话结论（含样本量与显著性） */
  verdict?: string | null;
  by_stock?: Array<{ code: string; signals: number; avg_return: number }>;
}

export interface TacticBacktestResult {
  horizon_days: number;
  eval_bars: number;
  pool: string[];
  pool_size: number;
  /** 取数失败 / 历史不足被剔除的票 */
  failed?: string[];
  /** 样本门槛：<min_samples 不给结论，<reliable_samples 不判显著 */
  min_samples?: number;
  reliable_samples?: number;
  generated_at: string;
  items: TacticBacktestItem[];
  /** 口径：命中后 N 日前向收益，且与同区间基准对比 */
  caliber?: Caliber;
  error?: string;
}

/** 行情源健康状态（GET /api/market/spot-status），供前端在「强制刷新」前判断能否安全触发。 */
export interface SpotStatus {
  /** 剩余冷却秒数，0 表示可安全刷新 */
  cooldown_seconds: number;
  in_cooldown: boolean;
  /** 进程内快照缓存年龄（秒），无缓存时为 null */
  snapshot_age_seconds: number | null;
  /** 缓存快照条数（全市场规模约 5400） */
  snapshot_size: number;
  /** 后端冷却窗口总长（用于展示口径，当前 180s） */
  cooldown_window_seconds: number;
  /** 强制刷新最小间隔（当前 60s） */
  force_min_interval_seconds: number;
}

/* ---------- 连板梯队（GET /api/limitup/snapshot · relay） ----------
 *
 * ⚠️ 这两种数据都**不是买卖信号**：连板接力只有「能否继续封板」这个中间指标上的
 * 正向线索，缺少收益口径（涨停池拿不到次日成交价），后端证据等级停在「初步」，
 * `evidence.actionable` 恒为 false。前端只做**位置描述与情绪描述**，
 * 不得渲染成买点、加仓或任何动作话术。
 */

/** 个股的连板位置分桶 —— 统计分桶，不是建议。 */
export interface LimitUpPosition {
  /** 启动 / 加速 / 中继 / 高位 / 分歧 */
  tag: string;
  reason: string;
}

/* ---------- 次日溢价读数（打板方向 · 口径 limitup_premium） ----------
 *
 * 这是项目里**唯一收益为正**的方向，但证据等级仍是 `preliminary` ——
 * 可成交性是代理口径（池快照没有量比字段，用换手率替代），真实成交率未知。
 * 因此前端纪律：
 *   · 读数不含动作词，不得渲染成买点/加仓/关注；
 *   · 必须**同时**展示期望与可成交性 —— 收益大头落在买不进的档
 *     （换手 <5% 期望最高但挂不上单），只展示期望会诱导去追一字板；
 *   · 数字一律用后端下发的，前端不自己算、不自己换口径。
 */

/** 单只涨停股的次日溢价读数。 */
export interface LimitUpPremium {
  /** 按换手率档给出的历史期望收益（%） */
  expect_pct: number;
  /** 换手率档：<5% / 5-15% / 15-30% / ≥30% */
  bucket: string;
  bucket_note: string;
  /** 可成交性（换手 ≥5%）：缩量一字/秒板期望最高但多数挂不上单 */
  tradable: boolean;
  /** 按首封时间档的期望；封板时间缺失时为 null（缺失 ≠ 尾盘板） */
  seal_expect_pct: number | null;
  seal_note: string;
  flags: LimitUpPremiumFlag[];
  evidence: TacticEvidence;
}

export interface LimitUpPremiumFlag {
  key: "late_seal" | "high_break" | string;
  label: string;
  tone: "warn" | "neutral";
  note: string;
}

/** 当日涨停池的溢价读数汇总：可成交档与不可成交档**分开报**。 */
export interface LimitUpPremiumSummary {
  total: number;
  /** 换手 ≥5% 的那部分；全为缩量一字板时为 null */
  tradable: { count: number; expect_low: number; expect_high: number } | null;
  /** 换手 <5% 的那部分：历史读数更高但多数挂不上单 */
  unbuyable: { count: number; expect_low: number; expect_high: number } | null;
  late_seal_count: number;
  buckets: LimitUpPremiumBucket[];
  /** 一句话结论（后端生成、自带免责句），前端原样展示 */
  headline: string;
  caliber: Caliber;
  evidence: TacticEvidence;
}

export interface LimitUpPremiumBucket {
  label: string;
  expect_pct: number;
  note: string;
  tradable: boolean;
  count: number;
  codes: string[];
  names: string[];
}

/** 涨停池个股（价格单位为元，市值/封单为亿元）。 */
export interface LimitUpStock {
  code: string;
  name: string;
  price: number;
  change_pct: number;
  /** 连板数：1 = 首板 */
  boards: number;
  /** 首次封板时间 HH:MM:SS，越早越强 */
  seal_time: string;
  last_seal_time: string;
  /** 盘中开板次数，0 = 封得死 */
  break_count: number;
  seal_fund_yi: number;
  float_mv_yi: number;
  turnover: number;
  amount_yi: number;
  /** 所属行业板块（用于识别主线） */
  sector: string;
  /** 统计口径：N 天 M 板 */
  stat_days: number;
  stat_boards: number;
  /** 封单占流通市值比（%），只能横向比、不能跨市值硬套 */
  seal_ratio: number;
  /**
   * 连板位置分桶。后端 `get_snapshot` 会给 ladder / stocks 两处都挂上；
   * 标注为可选是为了容忍滚动发布时连到旧后端的情况 —— 缺失时按「未知」降级，
   * 不要因为一个字段让整个梯队渲染成空白（同 TacticHit 对 evidence 的处理）。
   */
  position?: LimitUpPosition;
  /** 次日溢价读数（打板方向）；旧后端缺省 —— 缺失时整块隐藏，不要用默认值冒充 */
  premium?: LimitUpPremium;
}

/** 连板梯队的一档（>6 板合并为「6板+」）。 */
export interface LimitUpLadderGroup {
  key: number;
  /** 首板 / 2板 / … / 6板+ */
  label: string;
  count: number;
  items: LimitUpStock[];
}

/** 板块聚集度。 */
export interface LimitUpSector {
  sector: string;
  count: number;
  /** 其中连板（≥2 板）家数 */
  relay_count: number;
  max_boards: number;
  seal_fund_yi: number;
  avg_turnover: number;
  codes: string[];
  names: string[];
}

/** 当日情绪温度。 */
export interface LimitUpSentiment {
  limit_up_count: number;
  broken_count: number;
  /** 炸板率 % = 炸板家数 ÷ (涨停 + 炸板)，分母是「曾涨停过的家数」 */
  break_rate: number;
  max_boards: number;
  relay_count: number;
  first_board_count: number;
  /** 封板期间未开板的家数 */
  intact_count: number;
}

/** 情绪一句话点评。tone 由后端给出，前端只做配色映射。 */
export interface LimitUpSentimentNote {
  tone: "good" | "warn" | "neutral";
  text: string;
}

/** 今日操作建议（三档）。后端 play_advice 基于已回测口径（炸板率/断层/板块聚集度）给出，讲环境不讲个股。 */
export interface LimitUpPlayAdvice {
  /** avoid=空仓等待 / watch=只看不动手 / hunt=可打板 */
  level: "avoid" | "watch" | "hunt";
  title: string;
  reasons: string[];
  /** 梯队断层档位（如 [4] 表示 4 板档空缺） */
  gaps: number[];
  /** 主线板块名（聚集度最高的），无涨停时为 "—" */
  mainline: string;
}

export interface LimitUpSnapshot {
  trade_date: string;
  /** 时段标签：竞价 / 早盘 / 午休 / 尾盘 / 收盘 */
  session: string;
  cached: boolean;
  sentiment: LimitUpSentiment;
  sentiment_note: LimitUpSentimentNote;
  /** 滚动发布期连旧后端时缺省（undefined）—— 前端必须降级隐藏而不是报错 */
  play_advice?: LimitUpPlayAdvice;
  /** 连板股抽离 + 资金面持续性评分（三因子 0-3 分 → 回测晋级率读数）；旧后端缺省 */
  relay_stocks?: LimitUpRelayStock[];
  /** 强弱分层一览：给「哪个强哪个弱」一个分组层面的直接回答；旧后端缺省 */
  relay_tier_summary?: LimitUpTierSummary;
  /** 次日溢价读数汇总（可成交档 / 不可成交档分开报）；旧后端缺省 */
  premium_summary?: LimitUpPremiumSummary;
  ladder: LimitUpLadderGroup[];
  sectors: LimitUpSector[];
  stocks: LimitUpStock[];
  /** 炸板池是否取到；false 时 break_rate 只反映部分信息 */
  broken_ok: boolean;
  evidence: TacticEvidence;
  caliber: Caliber;
}

/** 晋级率按连板高度分档。 */
export interface LimitUpRelayRow {
  key: number;
  label: string;
  total: number;
  promoted: number;
  rate: number;
}

/** 资金面单因子判定（✓/✗ + 判定规则说明）。 */
export interface LimitUpScoreFactor {
  name: string;
  value: number;
  hit: boolean;
  /** 判定规则 + 回测出处（如「≥2% 记 1 分（回测：≥2% 档晋级率 44.7%…）」） */
  rule: string;
}

/** 连板股抽离条目：资金面持续性评分 + 明日晋级概率读数 + 相对强弱分层。 */
export interface LimitUpRelayStock {
  code: string;
  name: string;
  boards: number;
  sector: string;
  seal_time: string | null;
  seal_fund_yi: number;
  seal_ratio: number;
  turnover: number;
  break_count: number;
  /** 0-3 分 */
  score: number;
  max_score: number;
  /** 该得分档的历史晋级率读数（%，样本窗口仅 ~13 交易日，当相对强弱用） */
  rate: number;
  /** 该得分档的回测样本量 */
  rate_n: number;
  factors: LimitUpScoreFactor[];
  /** 强弱分层：1=资金面最强 / 2=较强 / 3=偏弱（含 0 分）；旧后端缺省 */
  tier?: number;
  /** 分层的人话标签，如「资金面最强」；旧后端缺省 */
  tier_label?: string;
  /** 分层一句话解释（缺哪个因子）；旧后端缺省 */
  tier_note?: string;
}

/** 资金面强弱分层一览（后端 relay_tier_summary 聚合产出）；旧后端缺省。 */
export interface LimitUpTierGroup {
  tier: number;
  label: string;
  desc: string;
  /** 该档的历史晋级率读数（%） */
  rate: number;
  rate_n: number;
  codes: string[];
  names: string[];
}

export interface LimitUpTierSummary {
  groups: LimitUpTierGroup[];
  /** 一句话总括（含「不是买入指令」的免责句） */
  headline: string;
}

/** 晋级率按板块聚集度分档（边缘分布，受连板高度混淆，需配合分层表看）。 */
export interface LimitUpRelayCluster {
  key: string;
  total: number;
  promoted: number;
  rate: number;
}

/** 分层交叉表的一个格子：控制住连板高度之后再看板块聚集度的影响。 */
export interface LimitUpRelayCell {
  boards: number;
  cluster: string;
  total: number;
  promoted: number;
  rate: number;
}

export interface LimitUpRelayStratum {
  /** 连板高度分桶（1..6，6 表示 6板+）。注意字段名是 boards，不是 key。 */
  boards: number;
  label: string;
  clusters: LimitUpRelayCell[];
}

export interface LimitUpRelayResult {
  caliber: Caliber;
  evidence: TacticEvidence;
  /** 请求的窗口天数 */
  days: number;
  /** 请求窗口（可能大于真正有数据的窗口） */
  date_range: string[];
  /** 真正取到数据的日期区间 —— 早于它的日期接口返回空池 */
  data_window: string[];
  /** 实际有数据的交易日数 */
  effective_days: number;
  /** 超出接口回溯范围、返回空池的日期（已排除出样本） */
  empty_dates: string[];
  /** 拉取失败的日期 */
  skipped_dates: string[];
  sessions: number;
  total_samples: number;
  overall_rate: number;
  avg_daily_limit_up: number;
  /** 随机水平参照（不是同口径基准，见 caliber.pitfall） */
  baseline_rate: number;
  market_universe: number;
  by_boards: LimitUpRelayRow[];
  by_cluster: LimitUpRelayCluster[];
  by_boards_cluster: LimitUpRelayStratum[];
  cached: boolean;
}

// ---------- 跌停池（抄底观察层）----------
//
// ⚠️ 这一组类型描述的是一个**负期望**策略的观测数据（n=133、期望 −4.47%/次）。
// 字段命名沿用 `LimitDown*` 只为与涨停侧对称，**不代表它是可执行信号** ——
// 后端 `evidence.actionable` 恒为 false，任何调用方都不得据此产出买点文案。

/** 跌停位置分桶（统计分组，不是建议）。 */
export interface LimitDownPosition {
  /** 首跌 / 换手 / 封死 / 连跌 / 深跌 */
  tag: string;
  reason: string;
}

/** 跌停池个股（价格单位为元，市值/封单为亿元）。 */
export interface LimitDownStock {
  code: string;
  name: string;
  price: number;
  change_pct: number;
  /** 连续跌停天数，1 = 首日跌停 */
  down_days: number;
  /** 最后封板时间 HH:MM:SS */
  last_seal_time: string;
  seal_fund_yi: number;
  float_mv_yi: number;
  turnover: number;
  amount_yi: number;
  sector: string;
  /**
   * 封单占流通市值比（%）。**与涨停侧同名指标语义相反**：那边封单厚 = 买盘强，
   * 这边封单厚 = 卖不掉。因此两者不能跨侧比较、也不能共用配色。
   */
  seal_ratio: number;
  /** 位置标注。旧后端缺省时按「未知」降级，不要让整段梯队渲染成空白。 */
  position?: LimitDownPosition;
}

/** 连续跌停梯队的一档（≥4 连跌合并为「4连跌+」）。 */
export interface LimitDownLadderGroup {
  key: number;
  /** 首日跌停 / 2连跌 / 3连跌 / 4连跌+ */
  label: string;
  count: number;
  items: LimitDownStock[];
}

/**
 * 跌停板块聚集度。
 *
 * ⚠️ 与涨停侧的板块聚集度**方向相反**：那边家数多是资金抱团做多，
 * 这边家数多是板块级利空。回测显示这里家数越多、次日越差（≥5 家期望 −7.17%），
 * 所以它是**风险读数**，不是机会读数。
 */
export interface LimitDownSector {
  sector: string;
  count: number;
  max_down_days: number;
  /** 其中连续跌停（≥2 日）家数 */
  chain_count: number;
  seal_fund_yi: number;
  avg_turnover: number;
  codes: string[];
  names: string[];
}

/** 当日跌停情绪。 */
export interface LimitDownSentiment {
  limit_down_count: number;
  limit_up_count: number;
  /** 跌停/涨停家数比；涨停数没取到时为 null（0 与「算不出来」是两件事） */
  down_up_ratio: number | null;
  chain_count: number;
  max_down_days: number;
  sector_count: number;
  top_sector: string | null;
  top_sector_count: number;
}

export interface LimitDownSentimentNote {
  tone: string;
  text: string;
}

export interface LimitDownSnapshot {
  trade_date: string;
  session: string;
  cached: boolean;
  sentiment: LimitDownSentiment;
  sentiment_note: LimitDownSentimentNote;
  ladder: LimitDownLadderGroup[];
  sectors: LimitDownSector[];
  stocks: LimitDownStock[];
  /** 涨停池是否取到；false 时 down_up_ratio 为 null */
  limit_up_ok: boolean;
  evidence: TacticEvidence;
  caliber: Caliber;
}

/**
 * 一个收益切片（全体 / 按是否封死 / 按连跌天数 / 按板块聚集度）。
 *
 * 字段可选是因为空桶只返回 `{ n: 0 }` —— 读取方一律用 `?? 0` 兜底，
 * 不要假定每个切片都有完整统计（那会让「某档无样本」直接抛错）。
 */
export interface LimitDownStats {
  n: number;
  /** 主口径：D 日跌停价买入 → D+1 集合竞价卖出的期望收益（%） */
  expect_open?: number;
  median_open?: number;
  /** 竞价卖出为正的比例（%） */
  win_rate_open?: number;
  avg_win?: number;
  avg_loss?: number;
  /** 在当前盈亏结构下期望为 0 所需的胜率（%）—— 本模块最该被看见的数字 */
  breakeven_win_rate?: number;
  expect_close?: number | null;
  win_rate_close?: number | null;
  /** 次日盘中最高价相对买入价（%）：反抽的弹性有多大 */
  avg_high?: number | null;
  /** 次日盘中曾转正的比例（%） */
  high_positive_rate?: number | null;
  /** 次日收盘仍跌停的比例（%），池子口径 */
  next_sealed_down_rate?: number;
  /** 次日反转涨停（地天板）的比例（%） */
  next_limit_up_rate?: number;
}

export interface LimitDownBucket extends LimitDownStats {
  key: string;
  label: string;
}

export interface LimitDownBrief {
  date: string;
  code: string;
  name: string;
  sector: string;
  /** 竞价卖出收益（%） */
  ret_open: number;
}

export interface LimitDownRepairResult {
  caliber: Caliber;
  evidence: TacticEvidence;
  days: number;
  date_range: string[];
  data_window: string[];
  effective_days: number;
  /** 所有空池日期（= 下面两者之和） */
  empty_dates: string[];
  /** 窗口内但当天真的没有跌停 —— 是有效信息（市场强），不是数据缺陷 */
  zero_down_dates: string[];
  /** 早于回溯下界、接口不提供数据 —— 是数据缺陷 */
  out_of_window_dates: string[];
  skipped_dates: string[];
  /** 候选样本总数（截断前） */
  candidate_size: number;
  /** 实际参与统计的样本数 */
  sample_size: number;
  /** true 表示候选超过样本上限，只统计了最近的部分 */
  truncated: boolean;
  overall: LimitDownStats;
  by_sealed: LimitDownBucket[];
  by_down_days: LimitDownBucket[];
  by_cluster: LimitDownBucket[];
  tail: {
    /** 次日跌停开盘（≤ −9%）的样本数 */
    drop9_n: number;
    drop9_rate: number;
    /** 次日一字跌停、挂单也卖不出去的样本数 */
    unsellable_n: number;
  };
  worst: LimitDownBrief[];
  best: LimitDownBrief[];
  cached: boolean;
}
