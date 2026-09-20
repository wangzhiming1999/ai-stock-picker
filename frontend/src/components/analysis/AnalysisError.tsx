import type { Phase } from "./shared";

interface Props {
  phase: Phase;
  errorMsg: string;
}

/** 错误态：仅 error 阶段且有文案时渲染。 */
export default function AnalysisError({ phase, errorMsg }: Props) {
  if (phase !== "error" || !errorMsg) return null;

  return (
    <div className="mt-4 rounded-lg border border-red-800 bg-red-950/40 px-4 py-3 text-sm text-red-300">
      {errorMsg}
    </div>
  );
}
