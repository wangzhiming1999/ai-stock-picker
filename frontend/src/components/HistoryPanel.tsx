import { useCallback, useEffect, useState } from "react";
import { fetchBatchDetail, fetchBatches } from "../api/client";
import { safeArray } from "../lib/safe";
import type { AnalysisBatch, AnalysisBatchDetail, StockAnalysis } from "../types";
import StockCard from "./StockCard";
import Button from "./Button";

interface Props {
  refreshKey: number;
}

export default function HistoryPanel({ refreshKey }: Props) {
  const [batches, setBatches] = useState<AnalysisBatch[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [selectedBatch, setSelectedBatch] = useState<AnalysisBatchDetail | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setErr("");
    try {
      setBatches(await fetchBatches(20));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  const openBatch = async (id: number) => {
    setSelectedBatch(null);
    try {
      setSelectedBatch(await fetchBatchDetail(id));
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  const fmtTime = (iso: string) => {
    const d = new Date(iso);
    return `${d.getMonth() + 1}-${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  };

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-ink">分析历史记录</h3>
          <Button variant="outlineQuiet" size="sm" onClick={() => void load()} >
            刷新
          </Button>
        </div>
        {loading && <div className="p-3 text-sm text-ink-faint">加载中...</div>}
        {err && <div className="rounded-lg border border-red-800 bg-red-950/40 px-3 py-2 text-sm text-red-300">{err}</div>}
        {!loading && batches.length === 0 && <div className="p-3 text-sm text-ink-faint">暂无历史记录，先运行一次分析吧</div>}
        {batches.length > 0 && (
          <div className="overflow-hidden rounded-xl border border-slate-800">
            <table className="w-full text-sm">
              <thead className="bg-slate-900 text-left text-xs text-ink-muted">
                <tr>
                  <th scope="col" className="px-3 py-2">时间</th>
                  <th scope="col" className="px-3 py-2">股票</th>
                  <th scope="col" className="px-3 py-2">模式</th>
                  <th scope="col" className="px-3 py-2 text-right">数量</th>
                  <th scope="col" className="px-3 py-2 text-right">平均分</th>
                  <th scope="col" className="px-3 py-2 text-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {batches.map((b) => (
                  <tr key={b.id} className="border-t border-slate-800/60 hover:bg-slate-800/40">
                    <td className="px-3 py-2 text-ink-muted">{fmtTime(b.created_at)}</td>
                    <td className="px-3 py-2">
                      {b.names ? (
                        <div className="max-w-[260px]">
                          <div className="truncate text-ink" title={b.names}>
                            {b.names}
                          </div>
                          <div className="truncate text-xs text-ink-faint" title={b.codes}>
                            {b.codes}
                          </div>
                        </div>
                      ) : (
                        <span className="text-ink">{b.codes}</span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <span className={`rounded px-1.5 py-0.5 text-xs ${b.mode === "llm" ? "bg-purple-900/50 text-purple-300" : "bg-slate-800 text-ink-muted"}`}>
                        {b.mode === "llm" ? "LLM" : "规则"}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right text-ink-muted">{b.total}</td>
                    <td className="px-3 py-2 text-right font-semibold text-brand-light">{b.avg_score?.toFixed(1) ?? "-"}</td>
                    <td className="px-3 py-2 text-right">
                      <button onClick={() => void openBatch(b.id)} className="rounded border border-slate-700 px-2 py-0.5 text-xs text-ink-muted hover:text-ink">
                        查看
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {selectedBatch && (
        <div>
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-ink-soft">
              批次 #{selectedBatch.id} · {fmtTime(selectedBatch.created_at)} · {selectedBatch.total} 只
            </h3>
            <button onClick={() => setSelectedBatch(null)} className="text-xs text-ink-faint hover:text-ink-soft">
              收起
            </button>
          </div>
          <div className="grid gap-6 lg:grid-cols-2">
            {safeArray<StockAnalysis>(selectedBatch.results).map((r) => (
              <StockCard key={r.code} analysis={r} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
