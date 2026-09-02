import { useCallback, useEffect, useState } from "react";
import { CalendarDays } from "lucide-react";
import { fetchDailyRecommend } from "../api/client";
import { fmtDate, fmtDayLabel, isTodayCN } from "../lib/dates";
import CollapsiblePanel from "./CollapsiblePanel";
import WatchStar from "./WatchStar";
import type { DailyRecommendResult } from "../types";

interface Props {
  onPick: (codes: string[]) => void;
}

export default function DailyRecommendCard({ onPick }: Props) {
  const [data, setData] = useState<DailyRecommendResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());

  const load = useCallback(async (force = false) => {
    setLoading(true);
    setErr("");
    setPicked(new Set());
    try {
      setData(await fetchDailyRecommend(force));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const toggle = (code: string) => {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  const pickAll = () => {
    if (data?.recommendations?.length) {
      onPick(data.recommendations.map((r) => r.code));
    }
  };

  return (
    <CollapsiblePanel
      id="daily_recommend"
      title={data ? `每日收盘推荐 · ${fmtDate(data.date)}` : "每日收盘推荐"}
      subtitle="策略扫描 + AI 精选收盘后下一个交易日值得关注的标的"
      action={
        <div className="flex items-center gap-2">
          {data?.recommendations?.length ? (
            <button onClick={pickAll} className="rounded-lg bg-green-600 px-3 py-1 text-xs font-medium text-white hover:bg-green-500">
              全部去分析 →
            </button>
          ) : null}
          <button
            onClick={() => void load(true)}
            disabled={loading}
            className="rounded-lg border border-slate-700 px-3 py-1 text-xs text-slate-400 hover:text-slate-200 disabled:opacity-50"
          >
            {loading ? "生成中..." : "强制刷新"}
          </button>
        </div>
      }
    >
      {err && <div className="rounded-lg border border-red-800 bg-red-950/40 px-3 py-2 text-sm text-red-300">{err}</div>}

      {data?.date && (
        <div className="mb-3 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md border border-slate-800 bg-slate-800/40 px-3 py-2 text-xs text-slate-400">
          <CalendarDays className="h-3.5 w-3.5 shrink-0 text-slate-500" />
          <span>
            数据截至 <span className="font-medium text-slate-200">{fmtDayLabel(data.date)}</span> 收盘
            {data.target_date && (
              <>
                <span className="mx-1.5 text-slate-600">→</span>
                目标关注 <span className="font-medium text-amber-300">{fmtDayLabel(data.target_date)}</span>
              </>
            )}
          </span>
          {isTodayCN(data.date) ? (
            <span className="rounded bg-green-500/10 px-1.5 py-0.5 text-[11px] text-green-400">当日收盘</span>
          ) : (
            <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-[11px] text-amber-400">最近交易日</span>
          )}
        </div>
      )}

      {!data && !err && <div className="p-3 text-sm text-slate-500">正在扫描全市场并生成 AI 推荐...</div>}

      {data?.message && <div className="rounded-lg bg-slate-800/50 px-3 py-2 text-sm text-slate-400">{data.message}</div>}

      {data?.recommendations?.length ? (
        <div className="max-h-[480px] space-y-2 overflow-y-auto pr-1">
          {data.recommendations.map((r, idx) => (
            <div
              key={r.code}
              onClick={() => toggle(r.code)}
              className={`cursor-pointer rounded-lg border p-3 transition-colors ${
                picked.has(r.code) ? "border-brand bg-brand/10" : "border-slate-800 hover:border-slate-600"
              }`}
            >
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-2">
                  <span className="flex h-5 w-5 items-center justify-center rounded bg-slate-800 text-[11px] font-bold text-slate-400">
                    {idx + 1}
                  </span>
                  <span className="text-sm font-medium text-white">{r.name}</span>
                  <span className="text-xs text-slate-500">{r.code}</span>
                  <span className={`text-xs font-medium ${r.change_pct >= 0 ? "text-green-400" : "text-red-400"}`}>
                    {r.change_pct >= 0 ? "+" : ""}
                    {r.change_pct.toFixed(2)}%
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-slate-500">{r.price.toFixed(2)}</span>
                  <span className="rounded bg-amber-900/40 px-1.5 py-0.5 text-[11px] font-semibold text-amber-300">
                    置信 {r.confidence.toFixed(1)}
                  </span>
                  {picked.has(r.code) && <span className="text-xs text-brand">✓</span>}
                  <WatchStar code={r.code} />
                </div>
              </div>
              <p className="mt-1.5 text-xs leading-relaxed text-slate-400">{r.reason}</p>
            </div>
          ))}
        </div>
      ) : null}
    </CollapsiblePanel>
  );
}
