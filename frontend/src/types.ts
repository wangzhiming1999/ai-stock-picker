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
  date: string;
  source: "llm" | "rule" | "empty";
  recommendations: DailyRecommendation[];
  candidates: number;
  message?: string;
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
}

export interface AnalysisBatchDetail extends AnalysisBatch {
  results: StockAnalysis[];
}
