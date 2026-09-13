import { lazy, Suspense, useCallback, useState } from "react";
import { Radar } from "lucide-react";
import { fetchIndustries } from "../api/client";
import CollapsiblePanel from "./CollapsiblePanel";
import DailyBriefing from "./DailyBriefing";
import DailyRecommendCard from "./DailyRecommendCard";
import type { Industry } from "../types";
import { pnlTone } from "../lib/tone";

const PredictionCard = lazy(() => import("./PredictionCard"));
const QuadRankTable = lazy(() => import("./QuadRankTable"));

interface Props {
  onPick: (codes: string[]) => void;
}

export default function DiscoverPanel({ onPick }: Props) {
  const [industries, setIndustries] = useState<Industry[]>([]);
  const [indLoading, setIndLoading] = useState(false);
  const [err, setErr] = useState("");
  const [detailsReady, setDetailsReady] = useState(false);
  const handleBriefingSettled = useCallback(() => setDetailsReady(true), []);

  const loadIndustries = useCallback(async () => {
    setIndLoading(true);
    setErr("");
    try {
      setIndustries(await fetchIndustries());
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setIndLoading(false);
    }
  }, []);

  return (
    <div className="space-y-5">
      <DailyBriefing onPick={onPick} onSettled={handleBriefingSettled} />

      {detailsReady ? (
        <div className="grid gap-5 xl:grid-cols-[1.05fr_0.95fr]">
          <div className="min-w-0">
            <DailyRecommendCard onPick={onPick} />
          </div>
          <div className="min-w-0">
            <Suspense fallback={<PanelSkeleton label="正在加载大盘推演" />}>
              <PredictionCard />
            </Suspense>
          </div>
        </div>
      ) : (
        <PanelSkeleton label="正在整理今日机会与大盘推演" />
      )}

      <div className="flex items-center gap-2 pt-1 text-sm font-semibold text-slate-300">
        <Radar className="h-4 w-4 text-brand" /> 想继续找机会？
        <span className="text-xs font-normal text-slate-500">下面是模型筛出的备选股票，可进一步分析，但不等于建议买入</span>
      </div>

      {detailsReady && (
        <Suspense fallback={<PanelSkeleton label="正在加载候选验证区" />}>
          <QuadRankTable onPick={onPick} />
        </Suspense>
      )}

      <CollapsiblePanel
        id="industry"
        title="行业板块热榜"
        subtitle="新浪行业板块 · 涨跌幅排序，识别当前热点方向"
        defaultOpen={false}
        onToggle={(open) => {
          if (open && industries.length === 0 && !indLoading) void loadIndustries();
        }}
        action={
          <button
            onClick={() => void loadIndustries()}
            disabled={indLoading}
            className="rounded-lg border border-slate-700 px-3 py-1 text-xs text-slate-400 hover:text-slate-200 disabled:opacity-50"
          >
            {indLoading ? "加载中..." : "刷新"}
          </button>
        }
      >
        <div className="max-h-80 overflow-y-auto rounded-xl border border-slate-800">
          {err && <div className="p-3 text-xs text-red-300">{err}</div>}
          {!indLoading && industries.length === 0 && !err && (
            <div className="p-4 text-sm text-slate-500">暂无数据，点击"刷新"重试</div>
          )}
          {industries.length > 0 && (
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-slate-900 text-left text-xs text-slate-400">
                <tr>
                  <th className="px-3 py-2">板块</th>
                  <th className="px-3 py-2 text-right">家数</th>
                  <th className="px-3 py-2 text-right">涨跌幅</th>
                  <th className="px-3 py-2 text-right">平均价</th>
                </tr>
              </thead>
              <tbody>
                {industries.map((ind) => (
                  <tr key={ind.label} className="border-t border-slate-800/60 hover:bg-slate-800/40">
                    <td className="px-3 py-1.5 text-slate-200">{ind.name}</td>
                    <td className="px-3 py-1.5 text-right text-slate-400">{ind.company_count}</td>
                    <td className={`px-3 py-1.5 text-right ${pnlTone(ind.change_pct)}`}>
                      {ind.change_pct >= 0 ? "+" : ""}
                      {ind.change_pct.toFixed(2)}%
                    </td>
                    <td className="px-3 py-1.5 text-right text-slate-400">{ind.avg_price.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </CollapsiblePanel>
    </div>
  );
}

function PanelSkeleton({ label }: { label: string }) {
  return (
    <div aria-busy="true" aria-label={label} className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
      <div className="h-4 w-32 animate-pulse rounded bg-slate-800" />
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div className="h-24 animate-pulse rounded-lg bg-slate-800/70" />
        <div className="h-24 animate-pulse rounded-lg bg-slate-800/70" />
      </div>
      <span className="sr-only">{label}</span>
    </div>
  );
}
