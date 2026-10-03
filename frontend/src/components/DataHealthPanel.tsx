import { useCallback, useEffect, useState } from "react";
import { fetchDataHealth } from "../api/client";
import type { DataHealth } from "../types";
import Button from "./ui/Button";
import CollapsiblePanel from "./ui/CollapsiblePanel";
import StatTile from "./ui/StatTile";

const STATUS = {
  healthy: { label: "正常", cls: "border-state-success-line bg-state-success-surface text-state-success-soft" },
  degraded: { label: "需关注", cls: "border-state-warn-line bg-state-warn-surface text-state-warn-soft" },
  critical: { label: "异常", cls: "border-state-danger-line bg-state-danger-surface text-state-danger-soft" },
  unavailable: { label: "不可用", cls: "border-state-danger-line bg-state-danger-surface text-state-danger-soft" },
} as const;

function timeLabel(value: string | null | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("zh-CN", { hour12: false });
}

export default function DataHealthPanel() {
  const [data, setData] = useState<DataHealth | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setData(await fetchDataHealth());
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const state = data ? STATUS[data.status] : null;
  const coverage = data?.snapshot_readiness?.field_coverage_pct;
  const minimumCoverage = coverage ? Math.min(...Object.values(coverage)) : null;

  return (
    <CollapsiblePanel
      id="data-health"
      title="数据健康中心"
      subtitle="结算调度、积压、行情缓存与点时特征覆盖率"
      action={<Button variant="outlineQuiet" size="sm" onClick={() => void load()} disabled={loading}>{loading ? "检查中…" : "重新检查"}</Button>}
    >
      {error && <div role="alert" className="rounded-lg border border-state-danger-line bg-state-danger-surface px-3 py-2 text-body text-state-danger-soft">{error}</div>}
      {!data && !error && <div className="p-3 text-body text-ink-soft">正在检查数据闭环…</div>}
      {data && state && (
        <div className="space-y-4">
          <div className={`flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2 text-meta ${state.cls}`}>
            <span className="font-semibold">闭环状态：{state.label}</span>
            <span>检查时间 {timeLabel(data.checked_at)}</span>
          </div>

          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <StatTile value={data.cron.age_hours != null ? `${data.cron.age_hours}h` : "—"} label="结算心跳距今" />
            <StatTile value={data.settlement?.settled_rows ?? "—"} label="已结算" />
            <StatTile value={data.settlement?.pending_rows ?? "—"} label="待结算" />
            <StatTile value={minimumCoverage != null ? `${minimumCoverage}%` : "—"} label="最低特征覆盖" />
          </div>

          <div className="grid gap-2 text-meta text-ink-muted sm:grid-cols-2">
            <div className="rounded-lg bg-surface-inset/50 px-3 py-2">最近成功结算：<span className="text-ink-soft">{timeLabel(data.cron.last_success_at)}</span></div>
            <div className="rounded-lg bg-surface-inset/50 px-3 py-2">最近行情缓存：<span className="text-ink-soft">{timeLabel(data.market_cache?.updated_at)}</span></div>
            <div className="rounded-lg bg-surface-inset/50 px-3 py-2">最早待结算：<span className="text-ink-soft">{data.settlement?.oldest_pending_date ?? "—"}</span></div>
            <div className="rounded-lg bg-surface-inset/50 px-3 py-2">点时样本：<span className="text-ink-soft">{data.snapshot_readiness?.settled_rows ?? 0}/{data.snapshot_readiness?.requirements.min_settled_rows ?? 300}</span></div>
          </div>

          {data.issues.length > 0 && (
            <div className="space-y-2">
              {data.issues.map((issue, index) => (
                <div key={`${issue.code}-${index}`} className={`rounded-lg border px-3 py-2 text-meta ${issue.severity === "critical" ? "border-state-danger-line bg-state-danger-surface text-state-danger-soft" : "border-state-warn-line bg-state-warn-surface text-state-warn-soft"}`}>
                  {issue.message}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </CollapsiblePanel>
  );
}
