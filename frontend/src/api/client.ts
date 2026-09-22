import type {
  AgentDecisionsData,
  AnalysisBatch,
  AnalysisBatchDetail,
  AlertEvent,
  AlertRule,
  AlertType,
  Briefing,
  BacktestResult,
  DailyRecommendResult,
  EvidenceLedger,
  Holding,
  HoldingsData,
  IndexHistory,
  Industry,
  LimitDownRepairResult,
  LimitDownSnapshot,
  LimitUpRelayResult,
  LimitUpSnapshot,
  MonitorInterval,
  MonitorResult,
  MarketPrediction,
  NewsItem,
  OpportunityResult,
  PortfolioAdvice,
  ParsedImportResult,
  PredictionRecord,
  PredictionStats,
  QuadRankResult,
  SanduScanResult,
  SanduAutoCandidatesResult,
  ScanStock,
  SimAccount,
  SimPerformance,
  SimPositionsData,
  SimTrade,
  SimTradesData,
  SpotStatus,
  StockInfo,
  StockSearchResult,
  StrategyName,
  StrategyStock,
  SSEEvent,
  TacticBacktestResult,
  TacticDef,
  TacticEvidenceSurvey,
  TacticScanResult,
  TacticStock,
  UserProfile,
  VanguardBoard,
  VanguardDiagnose,
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

/**
 * 统一读取后端错误详情（FastAPI 的 `detail`）。
 *
 * 为什么不直接抛状态码：后端在风控时会明确给出「行情源被风控，冷却中（63s 后重试）」，
 * 只显示 502 会让用户把「临时冷却」误判成「服务挂了」，然后反复重试 —— 而反复重试
 * 正是把 IP 封禁拖长的动作。拿不到 JSON（网关 502/504）时退回状态码。
 */
async function errorFrom(res: Response, fallback: string): Promise<Error> {
  try {
    const body = await res.json();
    const detail = typeof body?.detail === "string" ? body.detail.trim() : "";
    if (detail) return new Error(detail);
  } catch {
    /* 响应不是 JSON（Vercel/网关层错误页），走状态码兜底 */
  }
  return new Error(`${fallback}: ${res.status}`);
}

export async function fetchStock(code: string): Promise<StockInfo> {
  const res = await fetch(`${API}/stock/${code}`);
  if (!res.ok) throw await errorFrom(res, "获取股票失败");
  return res.json();
}

export async function fetchNews(code: string): Promise<NewsItem[]> {
  const res = await fetch(`${API}/stock/${code}/news`);
  if (!res.ok) throw await errorFrom(res, "获取新闻失败");
  return res.json();
}

// ---------- 行情源状态 ----------

/**
 * 行情源健康状态：冷却期内前端必须禁用「强制刷新」。
 *
 * 冷却状态由后端跨实例共享（`market_source_state` 表），因此这里拿到的是全局状态，
 * 不是「本浏览器上一次是否失败」——别的用户连点导致的风控同样要拦住本机操作。
 */
export async function fetchSpotStatus(): Promise<SpotStatus> {
  const res = await fetch(`${API}/market/spot-status`);
  if (!res.ok) throw await errorFrom(res, "获取行情源状态失败");
  return res.json();
}

// ---------- 市场筛选 ----------

export async function fetchIndustries(): Promise<Industry[]> {
  const res = await fetch(`${API}/market/industries`);
  if (!res.ok) throw await errorFrom(res, "获取行业板块失败");
  return res.json();
}

export async function fetchIndustryStocks(label: string): Promise<StockInfo[]> {
  const res = await fetch(`${API}/market/industries/${label}/stocks`);
  if (!res.ok) throw await errorFrom(res, "获取板块成分失败");
  return res.json();
}

export async function scanMarket(params: Record<string, number>, force = false): Promise<ScanStock[]> {
  const res = await fetch(`${API}/market/scan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...params, force }),
  });
  if (!res.ok) throw await errorFrom(res, "扫描失败");
  return res.json();
}

export async function strategyScan(
  strategy: StrategyName,
  limit = 20,
  minAmountYi = 3,
  force = false
): Promise<StrategyStock[]> {
  const res = await fetch(`${API}/market/strategy-scan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ strategy, limit, min_amount_yi: minAmountYi, force }),
  });
  if (!res.ok) throw await errorFrom(res, "策略扫描失败");
  return res.json();
}

/** 实战形态：技巧清单（分类 / 买卖方向 / 说明 + 证据等级） */
export async function listTactics(): Promise<TacticDef[]> {
  const res = await fetch(`${API}/market/tactics`);
  if (!res.ok) throw await errorFrom(res, "获取形态清单失败");
  return res.json();
}

