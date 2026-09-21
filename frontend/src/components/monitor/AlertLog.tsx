import { BellRing } from "lucide-react";
import type { MonitorAlertItem } from "./constants";
import { fmtTime, toneClass } from "./constants";

interface Props {
  /** 页内提醒留痕：toast 会消失，这份列表不会 */
  alerts: MonitorAlertItem[];
  onClear: () => void;
}

/** 盯盘提醒留痕：顶部的浮层提示会限时消失，这里保留并可回看 */
export default function AlertLog({ alerts, onClear }: Props) {
  if (alerts.length === 0) return null;
  return (
    <div className="mb-3 rounded-xl border border-state-warn-line bg-surface-panel/60 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <BellRing className="h-3.5 w-3.5 text-amber-300" aria-hidden />
        <span className="text-meta font-semibold text-ink">盯盘提醒</span>
        <span className="text-meta text-ink-muted">
          本次 <b className="text-ink-soft">{alerts.length}</b> 条 · 最近的在最前
        </span>
        <button
          onClick={onClear}
          className="ml-auto rounded-lg border border-surface-line px-2.5 py-1 text-meta text-ink-muted transition-colors hover:text-ink"
        >
          清空
        </button>
      </div>
      <ul className="mt-2 space-y-1">
        {alerts.map((a) => (
          <li key={a.id} className="flex flex-wrap items-center gap-2 text-meta">
            <span className="tabular-nums text-ink-muted">{fmtTime(a.at)}</span>
            <span
              className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 ${
                toneClass[a.tone] ?? toneClass.neutral
              }`}
            >
              <b>{a.name}</b>
              <span className="opacity-80">{a.label}</span>
            </span>
            <span className="text-ink-soft">{a.body}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
