import { useCallback, useEffect, useState } from "react";
import { fetchIndustries } from "../api/client";
import CollapsiblePanel from "./CollapsiblePanel";
import DailyBriefing from "./DailyBriefing";
import DailyRecommendCard from "./DailyRecommendCard";
import PredictionCard from "./PredictionCard";
import QuadRankTable from "./QuadRankTable";
import type { Industry } from "../types";

interface Props {
  onPick: (codes: string[]) => void;
}

export default function DiscoverPanel({ onPick }: Props) {
  const [industries, setIndustries] = useState<Industry[]>([]);
  const [indLoading, setIndLoading] = useState(false);
  const [err, setErr] = useState("");

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

  useEffect(() => {
    void loadIndustries();
  }, [loadIndustries]);

  return (
    <div className="space-y-5">
      <DailyBriefing onPick={onPick} />

      <QuadRankTable onPick={onPick} />

      <CollapsiblePanel
        id="daily-recommend-detail"
        title="每日推荐明细"
        subtitle="早盘关注池完整版 · 与上方简报同源，展开看全量推荐"
        defaultOpen={false}
      >
        <DailyRecommendCard onPick={onPick} collapsed />
      </CollapsiblePanel>

      <CollapsiblePanel
        id="prediction-detail"
        title="大盘推衍详情"
        subtitle="含指数走势图与推衍逻辑 · 展开看完整分析"
        defaultOpen={false}
      >
        <PredictionCard />
      </CollapsiblePanel>

      <CollapsiblePanel
        id="industry"
        title="行业板块热榜"
        subtitle="新浪行业板块 · 涨跌幅排序，识别当前热点方向"
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
        <div className="max-h-80 overflow-y-auto rounded-lg border border-slate-800">
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
                    <td className={`px-3 py-1.5 text-right ${ind.change_pct >= 0 ? "text-green-400" : "text-red-400"}`}>
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