/** 形态证据等级总览：分级口径、覆盖计数、证据快照（供角标说明与自查） */
export async function tacticEvidence(): Promise<TacticEvidenceSurvey> {
  const res = await fetch(`${API}/market/tactic-evidence`);
  if (!res.ok) throw await errorFrom(res, "获取形态证据等级失败");
  return res.json();
}

/**
 * 证据台账：每条口径的证据等级 + 样本出处 + 观察期自积累进度。
 *
 * 只读聚合（无回测、无行情请求）。用它回答「现在哪些结论能动手」——
 * 当前答案是 0 条，这是刻意的留白而不是缺数据。
 */
export async function fetchEvidenceLedger(): Promise<EvidenceLedger> {
  const res = await fetch(`${API}/market/evidence-ledger`);
  if (!res.ok) throw await errorFrom(res, "获取证据台账失败");
  return res.json();
}

/** 实战形态扫描：按技巧找命中标的（不区分买卖方向，由调用方按 direction 展示） */
export async function tacticScan(params: {
  tactic?: string;
  codes?: string[];
  limit?: number;
  minAmountYi?: number;
  force?: boolean;
}): Promise<TacticScanResult> {
  const res = await fetch(`${API}/market/tactic-scan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      tactic: params.tactic,
      codes: params.codes,
      limit: params.limit ?? 20,
      min_amount_yi: params.minAmountYi ?? 3,
      force: params.force ?? false,
    }),
  });
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `形态扫描失败: ${res.status}`);
  }
  return res.json();
}

/** 单票形态体检：返回全部技巧的逐条条件（含未命中） */
export async function tacticCheck(code: string): Promise<TacticStock> {
  const res = await fetch(`${API}/market/tactic-check?code=${encodeURIComponent(code)}`);
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `形态体检失败: ${res.status}`);
  }
  return res.json();
}

/**
 * 筹码形态扫描：按筹码峰形态（单峰密集 / 低位低获利 / 转移向上）筛命中标的。
 *
 * 复用 `POST /market/tactic-scan` 通用链路 —— 筹码形态就是注册在 pattern_service
 * 里的 chip_* 技巧，后端在 check_codes 里按需注入筹码序列。独立函数是为了
 * 调用点语义清晰（筹码页只扫 chip_* 键），而不是另一条 API。
 */
export async function chipScan(params: {
  tactic?: "chip_single_peak" | "chip_low_profit" | "chip_transfer_up";
  codes?: string[];
  limit?: number;
  minAmountYi?: number;
  force?: boolean;
}): Promise<TacticScanResult> {
  return tacticScan({ ...params, tactic: params.tactic });
}

/** 实战形态回测：walk-forward 验证技巧表现（含同区间基准对比） */
export async function tacticBacktest(params: {
  tactic?: string;
  codes?: string[];
  horizonDays?: number;
  evalBars?: number;
}): Promise<TacticBacktestResult> {
  const res = await fetch(`${API}/backtest/tactic`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      tactic: params.tactic,
      codes: params.codes,
      horizon_days: params.horizonDays ?? 10,
      eval_bars: params.evalBars ?? 250,
    }),
  });
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `形态回测失败: ${res.status}`);
  }
  return res.json();
}

export async function fetchPrediction(refresh = false): Promise<MarketPrediction> {
  const res = await fetch(`${API}/market/prediction${refresh ? "?refresh=true" : ""}`);
  if (!res.ok) throw await errorFrom(res, "大盘推衍失败");
  return res.json();
}

export async function fetchPredictionStats(): Promise<PredictionStats> {
  const res = await fetch(`${API}/market/prediction/stats`);
  if (!res.ok) throw await errorFrom(res, "获取预测统计失败");
  return res.json();
}

export async function fetchPredictionHistory(limit = 30): Promise<PredictionRecord[]> {
  const res = await fetch(`${API}/market/prediction/history?limit=${limit}`);
  if (!res.ok) throw await errorFrom(res, "获取预测历史失败");
  return res.json();
}

export async function settlePrediction(): Promise<{ settled: number }> {
  const res = await fetch(`${API}/market/prediction/settle`, { method: "POST" });
  if (!res.ok) throw await errorFrom(res, "结算失败");
  return res.json();
}

export async function searchStocks(q: string, limit = 8): Promise<StockSearchResult[]> {
  const res = await fetch(`${API}/market/search?q=${encodeURIComponent(q)}&limit=${limit}`);
  if (!res.ok) throw await errorFrom(res, "搜索失败");
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

/** 策略回测默认股票池（18 只行业代表标的）。留空 codes 时后端即用此池。 */
export async function fetchBacktestPool(): Promise<{ codes: string[]; count: number }> {
  const res = await fetch(`${API}/backtest/pool`);
  if (!res.ok) throw await errorFrom(res, "获取默认回测池失败");
  return res.json();
}

export async function fetchWinrate(): Promise<WinrateStats> {
  const res = await fetch(`${API}/market/winrate`);
  if (!res.ok) throw await errorFrom(res, "获取胜率失败");
  return res.json();
}

/* ---------- 连板梯队 ---------- */

/**
 * 当日连板全景：情绪温度 + 连板梯队 + 板块聚集度 + 个股位置标注。
 *
 * ⚠️ 返回体的 `evidence.actionable` 恒为 false（连板接力只到「初步」，见后端 evidence）。
 * 调用方**不得**把任何字段渲染成买点 —— 位置标签（启动/加速/中继/高位/分歧）是统计分桶。
 *
 * 数据源是东财 push2ex 涨停板池，与全市场快照（push2）是不同域名/端点，
 * 因此**不接** spotGuard 那套冷却闸门；默认走 60s 后端缓存即可。
 */
export async function fetchLimitUpSnapshot(force = false): Promise<LimitUpSnapshot> {
  const res = await fetch(`${API}/limitup/snapshot${force ? "?force=true" : ""}`);
  if (!res.ok) throw await errorFrom(res, "获取连板梯队失败");
  return res.json();
}

/**
 * 连板晋级率回溯（N 板 → 次日 N+1 板）。
 *
 * 默认取满接口回溯窗口（约 15 个交易日）。传更大的 days 也**不会**扩大样本：
 * 更早日期返回空池，会被后端识别为「无数据」并排除，可在 `empty_dates` / `data_window` 自查。
 */
export async function fetchLimitUpRelay(days?: number, force = false): Promise<LimitUpRelayResult> {
  const qs = new URLSearchParams();
  if (days != null) qs.set("days", String(days));
  if (force) qs.set("force", "true");
  const query = qs.toString();
  const res = await fetch(`${API}/limitup/relay${query ? `?${query}` : ""}`);
  if (!res.ok) throw await errorFrom(res, "获取连板晋级率失败");
  return res.json();
}

// ---------- 跌停池（抄底观察层）----------

/**
 * 当日跌停全景（家数 / 连跌梯队 / 板块聚集 / 个股位置）。
 *
 * ⚠️ 这不是抄底信号源。后端 `evidence.actionable` 恒为 false，证据等级是
 * `unsupported` —— 因为它**有明确的收益结论，而且是负的**（n=133、期望 −4.47%/次）。
 */
export async function fetchLimitDownSnapshot(force = false): Promise<LimitDownSnapshot> {
  const res = await fetch(`${API}/limitdown/snapshot${force ? "?force=true" : ""}`);
  if (!res.ok) throw await errorFrom(res, "获取跌停池失败");
  return res.json();
}

/**
 * 跌停次日修复收益回溯（D 日跌停价买入 → D+1 集合竞价 / 收盘 / 盘中最高）。
 *
 * ⚠️ 比 snapshot 贵得多：后端要为**每只**跌停股拉一次日 K（逐只请求是行情源风控主因）。
 * 因此后端有样本上限、结果缓存 6 小时，前端只在用户展开时请求一次，**不要轮询**。
 */
export async function fetchLimitDownRepair(
  days?: number,
  force = false,
): Promise<LimitDownRepairResult> {
  const qs = new URLSearchParams();
  if (days != null) qs.set("days", String(days));
  if (force) qs.set("force", "true");
  const query = qs.toString();
  const res = await fetch(`${API}/limitdown/repair${query ? `?${query}` : ""}`);
  if (!res.ok) throw await errorFrom(res, "获取跌停修复回测失败");
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
  if (!res.ok) throw await errorFrom(res, "删除持仓失败");
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
  if (!res.ok) throw await errorFrom(res, "获取大盘走势失败");
  return res.json();
}

export async function fetchQuadRanking(refresh = false): Promise<QuadRankResult> {
  const res = await fetch(`${API}/market/quad${refresh ? "?refresh=true" : ""}`);
  if (!res.ok) throw await errorFrom(res, "获取四维牛股榜失败");
  return res.json();
}

/* ---------- 决策先锋（三维选股 · 诊股） ---------- */

/**
 * 决策先锋三维榜：暗盘资金 / 趋势 / 活跃度 打分排序，同屏带板块强度、
 * 主力抱团、潜力龙头与买卖时机（结构位）。
 *
 * ⚠️ `evidence.tier` 恒为 `preliminary`（三维分是当日读数，不是收益口径）。
 * 调用方**不得**把它渲染成买点或动作指令。
 *
 * refresh=true 只穿透后端的榜单缓存；底层行情源仍走既有缓存与跨实例冷却，
 * 因此它**不会**触发全市场快照的强制直拉 —— 前端不需要为它加 spotGuard 闸门。
 */
export async function fetchVanguardBoard(refresh = false): Promise<VanguardBoard> {
  const res = await fetch(`${API}/market/vanguard${refresh ? "?refresh=true" : ""}`);
  if (!res.ok) throw await errorFrom(res, "获取决策先锋榜失败");
  return res.json();
}

/**
 * 单票三维体检（诊股）。命中榜单快照时后端零额外请求；否则现场算两只接口。
 * 只在用户显式操作时调用，不要轮询。
 */
export async function fetchVanguardDiagnose(code: string): Promise<VanguardDiagnose> {
  const res = await fetch(`${API}/market/vanguard/diagnose?code=${encodeURIComponent(code)}`);
  if (!res.ok) throw await errorFrom(res, "诊股失败");
  return res.json();
}

export async function fetchMonitor(
  codes: string[],
  force = false,
  costs?: Record<string, number>,
  interval: MonitorInterval = "1d"
): Promise<MonitorResult> {
  const res = await fetch(`${API}/market/monitor`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ codes, force, costs: costs ?? {}, interval }),
  });
  if (!res.ok) throw await errorFrom(res, "监控刷新失败");
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
  if (!res.ok) throw await errorFrom(res, "获取预警规则失败");
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
  if (!res.ok) throw await errorFrom(res, "获取预警事件失败");
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

/** 勾选标记部分预警为已读（ids 为空等价于全部已读）。 */
export async function markAlertReadPartial(ids: number[]): Promise<void> {
  await authFetch(`${API}/alerts/read/partial`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(ids),
  });
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

/* ---------- 模拟盘（V5 Paper Trading） ---------- */

export async function fetchSimAccount(): Promise<SimAccount> {
  const res = await authFetch(`${API}/sim/account`);
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `获取模拟账户失败: ${res.status}`);
  }
  return res.json();
}

export async function initSimAccount(total_capital?: number): Promise<SimAccount> {
  const res = await authFetch(`${API}/sim/account/init`, {
    method: "POST",
    body: JSON.stringify(total_capital ? { total_capital } : {}),
  });
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `初始化模拟账户失败: ${res.status}`);
  }
  return res.json();
}

export async function simTrade(payload: {
  code: string;
  side: "buy" | "sell";
  shares: number;
  price?: number;
  source?: "manual" | "briefing" | "recommend" | "agent" | "limitup_relay";
  related_reco_id?: string | null;
  note?: string;
  /** 预期价格（执行锚点）：建仓时计划成交的价位，仅记录用于事后对比滑点 */
  expected_price?: number;
}): Promise<{ trade: SimTrade; account: SimAccount; realized_pnl?: number }> {
  const res = await authFetch(`${API}/sim/trade`, { method: "POST", body: JSON.stringify(payload) });
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `模拟交易失败: ${res.status}`);
  }
  return res.json();
}

/* ---------- Agent 决策闭环（TradingAgents 执行闭环） ---------- */

export interface AgentAdoptResult {
  trade: unknown;
  account: SimAccount;
  plan: {
    decision_id: number;
    code: string;
    shares: number;
    budget: number;
    position_pct: number;
    stop_price?: number | null;
    target_price?: number | null;
  };
}

/** 按终审计划建仓模拟盘（后端换算手数；-approved/demoted 才放行）。 */
export async function simAdoptPlan(
  decision_id: number,
  price?: number
): Promise<AgentAdoptResult> {
  const res = await authFetch(`${API}/sim/from-plan`, {
    method: "POST",
    body: JSON.stringify({ decision_id, price: price ?? null }),
  });
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `计划建仓失败: ${res.status}`);
  }
  return res.json();
}

/** 当前用户的 agent 决策记录 + 闭环统计。 */
export async function fetchAgentDecisions(limit = 30): Promise<AgentDecisionsData> {
  const res = await authFetch(`${API}/sim/agent-decisions?limit=${limit}`);
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `获取 agent 决策记录失败: ${res.status}`);
  }
  return res.json();
}

export async function fetchSimPositions(): Promise<SimPositionsData> {
  const res = await authFetch(`${API}/sim/positions`);
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `获取模拟持仓失败: ${res.status}`);
  }
  return res.json();
}

export async function fetchSimTrades(limit = 50, offset = 0): Promise<SimTradesData> {
  const res = await authFetch(`${API}/sim/trades?limit=${limit}&offset=${offset}`);
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `获取成交记录失败: ${res.status}`);
  }
  return res.json();
}

export async function fetchSimPerformance(): Promise<SimPerformance> {
  const res = await authFetch(`${API}/sim/performance`);
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `获取收益统计失败: ${res.status}`);
  }
  return res.json();
}

export async function resetSimAccount(): Promise<SimAccount> {
  const res = await authFetch(`${API}/sim/reset`, { method: "POST", body: JSON.stringify({ confirm: true }) });
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `重置失败: ${res.status}`);
  }
  return res.json();
}

export async function fetchBriefing(): Promise<Briefing> {
  const res = await authFetch(`${API}/briefing/today`);
  if (!res.ok) throw await errorFrom(res, "获取今日简报失败");
  return res.json();
}

export async function fetchAuctionOpportunity(limit = 15, force = false): Promise<OpportunityResult> {
  const url = `${API}/market/opportunity/auction?limit=${limit}${force ? "&force=true" : ""}`;
  const res = await fetch(url);
  if (!res.ok) throw await errorFrom(res, "早盘竞价扫描失败");
  return res.json();
}

export async function fetchClosingOpportunity(limit = 15, force = false): Promise<OpportunityResult> {
  const url = `${API}/market/opportunity/closing?limit=${limit}${force ? "&force=true" : ""}`;
  const res = await fetch(url);
  if (!res.ok) throw await errorFrom(res, "尾盘扫描失败");
  return res.json();
}

// ---------- 三度交易理论（厚度·力度·速度）----------

/**
 * 三度扫描：对给定候选（≤30 只）逐只拉日 K 打分。
 *
 * 候选制扫描（类似 monitor/analysis），不碰全市场快照；逐只历史 K 由后端
 * gather_limited 控并发，走既有缓存链路 —— 前端不需要 spotGuard 闸门，
 * 但也不要轮询（每只都要一次腾讯 K 线请求）。
 */
export async function sanduScan(codes: string[], minOverall = 6.5): Promise<SanduScanResult> {
  const res = await fetch(`${API}/sandu/scan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ codes, min_overall: minOverall }),
  });
  if (!res.ok) throw await errorFrom(res, "三度扫描失败");
  return res.json();
}

