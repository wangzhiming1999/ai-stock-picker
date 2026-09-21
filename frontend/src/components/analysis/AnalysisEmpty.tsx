import { BarChart3 } from "lucide-react";

/** 空状态：尚未分析且不在运行。纯静态文案。 */
export default function AnalysisEmpty() {
  return (
    <div className="mt-10 text-center">
      <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-xl bg-surface-inset">
        <BarChart3 className="h-7 w-7 text-brand-light" aria-hidden />
      </div>
      <p className="mt-3 text-body text-ink-soft">
        输入 A 股代码，AI 将综合行情、K线趋势与最新新闻给出选股评分
      </p>
    </div>
  );
}
