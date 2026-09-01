import type { AnalysisBatch, AnalysisBatchDetail, Industry, NewsItem, ScanStock, StockInfo, SSEEvent } from "../types";

const BASE = "/api";

export async function fetchStock(code: string): Promise<StockInfo> {
  const res = await fetch(`${BASE}/stock/${code}`);
  if (!res.ok) throw new Error(`获取股票失败: ${res.status}`);
  return res.json();
}

export async function fetchNews(code: string): Promise<NewsItem[]> {
  const res = await fetch(`${BASE}/stock/${code}/news`);
  if (!res.ok) throw new Error(`获取新闻失败: ${res.status}`);
  return res.json();
}

// ---------- 市场筛选 ----------

export async function fetchIndustries(): Promise<Industry[]> {
  const res = await fetch(`${BASE}/market/industries`);
  if (!res.ok) throw new Error(`获取行业板块失败: ${res.status}`);
  return res.json();
}

export async function fetchIndustryStocks(label: string): Promise<StockInfo[]> {
  const res = await fetch(`${BASE}/market/industries/${label}/stocks`);
  if (!res.ok) throw new Error(`获取板块成分失败: ${res.status}`);
  return res.json();
}

export async function scanMarket(params: Record<string, number>): Promise<ScanStock[]> {
  const res = await fetch(`${BASE}/market/scan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) throw new Error(`扫描失败: ${res.status}`);
  return res.json();
}

// ---------- 历史记录 ----------

export async function fetchBatches(limit = 20): Promise<AnalysisBatch[]> {
  const res = await fetch(`${BASE}/history/batches?limit=${limit}`);
  if (!res.ok) throw new Error(`获取历史失败: ${res.status}`);
  return res.json();
}

export async function fetchBatchDetail(batchId: number): Promise<AnalysisBatchDetail> {
  const res = await fetch(`${BASE}/history/batches/${batchId}`);
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
  const res = await fetch(`${BASE}/analysis/stocks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
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
