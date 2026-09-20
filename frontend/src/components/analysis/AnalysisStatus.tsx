import RunningDot from "./RunningDot";
import type { Phase } from "./shared";

interface Props {
  phase: Phase;
  status: string;
  /** 本批请求的总只数，用于「已完成 2/3 只」的进度 */
  total: number;
  /** 已完成只数（items.length 只反映已完成的） */
  doneCount: number;
  /** 正在跑的那只代码，状态行里带一下 */
  currentCode: string;
}

/**
 * 流式状态条：运行中显示呼吸点 + 进度，完成显示「✓ 文案」。
 * 空文案时不渲染，避免占位空白。
 */
export default function AnalysisStatus({ phase, status, total, doneCount, currentCode }: Props) {
  if (!(phase === "running" || phase === "done") || !status) return null;

  return (
    <div className="mt-4 flex items-center gap-2 rounded-xl border border-slate-800 bg-slate-900 px-4 py-3 text-sm text-ink-soft">
      {phase === "running" ? (
        <>
          <RunningDot />
          <span>{status}</span>
          {total > 0 && (
            <span className="ml-auto shrink-0 text-xs text-ink-faint tabular-nums">
              {doneCount}/{total}
            </span>
          )}
          {currentCode && <span className="text-xs text-ink-faint">({currentCode})</span>}
        </>
      ) : (
        <span className="text-brand-light">✓ {status}</span>
      )}
    </div>
  );
}
