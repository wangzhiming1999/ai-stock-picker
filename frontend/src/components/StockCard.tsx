import type { StockAnalysis, StockInfo } from "../types";
import KLineChart from "./KLineChart";
import ScoreBar from "./ScoreBar";

interface Props {
  analysis: StockAnalysis;
  info?: StockInfo;
}

export default function StockCard({ analysis, info }: Props) {
  const quote = info?.quote;
  const rising = (quote?.change_pct ?? 0) >= 0;

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 backdrop-blur">
      {/* 头部 */}
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-lg font-bold text-white">
            {analysis.name}
            <span className="ml-2 text-sm font-normal text-slate-500">{analysis.code}</span>
          </h3>
          {quote && (
            <div className="mt-1 flex items-baseline gap-2">
              <span className="text-2xl font-semibold text-white">{quote.price.toFixed(2)}</span>
              <span className={`text-sm font-medium ${rising ? "text-green-400" : "text-red-400"}`}>
                {rising ? "+" : ""}
                {quote.change_pct.toFixed(2)}%
              </span>
            </div>
          )}
        </div>
        <div className="text-right">
          <div className="text-sm text-slate-400">综合评分</div>
          <div className="text-4xl font-black text-brand">{analysis.overall_score.toFixed(1)}</div>
          <div className="text-xs text-slate-500">/ 10</div>
        </div>
      </div>

      {/* K线 */}
      <div className="mt-4">
        <KLineChart history={info?.history} />
      </div>

      {/* 综合点评 */}
      <p className="mt-4 text-sm leading-relaxed text-slate-300">{analysis.summary}</p>

      {/* 维度评分 */}
      <div className="mt-4 space-y-2">
        {analysis.dimensions.map((d) => (
          <ScoreBar key={d.name} label={d.name} score={d.score} />
        ))}
      </div>

      {/* 风险 */}
      {analysis.risks.length > 0 && (
        <div className="mt-4 rounded-lg bg-red-950/40 border border-red-900/50 p-3">
          <div className="mb-1 text-xs font-semibold text-red-400">风险提示</div>
          <ul className="list-disc pl-4 text-xs text-red-300/80 space-y-0.5">
            {analysis.risks.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </div>
      )}

      {/* 建议 */}
      {analysis.suggestions.length > 0 && (
        <div className="mt-3 rounded-lg bg-slate-800/60 p-3">
          <div className="mb-1 text-xs font-semibold text-slate-400">操作建议</div>
          <ul className="list-disc pl-4 text-xs text-slate-300 space-y-0.5">
            {analysis.suggestions.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
