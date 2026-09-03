import { useCallback, useEffect, useState } from "react";
import { fetchIndexHistory, fetchPrediction, fetchPredictionHistory, fetchPredictionStats } from "../api/client";
import CollapsiblePanel from "./CollapsiblePanel";
import KLineChart from "./KLineChart";
import { safeArray, safeObj } from "../lib/safe";
import type { IndexHistory, MarketPrediction, PredictionRecord, PredictionStats, StockHistory } from "../types";

function directionColor(d: string): string {
  if (d.includes("上涨") || d.includes("强")) return "text-green-400";
  if (d.includes("下跌") || d.includes("弱")) return "text-red-400";
  return "text-yellow-400";
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getMonth() + 1}-${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export default function PredictionCard() {
  const [data, setData] = useState<MarketPrediction | null>(null);
  const [stats, setStats] = useState<PredictionStats | null>(null);
  const [history, setHistory] = useState<PredictionRecord[]>([]);
  const [indexHist, setIndexHist] = useState<IndexHistory | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const load = useCallback(async (force = false) => {
    setLoading(true);
    setErr("");
    try {
      const [p, s, h] = await Promise.all([
        fetchPrediction(force),
        fetchPredictionStats().catch(() => null),
        fetchPredictionHistory(15).catch(() => []),
      ]);
      setData(p);
      setStats(s);
      setHistory(h);
      // 大盘走势图（只读行情，失败不影响主流程）
      fetchIndexHistory(120)
        .then(setIndexHist)
        .catch(() => setIndexHist(null));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  // 转成 KLineChart 需要的结构
  const chartHistory: StockHistory | undefined = indexHist
    ? { dates: indexHist.dates, closes: indexHist.closes, volumes: indexHist.volumes }
    : undefined;

  useEffect(() => {
    void load();
  }, [load]);

  const hitColor = (hit: boolean | undefined) => (hit ? "bg-green-900/40 text-green-300" : "bg-red-900/40 text-red-300");

  return (
    <CollapsiblePanel
      id="prediction"
      title="明日大盘推衍"
      subtitle="上证指数技术信号 + AI 预测 · 附准确率追踪"
      action={
        <button onClick={() => void load(true)} disabled={loading} className="rounded-lg border border-slate-700 px-3 py-1 text-xs text-slate-400 hover:text-slate-200 disabled:opacity-50">
          {loading ? "分析中..." : "强制刷新"}
        </button>
      }
    >

      {err && <div className="rounded-lg border border-red-800 bg-red-950/40 px-3 py-2 text-sm text-red-300">{err}</div>}

      {!data && !err && <div className="p-3 text-sm text-slate-500">正在基于上证指数技术信号推衍明日走势...</div>}

      {data && (
        <div className="space-y-3">
          {/* 方向 + 概率 */}
          <div className="flex items-center gap-4">
            <div>
              <div className="text-xs text-slate-500">
                {data.technical?.target_date ? `${data.technical.target_date} 方向` : "下一个交易日方向"}
              </div>
              <div className={`text-2xl font-black ${directionColor(data.summary.direction)}`}>
                {data.summary.direction ?? "-"}
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

          {/* 大盘走势图 */}
          {chartHistory && (
            <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-2">
              <div className="mb-1 flex items-center justify-between px-1">
                <span className="text-[11px] text-slate-500">
                  {indexHist?.index ?? "上证指数"} · 近 {indexHist?.days ?? 0} 个交易日
                </span>
                {indexHist?.latest != null && (
                  <span className="flex items-baseline gap-1.5">
                    <span className="text-sm font-semibold text-slate-200">{indexHist.latest.toFixed(2)}</span>
                    <span
                      className={`text-[11px] font-medium ${
                        (indexHist.change_pct ?? 0) >= 0 ? "text-green-400" : "text-red-400"
                      }`}
                    >
                      {(indexHist.change_pct ?? 0) >= 0 ? "+" : ""}
                      {indexHist.change_pct?.toFixed(2)}%
                    </span>
                  </span>
                )}
              </div>
              <KLineChart history={chartHistory} height={200} />
            </div>
          )}

          {/* 关键点位 */}
          {data.summary.key_levels && (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {Object.entries(safeObj<Record<string, string | number>>(data.summary.key_levels, {})).map(([k, v]) => (
                <div key={k} className="rounded-lg bg-slate-800/50 px-2 py-1.5 text-center">
                  <div className="text-[11px] text-slate-500">{k}</div>
                  <div className="text-sm font-semibold text-slate-200">{v ?? "-"}</div>
                </div>
              ))}
            </div>
          )}

          {/* 研判 */}
          <p className="text-sm leading-relaxed text-slate-300">{data.summary.summary ?? ""}</p>

          {/* 驱动因素 */}
          {data.summary.drivers && data.summary.drivers.length > 0 && (
            <div>
              <div className="mb-1 text-xs font-semibold text-slate-400">关键因素</div>
              <ul className="list-disc pl-4 text-xs text-slate-300 space-y-0.5">
                {safeArray<string>(data.summary.drivers).map((d, i) => (
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

      {/* 准确率统计 */}
      {stats && (stats.total > 0 || (stats.by_direction && Object.keys(stats.by_direction).length > 0)) && (
        <div className="mt-4 border-t border-slate-800 pt-3">
          <div className="mb-2 text-xs font-semibold text-slate-400">预测准确率</div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <div className="rounded-lg bg-slate-800/50 px-3 py-2 text-center">
              <div className="text-lg font-bold text-slate-200">{stats.total}</div>
              <div className="text-[11px] text-slate-500">已记录</div>
            </div>
            <div className="rounded-lg bg-slate-800/50 px-3 py-2 text-center">
              <div className="text-lg font-bold text-slate-200">{stats.settled}</div>
              <div className="text-[11px] text-slate-500">已结算</div>
            </div>
            <div className="rounded-lg bg-slate-800/50 px-3 py-2 text-center">
              <div className="text-lg font-bold text-slate-200">{stats.hit}</div>
              <div className="text-[11px] text-slate-500">命中</div>
            </div>
            <div className="rounded-lg bg-slate-800/50 px-3 py-2 text-center">
              <div className={`text-lg font-bold ${stats.hit_rate != null && stats.hit_rate >= 50 ? "text-green-400" : stats.hit_rate != null && stats.hit_rate < 50 ? "text-red-400" : "text-slate-200"}`}>
                {stats.hit_rate != null ? `${stats.hit_rate}%` : "-"}
              </div>
              <div className="text-[11px] text-slate-500">命中率</div>
            </div>
          </div>
          {Object.entries(stats.by_direction).length > 0 && (
            <div className="mt-2 flex flex-wrap gap-2 text-[11px]">
              {Object.entries(stats.by_direction).map(([d, b]) => (
                <span key={d} className="rounded bg-slate-800/60 px-2 py-1 text-slate-400">
                  {d} {b.hit}/{b.total}（{b.hit_rate ?? "-"}%）
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 历史预测记录 */}
      {safeArray(history).length > 0 && (
        <div className="mt-4 border-t border-slate-800 pt-3">
          <div className="mb-2 text-xs font-semibold text-slate-400">历史预测</div>
          <div className="max-h-64 overflow-y-auto rounded-lg border border-slate-800">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-slate-900 text-left text-xs text-slate-400">
                <tr>
                  <th className="px-2 py-1.5">时间</th>
                  <th className="px-2 py-1.5">预测</th>
                  <th className="px-2 py-1.5 text-right">实际</th>
                  <th className="px-2 py-1.5 text-center">结果</th>
                </tr>
              </thead>
              <tbody>
                {history.map((r) => (
                  <tr key={r.id} className="border-t border-slate-800/60">
                    <td className="px-2 py-1.5 text-[11px] text-slate-500">{fmtDate(r.created_at)}</td>
                    <td className="px-2 py-1.5">
                      <span className={`text-xs font-medium ${directionColor(r.direction_raw || r.direction)}`}>
                        {r.direction_raw || r.direction || "-"}
                      </span>
                    </td>
                    <td className="px-2 py-1.5 text-right text-xs">
                      {r.actual_direction ? (
                        <span className={r.actual_change != null && r.actual_change >= 0 ? "text-green-400" : "text-red-400"}>
                          {r.actual_direction} {r.actual_change != null ? `${r.actual_change > 0 ? "+" : ""}${r.actual_change}%` : ""}
                        </span>
                      ) : (
                        <span className="text-slate-600">待结算</span>
                      )}
                    </td>
                    <td className="px-2 py-1.5 text-center">
                      {r.hit != null ? (
                        <span className={`rounded px-1.5 py-0.5 text-[11px] ${hitColor(r.hit)}`}>
                          {r.hit ? "命中" : "未中"}
                        </span>
                      ) : (
                        <span className="text-slate-600">-</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </CollapsiblePanel>
  );
}
