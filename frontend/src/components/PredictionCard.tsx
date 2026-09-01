import { useCallback, useEffect, useState } from "react";
import { fetchPrediction } from "../api/client";
import type { MarketPrediction } from "../types";

function directionColor(d: string): string {
  if (d.includes("上涨") || d.includes("强")) return "text-green-400";
  if (d.includes("下跌") || d.includes("弱")) return "text-red-400";
  return "text-yellow-400";
}

export default function PredictionCard() {
  const [data, setData] = useState<MarketPrediction | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setErr("");
    try {
      setData(await fetchPrediction());
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-200">明日大盘推衍</h3>
        <button onClick={() => void load()} disabled={loading} className="rounded-lg border border-slate-700 px-3 py-1 text-xs text-slate-400 hover:text-slate-200 disabled:opacity-50">
          {loading ? "分析中..." : "刷新"}
        </button>
      </div>

      {err && <div className="rounded-lg border border-red-800 bg-red-950/40 px-3 py-2 text-sm text-red-300">{err}</div>}

      {!data && !err && <div className="p-3 text-sm text-slate-500">正在基于上证指数技术信号推衍明日走势...</div>}

      {data && (
        <div className="space-y-3">
          {/* 方向 + 概率 */}
          <div className="flex items-center gap-4">
            <div>
              <div className="text-xs text-slate-500">明日方向</div>
              <div className={`text-2xl font-black ${directionColor(data.summary.direction)}`}>
                {data.summary.direction}
                {data.summary.direction_score > 0 && (
                  <span className="ml-1 text-sm font-semibold text-slate-400">({data.summary.direction_score.toFixed(1)})</span>
                )}
              </div>
            </div>
            {data.summary.probability && (
              <div className="rounded-lg bg-slate-800/60 px-3 py-2 text-xs text-slate-300">
                {data.summary.probability}
              </div>
            )}
          </div>

          {/* 关键点位 */}
          {data.summary.key_levels && (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {Object.entries(data.summary.key_levels).map(([k, v]) => (
                <div key={k} className="rounded-lg bg-slate-800/50 px-2 py-1.5 text-center">
                  <div className="text-[11px] text-slate-500">{k}</div>
                  <div className="text-sm font-semibold text-slate-200">{v ?? "-"}</div>
                </div>
              ))}
            </div>
          )}

          {/* 研判 */}
          <p className="text-sm leading-relaxed text-slate-300">{data.summary.summary}</p>

          {/* 驱动因素 */}
          {data.summary.drivers && data.summary.drivers.length > 0 && (
            <div>
              <div className="mb-1 text-xs font-semibold text-slate-400">关键因素</div>
              <ul className="list-disc pl-4 text-xs text-slate-300 space-y-0.5">
                {data.summary.drivers.map((d, i) => (
                  <li key={i}>{d}</li>
                ))}
              </ul>
            </div>
          )}

          {/* 操作建议 */}
          {data.summary.trading_advice && (
            <div className="rounded-lg border border-amber-900/40 bg-amber-950/20 p-3">
              <div className="mb-1 text-xs font-semibold text-amber-400">操作建议</div>
              <p className="text-xs leading-relaxed text-amber-200/80">{data.summary.trading_advice}</p>
            </div>
          )}

          {/* 技术基础数据 */}
          <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-slate-800 pt-2 text-[11px] text-slate-500">
            <span>收盘 {data.technical.price.toFixed(2)}</span>
            <span>当日 {data.technical.day_change > 0 ? "+" : ""}{data.technical.day_change}%</span>
            <span>量比 {data.technical.vol_ratio}</span>
            <span>近5日 {data.technical.ret5 > 0 ? "+" : ""}{data.technical.ret5}%</span>
            <span>近20日 {data.technical.ret20 > 0 ? "+" : ""}{data.technical.ret20}%</span>
            <span>60日区间 {data.technical.position_60d}%</span>
            {data.technical.signal && (
              <span>信号强度 {data.technical.signal.strength.toFixed(1)}</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
