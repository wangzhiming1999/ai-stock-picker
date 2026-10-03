import { useCallback, useEffect, useState } from "react";
import { fetchShadowStrategies } from "../api/client";
import type { ShadowStrategyCandidate, ShadowStrategyReport } from "../types";
import Button from "./ui/Button";
import CollapsiblePanel from "./ui/CollapsiblePanel";

const BLOCKER_LABELS: Record<string, string> = {
  point_in_time_evidence_not_ready: "点时样本尚未成熟",
  avg_net_excess_not_positive: "平均净超额未转正",
  avg_net_excess_not_above_baseline: "平均净超额未超过基线",
  stable_windows_below_two_thirds: "跨窗口稳定性不足 2/3",
};

function blockerLabel(value: string) {
  if (BLOCKER_LABELS[value]) return BLOCKER_LABELS[value];
  if (value.startsWith("oos_selections_below_")) {
    const parts = value.split("_");
    return `样本外记录不足 ${parts[parts.length - 1]} 条`;
  }
  if (value.startsWith("hit_rate_lift_below_")) return "胜率提升不足 3 个百分点";
  return value;
}

function metric(value: number | null | undefined, suffix = "") {
  return value == null ? "—" : `${value}${suffix}`;
}

function CandidateRow({ candidate }: { candidate: ShadowStrategyCandidate }) {
  const tone = candidate.promotion_eligible
    ? "border-state-success-line bg-state-success-surface"
    : candidate.status === "rejected"
      ? "border-state-danger-line bg-state-danger-surface"
      : "border-surface-line bg-surface-inset/50";
  return (
    <div className={`rounded-xl border p-3 ${tone}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-body font-semibold text-ink">{candidate.label}</span>
        <span className="text-meta text-ink-muted">
          {candidate.promotion_eligible ? "进入人工复核" : candidate.status === "rejected" ? "未通过" : "积累中"}
        </span>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2 text-meta text-ink-muted sm:grid-cols-4">
        <span>样本外 <b className="text-ink-soft">{candidate.metrics.selections ?? 0}</b></span>
        <span>胜率 <b className="text-ink-soft">{metric(candidate.metrics.hit_rate, "%")}</b></span>
        <span>提升 <b className="text-ink-soft">{metric(candidate.hit_rate_lift, "点")}</b></span>
        <span>净超额 <b className="text-ink-soft">{metric(candidate.metrics.avg_excess_return, "%")}</b></span>
      </div>
      {candidate.blockers.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {candidate.blockers.map((item) => <span key={item} className="rounded-md bg-surface-panel/70 px-2 py-1 text-meta text-ink-muted">{blockerLabel(item)}</span>)}
        </div>
      )}
    </div>
  );
}

export default function ShadowStrategyPanel() {
  const [data, setData] = useState<ShadowStrategyReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setData(await fetchShadowStrategies());
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  return (
    <CollapsiblePanel
      id="shadow-strategies"
      title="影子策略实验室"
      subtitle="新算法只做留样与样本外对照，不自动修改生产权重"
      action={<Button variant="outlineQuiet" size="sm" onClick={() => void load()} disabled={loading}>{loading ? "评估中…" : "重新评估"}</Button>}
    >
      {error && <div role="alert" className="rounded-lg border border-state-danger-line bg-state-danger-surface px-3 py-2 text-body text-state-danger-soft">{error}</div>}
      {!data && !error && <div className="p-3 text-body text-ink-soft">正在读取生产点时样本…</div>}
      {data && (
        <div className="space-y-3">
          <div className="rounded-lg border border-brand/30 bg-brand/5 px-3 py-2 text-meta text-brand-light">
            影子模式 · 生产权重未修改 · 可用样本 {data.usable_samples ?? 0} 条 / {data.sample_dates ?? 0} 个交易日
          </div>
          {data.status === "storage_not_configured" && <div className="text-meta text-state-warn-soft">存储未配置，暂时无法读取生产留样。</div>}
          {data.status === "migration_required" && <div className="text-meta text-state-warn-soft">需要先执行 {data.migration} 数据迁移。</div>}
          {data.candidates.map((candidate) => <CandidateRow key={candidate.key} candidate={candidate} />)}
          {data.candidates.length === 0 && data.status !== "storage_not_configured" && data.status !== "migration_required" && <div className="text-meta text-ink-soft">尚无可评估的已结算样本。</div>}
        </div>
      )}
    </CollapsiblePanel>
  );
}
