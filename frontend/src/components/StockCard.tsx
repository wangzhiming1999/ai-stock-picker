import type { StockAnalysis, StockInfo } from "../types";
import KLineChart from "./KLineChart";
import ScoreBar from "./ScoreBar";
import { fmtNum, safeArray } from "../lib/safe";

interface Props {
  analysis: StockAnalysis;
  info?: StockInfo;
}

export default function StockCard({ analysis, info }: Props) {
  const quote = info?.quote;
  const rising = (quote?.change_pct ?? 0) >= 0;
  const dimensions = safeArray<{ name?: string; score?: number }>(analysis.dimensions);
  const risks = safeArray<string>(analysis.risks);
  const suggestions = safeArray<string>(analysis.suggestions);

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
          <div className="text-4xl font-black text-brand">{fmtNum(analysis.overall_score, 1, "0")}</div>
          <div className="text-xs text-slate-500">/ 10</div>
        </div>
      </div>

      {/* K线 */}
      <div className="mt-4">
        <KLineChart history={info?.history} />
      </div>

      {/* 综合点评 */}
      <p className="mt-4 text-sm leading-relaxed text-slate-300">{analysis.summary ?? ""}</p>

      {/* 技术信号（压力位/买卖点/止损） */}
      {analysis.signal && (
        <div className="mt-4 rounded-lg border border-amber-900/40 bg-amber-950/20 p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-semibold text-amber-400">技术信号</span>
            <span className="flex items-center gap-1">
              <span className="text-[11px] text-slate-500">强度</span>
              <span className={`text-sm font-bold ${analysis.signal.strength >= 6 ? "text-green-400" : analysis.signal.strength >= 4 ? "text-yellow-400" : "text-red-400"}`}>
                {fmtNum(analysis.signal.strength, 1)}
              </span>
              <span className="text-[11px] text-slate-500">风报比</span>
              <span className={`text-sm font-bold ${analysis.signal.rr_ratio >= 2 ? "text-green-400" : analysis.signal.rr_ratio >= 1 ? "text-yellow-400" : "text-red-400"}`}>
                {fmtNum(analysis.signal.rr_ratio, 2)}
              </span>
            </span>
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs sm:grid-cols-3">
            <div className="flex justify-between rounded bg-slate-800/50 px-2 py-1">
              <span className="text-slate-500">支撑位</span>
              <span className="font-medium text-slate-200">{fmtNum(analysis.signal.support)}</span>
            </div>
            <div className="flex justify-between rounded bg-slate-800/50 px-2 py-1">
              <span className="text-slate-500">压力位</span>
              <span className="font-medium text-slate-200">{fmtNum(analysis.signal.resistance)}</span>
            </div>
            <div className="flex justify-between rounded bg-green-900/30 px-2 py-1">
              <span className="text-slate-400">买入区</span>
              <span className="font-medium text-green-400">{fmtNum(analysis.signal.buy_point)}</span>
            </div>
            <div className="flex justify-between rounded bg-red-900/30 px-2 py-1">
              <span className="text-slate-400">卖出区</span>
              <span className="font-medium text-red-400">{fmtNum(analysis.signal.sell_point)}</span>
            </div>
            <div className="flex justify-between rounded bg-slate-800/50 px-2 py-1">
              <span className="text-slate-500">止损位</span>
              <span className="font-medium text-orange-400">{fmtNum(analysis.signal.stop_loss)}</span>
            </div>
            <div className="flex justify-between rounded bg-slate-800/50 px-2 py-1">
              <span className="text-slate-500">现价</span>
              <span className="font-medium text-slate-200">{fmtNum(analysis.signal.price)}</span>
            </div>
          </div>
        </div>
      )}

      {/* 持有建议 */}
      {analysis.holding_advice && (
        <div className="mt-3 rounded-lg border border-blue-900/40 bg-blue-950/20 p-3">
          <div className="mb-1 text-xs font-semibold text-blue-400">持有建议</div>
          <p className="text-xs leading-relaxed text-blue-200/80">{analysis.holding_advice}</p>
        </div>
      )}

      {/* 维度评分 */}
      <div className="mt-4 space-y-2">
        {dimensions.map((d) => (
          <ScoreBar key={d.name ?? String(d.score)} label={d.name ?? "-"} score={d.score ?? 0} />
        ))}
      </div>

      {/* 风险 */}
      {risks.length > 0 && (
        <div className="mt-4 rounded-lg bg-red-950/40 border border-red-900/50 p-3">
          <div className="mb-1 text-xs font-semibold text-red-400">风险提示</div>
          <ul className="list-disc pl-4 text-xs text-red-300/80 space-y-0.5">
            {risks.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </div>
      )}

      {/* 建议 */}
      {suggestions.length > 0 && (
        <div className="mt-3 rounded-lg bg-slate-800/60 p-3">
          <div className="mb-1 text-xs font-semibold text-slate-400">操作建议</div>
          <ul className="list-disc pl-4 text-xs text-slate-300 space-y-0.5">
            {suggestions.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
