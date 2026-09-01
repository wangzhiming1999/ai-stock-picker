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

export interface StockAnalysis {
  code: string;
  name: string;
  overall_score: number;
  summary: string;
  dimensions: ScoreDimension[];
  risks: string[];
  suggestions: string[];
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
