import { useCallback, useEffect, useState } from "react";
import { fetchBatchDetail, fetchBatches } from "../api/client";
import { safeArray } from "../lib/safe";
import type { AnalysisBatch, AnalysisBatchDetail, StockAnalysis } from "../types";
import StockCard from "./StockCard";
import Button from "./ui/Button";
import Table, { Th } from "./ui/Table";
import Panel from "./ui/Panel";
import { CELL } from "../lib/ui";

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
      <Panel
        title="分析历史记录"
        actions={
          <Button variant="outlineQuiet" size="sm" onClick={() => void load()}>
            刷新
          </Button>
        }
      >        {loading && <div className="p-3 text-body text-ink-soft">加载中...</div>}
        {err && <div className="rounded-lg border border-state-danger-line bg-state-danger-surface px-3 py-2 text-body text-state-danger-soft">{err}</div>}
        {!loading && batches.length === 0 && <div className="p-3 text-body text-ink-soft">暂无历史记录，先运行一次分析吧</div>}
        {batches.length > 0 && (
          <Table label="分析历史记录" maxHeight="none" head={
            <tr>
              <Th>时间</Th>
              <Th>股票</Th>
              <Th>模式</Th>
              <Th align="right">数量</Th>
              <Th align="right">平均分</Th>
              <Th align="right">操作</Th>
            </tr>
          }>
                {batches.map((b) => (
                  <tr key={b.id} className="border-t border-surface-line-soft hover:bg-surface-inset/40">
                    <td className={`${CELL} text-ink-muted`}>{fmtTime(b.created_at)}</td>
                    <td className={CELL}>
                      {b.names ? (
                        <div className="max-w-[260px]">
                          <div className="truncate text-ink" title={b.names}>
                            {b.names}
                          </div>
                          <div className="truncate text-meta text-ink-muted" title={b.codes}>
                            {b.codes}
                          </div>
                        </div>
                      ) : (
                        <span className="text-ink">{b.codes}</span>
                      )}
                    </td>
                    <td className={CELL}>
                      <span className={`rounded-md px-1.5 py-0.5 text-meta ${b.mode === "llm" ? "bg-purple-900/50 text-purple-300" : "bg-surface-inset text-ink-muted"}`}>
                        {b.mode === "llm" ? "LLM" : "规则"}
                      </span>
                    </td>
                    <td className={`${CELL} text-right text-ink-muted`}>{b.total}</td>
                    <td className={`${CELL} text-right font-semibold text-brand-light`}>{b.avg_score?.toFixed(1) ?? "-"}</td>
                    <td className={`${CELL} text-right`}>
                      <button onClick={() => void openBatch(b.id)} className="rounded-md border border-surface-line px-2 py-0.5 text-meta text-ink-muted hover:text-ink">
                        查看
                      </button>
                    </td>
                  </tr>
                ))}
          </Table>
        )}
      </Panel>

      {selectedBatch && (
        <div>
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-body font-semibold text-ink-soft">
              批次 #{selectedBatch.id} · {fmtTime(selectedBatch.created_at)} · {selectedBatch.total} 只
            </h3>
            <button onClick={() => setSelectedBatch(null)} className="text-meta text-ink-muted hover:text-ink-soft">
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