/**
 * 三度自动候选：取当日主力净流入榜前列（吸筹侧）作为扫描候选。
 * 后端走东财资金流批量单请求，非逐股 —— 前端同样不需要 spotGuard 闸门。
 */
export async function sanduAutoCandidates(count = 20): Promise<SanduAutoCandidatesResult> {
  const res = await fetch(`${API}/sandu/auto-candidates?count=${count}`);
  if (!res.ok) throw await errorFrom(res, "自动候选获取失败");
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
  if (!res.ok) throw await errorFrom(res, "删除自选失败");
}

export async function fetchDailyRecommend(refresh = false): Promise<DailyRecommendResult> {
  const res = await fetch(`${API}/market/daily-recommend${refresh ? "?refresh=true" : ""}`);
  if (!res.ok) throw await errorFrom(res, "每日推荐失败");
  return res.json();
}

// ---------- 历史记录 ----------

export async function fetchBatches(limit = 20): Promise<AnalysisBatch[]> {
  const res = await fetch(`${API}/history/batches?limit=${limit}`, { headers: authHeaders() });
  if (!res.ok) throw await errorFrom(res, "获取历史失败");
  return res.json();
}

export async function fetchBatchDetail(batchId: number): Promise<AnalysisBatchDetail> {
  const res = await fetch(`${API}/history/batches/${batchId}`, { headers: authHeaders() });
  if (!res.ok) throw await errorFrom(res, "获取历史详情失败");
  return res.json();
}

/**
 * 触发批量分析，通过 EventSource/SSE 回调增量事件。
 * 使用 fetch + ReadableStream 解析，便于获取更多错误信息。
 */
export async function streamAnalysis(
  codes: string[],
  onEvent: (event: SSEEvent) => void,
  signal?: AbortSignal,
  force = false,
  debate = false
): Promise<void> {
  const res = await fetch(`${API}/analysis/stocks`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ codes, force, debate }),
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
