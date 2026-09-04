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

export interface StockAnalysis {
  code: string;
  name: string;
  overall_score: number;
  summary: string;
  dimensions: ScoreDimension[];
  risks: string[];
  suggestions: string[];
  signal?: TradeSignal;
  holding_advice?: string;
}

export type SSEEventType =
  | "status"
  | "stock_start"
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
  tags?: string[];
}

export interface DailyRecommendResult {
  /** 数据日：行情收盘对应的最近交易日 */
  date: string;
  /** 目标关注日：下一个交易日（T+1） */
  target_date?: string;
  source: "llm" | "rule" | "empty";
  recommendations: DailyRecommendation[];
  candidates: number;
  message?: string;
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

/** 盯盘监控：实时行情 + 技术信号 → 操作指令 */
export interface MonitorSignal {
  support: number;
  resistance: number;
  buy_point: number;
  sell_point: number;
  stop_loss: number;
  rr_ratio: number;
  strength: number;
  ma20: number;
  ma60: number;
  high60: number;
  low60: number;
}

export interface MonitorAdvice {
  action: "stop" | "sell" | "buy" | "hold";
  label: string;
  tone: "danger" | "warn" | "good" | "neutral";
  hint: string;
  dist: { to_stop: number; to_support: number; to_resistance: number };
}

export interface MonitorStock {
  code: string;
  name: string;
  price: number;
  change_pct: number;
  turnover: number | null;
  signal: MonitorSignal;
  advice: MonitorAdvice;
}

export interface MonitorResult {
  updated_at: string;
  count: number;
  missed: string[];
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
export type AlertType = "stop_loss" | "breakdown" | "price_target";

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

export interface WinrateStats {
  prediction: {
    total: number;
    hit: number;
    hit_rate: number | null;
    by_direction: Record<string, { total: number; hit: number; hit_rate: number | null }>;
  } | null;
  recommendation: {
    total: number;
    hit: number;
    hit_rate: number | null;
  } | null;
  snapshot: {
    snapshot_date: string;
    prediction_rate: number | null;
    recommend_rate: number | null;
  } | null;
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
  };
  technical: {
    price: number;
    day_change: number;
    vol_ratio: number;
    ret5: number;
    ret20: number;
    position_60d: number;
    signal?: TradeSignal;
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


// ---------- 今日作战简报（V6 体验重构） ----------

/** 早盘关注的一只票（含技术信号与建议仓位） */
export interface BriefingStock {
  code: string;
  name: string;
  price?: number;
  change_pct?: number;
  reason: string;
  confidence?: number;
  buy_point?: number | null;
  stop_loss?: number | null;
  sell_point?: number | null;
  strength?: number | null;
  rr_ratio?: number | null;
  suggest_amount?: number | null;
  suggest_shares?: number | null;
  risk_level?: string;
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
}
