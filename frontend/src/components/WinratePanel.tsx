import { useCallback, useEffect, useState } from "react";
import { fetchWinrate } from "../api/client";
import CollapsiblePanel from "./CollapsiblePanel";
import { safeObj } from "../lib/safe";
import type { WinrateStats } from "../types";

function rateColor(rate: number | null | undefined): string {
  if (rate == null) return "text-slate-200";
  if (rate >= 50) return "text-green-400";
  if (rate >= 40) return "text-yellow-400";
  return "text-red-400";
}

export default function WinratePanel() {
  const [data, setData] = useState<WinrateStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setErr("");
    try {
      setData(await fetchWinrate());
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
    <CollapsiblePanel
      id="winrate"
      title="胜率看板"
      subtitle="预测与推荐的实际命中表现 · 每日自动结算"
      action={
        <button onClick={() => void load()} disabled={loading} className="rounded-lg border border-slate-700 px-3 py-1 text-xs text-slate-400 hover:text-slate-200 disabled:opacity-50">
          {loading ? "加载中..." : "刷新"}
        </button>
      }
    >

      {err && <div className="rounded-lg border border-red-800 bg-red-950/40 px-3 py-2 text-sm text-red-300">{err}</div>}
      {!data && !err && <div className="p-3 text-sm text-slate-500">加载中...</div>}

      {data && (
        <div className="space-y-4">
          {/* 数据积累徽标：让用户看见闭环在跑 */}
          {(data.prediction?.total ?? 0) + (data.recommendation?.total ?? 0) > 0 ? (
            <div className="flex items-center gap-2 rounded-lg border border-green-800/40 bg-green-500/5 px-3 py-2 text-xs text-green-300">
              <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-green-400" />
              闭环运行中 · 已结算 {data.prediction?.total ?? 0} 次预测 + {data.recommendation?.total ?? 0} 只推荐
            </div>
          ) : (
            <div className="rounded-lg border border-slate-700 bg-slate-800/40 px-3 py-2 text-xs text-slate-400">
              闭环待启动 · 首次结算将在今日收盘后自动执行
            </div>
          )}

          {/* 大盘预测胜率 */}
          <div>
            <div className="mb-1.5 text-xs font-semibold text-slate-400">大盘推衍命中率</div>
            {data.prediction && data.prediction.total > 0 ? (
              <div className="grid grid-cols-3 gap-2">
                <div className="rounded-lg bg-slate-800/50 px-3 py-2 text-center">
                  <div className="text-lg font-bold text-slate-200">{data.prediction.total}</div>
                  <div className="text-[11px] text-slate-500">已结算</div>
                </div>
                <div className="rounded-lg bg-slate-800/50 px-3 py-2 text-center">
                  <div className="text-lg font-bold text-slate-200">{data.prediction.hit}</div>
                  <div className="text-[11px] text-slate-500">命中</div>
                </div>
                <div className="rounded-lg bg-slate-800/50 px-3 py-2 text-center">
                  <div className={`text-lg font-bold ${rateColor(data.prediction.hit_rate)}`}>
                    {data.prediction.hit_rate != null ? `${data.prediction.hit_rate}%` : "-"}
                  </div>
                  <div className="text-[11px] text-slate-500">命中率</div>
                </div>
              </div>
            ) : (
              <div className="rounded-lg bg-slate-800/40 px-3 py-2 text-xs text-slate-500">
                暂无数据 · 每日收盘后自动结算（今日收盘后回来看第一批结果）
              </div>
            )}
            {data.prediction && Object.keys(data.prediction.by_direction || {}).length > 0 && (
              <div className="mt-2 flex flex-wrap gap-2 text-[11px]">
                {Object.entries(safeObj<Record<string, { hit?: number; total?: number; hit_rate?: number }>>(data.prediction.by_direction, {})).map(([d, b]) => (
                  <span key={d} className="rounded bg-slate-800/60 px-2 py-1 text-slate-400">
                    {d} {b.hit}/{b.total}（{b.hit_rate ?? "-"}%）
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* 个股推荐胜率 */}
          <div>
            <div className="mb-1.5 text-xs font-semibold text-slate-400">每日推荐次日胜率</div>
            {data.recommendation && data.recommendation.total > 0 ? (
              <div className="grid grid-cols-3 gap-2">
                <div className="rounded-lg bg-slate-800/50 px-3 py-2 text-center">
                  <div className="text-lg font-bold text-slate-200">{data.recommendation.total}</div>
                  <div className="text-[11px] text-slate-500">已结算</div>
                </div>
                <div className="rounded-lg bg-slate-800/50 px-3 py-2 text-center">
                  <div className="text-lg font-bold text-slate-200">{data.recommendation.hit}</div>
                  <div className="text-[11px] text-slate-500">次日上涨</div>
                </div>
                <div className="rounded-lg bg-slate-800/50 px-3 py-2 text-center">
                  <div className={`text-lg font-bold ${rateColor(data.recommendation.hit_rate)}`}>
                    {data.recommendation.hit_rate != null ? `${data.recommendation.hit_rate}%` : "-"}
                  </div>
                  <div className="text-[11px] text-slate-500">次日胜率</div>
                </div>
              </div>
            ) : (
              <div className="rounded-lg bg-slate-800/40 px-3 py-2 text-xs text-slate-500">
                暂无数据 · 每日收盘后自动结算（推荐生成后次日判定涨跌）
              </div>
            )}
          </div>

          <p className="text-[11px] text-slate-600">
            数据由每日收盘后的定时任务自动结算。数据积累越多，胜率越有参考价值。
          </p>
        </div>
      )}
    </CollapsiblePanel>
  );
}
