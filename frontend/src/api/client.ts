import type {
  AnalysisBatch,
  AnalysisBatchDetail,
  AlertEvent,
  AlertRule,
  AlertType,
  Briefing,
  BacktestResult,
  DailyRecommendResult,
  Holding,
  HoldingsData,
  IndexHistory,
  Industry,
  MonitorResult,
  MarketPrediction,
  NewsItem,
  OpportunityResult,
  PortfolioAdvice,
  ParsedImportResult,
  PredictionRecord,
  PredictionStats,
  QuadRankResult,
  ScanStock,
  StockInfo,
  StockSearchResult,
  StrategyName,
  StrategyStock,
  SSEEvent,
  UserProfile,
  WatchImportResult,
  WatchlistData,
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

/** 从 Supabase session 读取登录 token（向后兼容 localStorage） */
export function getAuthToken(): string | null {
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.includes("-auth-token")) {
        const v = JSON.parse(localStorage.getItem(k) || "{}");
        if (v?.access_token) return v.access_token as string;
      }
    }
    return localStorage.getItem("ai_stock_token");
  } catch {
    return null;
  }
}

function authHeaders(): Record<string, string> {
  // 从 Supabase client 读取当前 session（自动 cookie/localStorage + 自动 refresh）
  // 注意：getSession 内部异步；同步接口仅返回缓存的 token，已在 onAuthStateChange 同步
  // 兜底：直接读 Supabase localStorage key
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.includes("-auth-token")) {
        const v = JSON.parse(localStorage.getItem(k) || "{}");
        if (v?.access_token) return { Authorization: `Bearer ${v.access_token}` };
      }
    }
    // 兼容旧 key
    const t = localStorage.getItem("ai_stock_token");
    if (t) return { Authorization: `Bearer ${t}` };
  } catch {
    /* ignore */
  }
  return {};
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

export async function runBacktest(params: {
  strategy: string;
  start_date: string;
  end_date: string;
  top_n: number;
  rebalance_days: number;
  initial_capital?: number;
  codes?: string[];
}): Promise<BacktestResult> {
  const res = await fetch(`${API}/backtest/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || `回测失败: ${res.status}`);
  }
  return res.json();
}

export async function fetchWinrate(): Promise<WinrateStats> {
  const res = await fetch(`${API}/market/winrate`);
  if (!res.ok) throw new Error(`获取胜率失败: ${res.status}`);
  return res.json();
}

// ---------- 持仓 ----------

async function authFetch(url: string, init?: RequestInit): Promise<Response> {
  const token = getAuthToken();
  const headers = new Headers(init?.headers);
  headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return fetch(url, { ...init, headers });
}

export async function fetchPortfolioProfile(): Promise<UserProfile> {
  const res = await authFetch(`${API}/portfolio/profile`);
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `获取配置失败: ${res.status}`);
  }
  return res.json();
}

export async function updatePortfolioProfile(payload: { risk_level?: string; total_capital?: number }): Promise<UserProfile> {
  const res = await authFetch(`${API}/portfolio/profile`, { method: "PUT", body: JSON.stringify(payload) });
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `更新配置失败: ${res.status}`);
  }
  return res.json();
}

export async function fetchHoldings(): Promise<HoldingsData> {
  const res = await authFetch(`${API}/portfolio/holdings`);
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `获取持仓失败: ${res.status}`);
  }
  return res.json();
}

export async function addHolding(payload: { code: string; cost_price: number; shares: number; buy_date?: string; note?: string }): Promise<Holding> {
  const res = await authFetch(`${API}/portfolio/holdings`, { method: "POST", body: JSON.stringify(payload) });
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `添加持仓失败: ${res.status}`);
  }
  return res.json();
}

export async function updateHolding(id: number, payload: Partial<{ cost_price: number; shares: number; note: string }>): Promise<Holding> {
  const res = await authFetch(`${API}/portfolio/holdings/${id}`, { method: "PUT", body: JSON.stringify(payload) });
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `更新持仓失败: ${res.status}`);
  }
  return res.json();
}

export async function removeHolding(id: number): Promise<void> {
  const res = await authFetch(`${API}/portfolio/holdings/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`删除持仓失败: ${res.status}`);
}

export async function fetchPortfolioAdvice(): Promise<PortfolioAdvice> {
  const res = await authFetch(`${API}/portfolio/advice`);
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `获取建议失败: ${res.status}`);
  }
  return res.json();
}

export async function fetchIndexHistory(days = 120): Promise<IndexHistory> {
  const res = await fetch(`${API}/market/prediction/index-history?days=${days}`);
  if (!res.ok) throw new Error(`获取大盘走势失败: ${res.status}`);
  return res.json();
}

