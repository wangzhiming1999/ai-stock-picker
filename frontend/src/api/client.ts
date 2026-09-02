import type {
  AnalysisBatch,
  AnalysisBatchDetail,
  DailyRecommendResult,
  Industry,
  MarketPrediction,
  NewsItem,
  PredictionRecord,
  PredictionStats,
  ScanStock,
  StockInfo,
  StockSearchResult,
  StrategyName,
  StrategyStock,
  SSEEvent,
  WinrateStats,
} from "../types";

// 后端地址解析：
// 1. 生产环境默认使用相对路径 /api，由 Vercel rewrites 代理转发到后端（推荐，避免跨域）
// 2. 也可通过 VITE_API_BASE 指向独立后端域名（会清理 BOM/空白/尾部斜杠）
const BASE = (import.meta.env.VITE_API_BASE as string | undefined)
  ?.replace(/^\uFEFF/, "")   // 清理 PowerShell 管道可能带入的 BOM
  .trim()
  .replace(/\/$/, "") ?? "";
const API = `${BASE}/api`;

/** 从 localStorage 读取登录 token（供请求鉴权） */
export function getAuthToken(): string | null {
  try {
    return localStorage.getItem("ai_stock_token");
  } catch {
    return null;
  }
}

function authHeaders(): Record<string, string> {
  const token = getAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function fetchStock(code: string): Promise<StockInfo> {
  const res = await fetch(`${API}/stock/${code}`);
  if (!res.ok) throw new Error(`获取股票失败: ${res.status}`);
  return res.json();
}

export async function fetchNews(code: string): Promise<NewsItem[]> {
  const res = await fetch(`${API}/stock/${code}/news`);
  if (!res.ok) throw new Error(`获取新闻失败: ${res.status}`);
  return res.json();
}

// ---------- 市场筛选 ----------

export async function fetchIndustries(): Promise<Industry[]> {
  const res = await fetch(`${API}/market/industries`);
  if (!res.ok) throw new Error(`获取行业板块失败: ${res.status}`);
  return res.json();
}

export async function fetchIndustryStocks(label: string): Promise<StockInfo[]> {
  const res = await fetch(`${API}/market/industries/${label}/stocks`);
  if (!res.ok) throw new Error(`获取板块成分失败: ${res.status}`);
  return res.json();
}

export async function scanMarket(params: Record<string, number>): Promise<ScanStock[]> {
  const res = await fetch(`${API}/market/scan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) throw new Error(`扫描失败: ${res.status}`);
  return res.json();
}

export async function strategyScan(strategy: StrategyName, limit = 20, minAmountYi = 3): Promise<StrategyStock[]> {
  const res = await fetch(`${API}/market/strategy-scan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ strategy, limit, min_amount_yi: minAmountYi }),
  });
  if (!res.ok) throw new Error(`策略扫描失败: ${res.status}`);
  return res.json();
}

export async function fetchPrediction(refresh = false): Promise<MarketPrediction> {
  const res = await fetch(`${API}/market/prediction${refresh ? "?refresh=true" : ""}`);
  if (!res.ok) throw new Error(`大盘推衍失败: ${res.status}`);
  return res.json();
}

export async function fetchPredictionStats(): Promise<PredictionStats> {
  const res = await fetch(`${API}/market/prediction/stats`);
  if (!res.ok) throw new Error(`获取预测统计失败: ${res.status}`);
  return res.json();
}

export async function fetchPredictionHistory(limit = 30): Promise<PredictionRecord[]> {
  const res = await fetch(`${API}/market/prediction/history?limit=${limit}`);
  if (!res.ok) throw new Error(`获取预测历史失败: ${res.status}`);
  return res.json();
}

export async function settlePrediction(): Promise<{ settled: number }> {
  const res = await fetch(`${API}/market/prediction/settle`, { method: "POST" });
  if (!res.ok) throw new Error(`结算失败: ${res.status}`);
  return res.json();
}

export async function searchStocks(q: string, limit = 8): Promise<StockSearchResult[]> {
  const res = await fetch(`${API}/market/search?q=${encodeURIComponent(q)}&limit=${limit}`);
  if (!res.ok) throw new Error(`搜索失败: ${res.status}`);
  return res.json();
}

export async function fetchWinrate(): Promise<WinrateStats> {
  const res = await fetch(`${API}/market/winrate`);
  if (!res.ok) throw new Error(`获取胜率失败: ${res.status}`);
  return res.json();
}

export async function fetchDailyRecommend(refresh = false): Promise<DailyRecommendResult> {
  const res = await fetch(`${API}/market/daily-recommend${refresh ? "?refresh=true" : ""}`);
  if (!res.ok) throw new Error(`每日推荐失败: ${res.status}`);
  return res.json();
}

// ---------- 历史记录 ----------

export async function fetchBatches(limit = 20): Promise<AnalysisBatch[]> {
  const res = await fetch(`${API}/history/batches?limit=${limit}`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`获取历史失败: ${res.status}`);
  return res.json();
}

export async function fetchBatchDetail(batchId: number): Promise<AnalysisBatchDetail> {
  const res = await fetch(`${API}/history/batches/${batchId}`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`获取历史详情失败: ${res.status}`);
  return res.json();
}

/**
 * 触发批量分析，通过 EventSource/SSE 回调增量事件。
 * 使用 fetch + ReadableStream 解析，便于获取更多错误信息。
 */
export async function streamAnalysis(
  codes: string[],
  onEvent: (event: SSEEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  const res = await fetch(`${API}/analysis/stocks`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ codes }),
    signal,
  });

  if (!res.ok || !res.body) {
    throw new Error(`分析请求失败: ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE 事件以空行分隔
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";

    for (const part of parts) {
      for (const line of part.split("\n")) {
        if (!line.startsWith("data:")) continue;
        const raw = line.slice(5).trim();
        if (!raw) continue;
        try {
          onEvent(JSON.parse(raw) as SSEEvent);
        } catch {
          // 忽略无法解析的行
        }
      }
    }
  }
}
