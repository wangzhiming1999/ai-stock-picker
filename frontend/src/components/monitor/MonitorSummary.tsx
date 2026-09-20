import type { MonitorSummary } from "../../types";
import { toneClass, toneDot } from "./constants";

interface Props {
  summary: MonitorSummary;
  onlyAction: boolean;
  onToggleOnlyAction: () => void;
}

/** 今日决策条：一眼知道现在要不要动，可一键只看需要操作的标的 */
export default function MonitorSummary({ summary, onlyAction, onToggleOnlyAction }: Props) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="mb-3 rounded-xl border border-slate-800 bg-gradient-to-br from-slate-900 to-slate-950 p-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold text-ink">现在要不要动</span>
        {summary.act_now === 0 ? (
          <span className="text-xs text-ink-muted">全部观望，暂无需要立刻操作的标的</span>
        ) : (
          <>
            <span className="text-xs text-ink-soft">
              共 <b className="text-base text-white">{summary.act_now}</b> 只要操作
            </span>
            {summary.stop > 0 && (
              <span className="rounded-md border border-red-800/70 bg-red-950/50 px-2 py-0.5 text-xs text-red-300">
                止损 {summary.stop}
              </span>
            )}
            {summary.sell > 0 && (
              <span className="rounded-md border border-amber-800/60 bg-amber-950/40 px-2 py-0.5 text-xs text-amber-300">
                卖出/减仓 {summary.sell}
              </span>
            )}
            {summary.buy > 0 && (
              <span className="rounded-md border border-green-800/60 bg-green-950/40 px-2 py-0.5 text-xs text-green-300">
                买入 {summary.buy}
              </span>
            )}
            {(summary.tactic_hits ?? 0) > 0 && (
              <span
                title="命中实战形态（K 线量价条件全部成立）的只数。条件成立不等于形态被回测验证，未验证的命中只作观察"
                className="rounded-md border border-sky-800/60 bg-sky-950/40 px-2 py-0.5 text-xs text-sky-300"
              >
                形态命中 {summary.tactic_hits}（观察）
              </span>
            )}
          </>
        )}
        <button
          onClick={onToggleOnlyAction}
          className={`ml-auto rounded-lg border px-2.5 py-1 text-xs transition-colors ${
            onlyAction
              ? "border-brand bg-brand/10 text-brand-light"
              : "border-slate-700 text-ink-muted hover:text-ink"
          }`}
        >
          {onlyAction ? "显示全部" : "只看要操作的"}
        </button>
      </div>
      {summary.top.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {summary.top.map((t) => (
            <span
              key={t.code}
              title={t.do}
              className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs ${toneClass[t.tone] ?? toneClass.neutral}`}
            >
              <span className={`h-1.5 w-1.5 rounded-full ${toneDot[t.tone] ?? toneDot.neutral}`} />
              <b>{t.name}</b>
              <span className="opacity-80">{t.do || t.label}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