export async function fetchQuadRanking(refresh = false): Promise<QuadRankResult> {
  const res = await fetch(`${API}/market/quad${refresh ? "?refresh=true" : ""}`);
  if (!res.ok) throw new Error(`获取四维牛股榜失败: ${res.status}`);
  return res.json();
}

export async function fetchMonitor(codes: string[]): Promise<MonitorResult> {
  const res = await fetch(`${API}/market/monitor`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ codes }),
  });
  if (!res.ok) throw new Error(`监控刷新失败: ${res.status}`);
  return res.json();
}

export async function parseHoldingImport(payload: { text?: string; image_base64?: string }): Promise<ParsedImportResult> {
  const res = await authFetch(`${API}/portfolio/import/parse`, { method: "POST", body: JSON.stringify(payload) });
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `解析失败: ${res.status}`);
  }
  return res.json();
}

export async function importHoldingsBatch(
  items: { code: string; name?: string; cost_price: number; shares: number; note?: string }[]
): Promise<{ added: number; skipped: number }> {
  const res = await authFetch(`${API}/portfolio/holdings/batch`, { method: "POST", body: JSON.stringify({ items }) });
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `批量导入失败: ${res.status}`);
  }
  return res.json();
}

/* ---------- 价格预警中心 ---------- */

export async function fetchAlertRules(): Promise<AlertRule[]> {
  const res = await authFetch(`${API}/alerts/rules`);
  if (!res.ok) throw new Error(`获取预警规则失败: ${res.status}`);
  return res.json();
}

export async function addAlertRule(payload: { code: string; type: AlertType; threshold: number; name?: string; note?: string }): Promise<AlertRule> {
  const res = await authFetch(`${API}/alerts/rules`, { method: "POST", body: JSON.stringify(payload) });
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `添加规则失败: ${res.status}`);
  }
  return res.json();
}

export async function deleteAlertRule(id: number): Promise<void> {
  const res = await authFetch(`${API}/alerts/rules/${id}`, { method: "DELETE" });
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `删除规则失败: ${res.status}`);
  }
}

export async function fetchAlertEvents(unreadOnly = false, limit = 50): Promise<AlertEvent[]> {
  const res = await authFetch(`${API}/alerts/events?unread_only=${unreadOnly}&limit=${limit}`);
  if (!res.ok) throw new Error(`获取预警事件失败: ${res.status}`);
  return res.json();
}

export async function fetchAlertUnread(): Promise<number> {
  const res = await authFetch(`${API}/alerts/unread`);
  if (!res.ok) return 0;
  return (await res.json()).count ?? 0;
}

export async function markAlertRead(): Promise<void> {
  await authFetch(`${API}/alerts/read`, { method: "POST" });
}

export async function evaluateAlerts(): Promise<number> {
  try {
    const res = await authFetch(`${API}/alerts/evaluate`, { method: "POST" });
    if (!res.ok) return 0;
    return (await res.json()).new_events ?? 0;
  } catch {
    return 0;
  }
}

export async function fetchBriefing(): Promise<Briefing> {
  const res = await authFetch(`${API}/briefing/today`);
  if (!res.ok) throw new Error(`获取今日简报失败: ${res.status}`);
  return res.json();
}

export async function fetchAuctionOpportunity(limit = 15, force = false): Promise<OpportunityResult> {
  const url = `${API}/market/opportunity/auction?limit=${limit}${force ? "&force=true" : ""}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`早盘竞价扫描失败: ${res.status}`);
  return res.json();
}

export async function fetchClosingOpportunity(limit = 15, force = false): Promise<OpportunityResult> {
  const url = `${API}/market/opportunity/closing?limit=${limit}${force ? "&force=true" : ""}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`尾盘扫描失败: ${res.status}`);
  return res.json();
}

// ---------- 自选股 ----------

export async function fetchWatchlist(): Promise<WatchlistData> {
  const res = await authFetch(`${API}/watchlist`);
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `获取自选失败: ${res.status}`);
  }
  return res.json();
}

export async function addToWatchlist(code: string): Promise<void> {
  const res = await authFetch(`${API}/watchlist`, { method: "POST", body: JSON.stringify({ code }) });
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `添加自选失败: ${res.status}`);
  }
}

export async function importToWatchlist(codes: string[]): Promise<WatchImportResult> {
  const res = await authFetch(`${API}/watchlist/import`, { method: "POST", body: JSON.stringify({ codes }) });
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `导入自选失败: ${res.status}`);
  }
  return res.json();
}

export async function checkWatchlist(codes: string[]): Promise<Record<string, boolean>> {
  const res = await authFetch(`${API}/watchlist/check`, { method: "POST", body: JSON.stringify({ codes }) });
  if (!res.ok) return {};
  return res.json();
}

export async function removeFromWatchlist(id: number): Promise<void> {
  const res = await authFetch(`${API}/watchlist/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`删除自选失败: ${res.status}`);
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
