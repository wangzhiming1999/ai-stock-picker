import { lazy, Suspense, useCallback, useState } from "react";
import { Radar } from "lucide-react";
import { fetchIndustries } from "../api/client";
import CollapsiblePanel from "./CollapsiblePanel";
import DailyRecommendCard from "./DailyRecommendCard";
import PanelSkeleton from "./PanelSkeleton";
import type { Industry } from "../types";
import { pnlTone } from "../lib/tone";
import Button from "./Button";

const PredictionCard = lazy(() => import("./PredictionCard"));
const QuadRankTable = lazy(() => import("./QuadRankTable"));

interface Props {
  onPick: (codes: string[]) => void;
}

/**
 * 选机会 · 推荐 tab
 *
 * 回答「今天有哪些票值得看」。原 DiscoverPanel 把「作战简报」也混在这里，
 * 但简报属于「今天怎么操作」（今日作战），推荐才属于「买什么」（选机会），
 * 两者任务不同，已拆开。
 */
export default function RecommendPanel({ onPick }: Props) {
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

  return (
    <div className="space-y-5">
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

      <div className="flex items-center gap-2 pt-1 text-sm font-semibold text-ink-soft">
        <Radar className="h-4 w-4 text-brand-light" aria-hidden /> 想继续找机会？
        <span className="text-xs font-normal text-ink-faint">下面是模型筛出的备选股票，可进一步分析，但不等于建议买入</span>
      </div>

      <Suspense fallback={<PanelSkeleton label="正在加载候选验证区" />}>
        <QuadRankTable onPick={onPick} />
      </Suspense>

      <CollapsiblePanel
        id="industry"
        title="行业板块热榜"
        subtitle="新浪行业板块 · 涨跌幅排序，识别当前热点方向"
        defaultOpen={false}
        onToggle={(open) => {
          if (open && industries.length === 0 && !indLoading) void loadIndustries();
        }}
        action={
          <Button variant="outlineQuiet" size="sm"
            onClick={() => void loadIndustries()}
            disabled={indLoading}
            >
            {indLoading ? "加载中..." : "刷新"}
          </Button>
        }
      >
        <div className="max-h-80 overflow-y-auto rounded-xl border border-slate-800">
          {err && <div className="p-3 text-xs text-red-300">{err}</div>}
          {!indLoading && industries.length === 0 && !err && (
            <div className="p-4 text-sm text-ink-faint">暂无数据，点击"刷新"重试</div>
          )}
          {industries.length > 0 && (
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-slate-900 text-left text-xs text-ink-muted">
                <tr>
                  <th scope="col" className="px-3 py-2">板块</th>
                  <th scope="col" className="px-3 py-2 text-right">家数</th>
                  <th scope="col" className="px-3 py-2 text-right">涨跌幅</th>
                  <th scope="col" className="px-3 py-2 text-right">平均价</th>
                </tr>
              </thead>
              <tbody>
                {industries.map((ind) => (
                  <tr key={ind.label} className="border-t border-slate-800/60 hover:bg-slate-800/40">
                    <td className="px-3 py-2 text-ink">{ind.name}</td>
                    <td className="px-3 py-2 text-right text-ink-muted">{ind.company_count}</td>
                    <td className={`px-3 py-1.5 text-right tabular-nums ${pnlTone(ind.change_pct)}`}>
                      {ind.change_pct >= 0 ? "+" : ""}
                      {ind.change_pct.toFixed(2)}%
                    </td>
                    <td className="px-3 py-2 text-right text-ink-muted tabular-nums">{ind.avg_price.toFixed(2)}</td>
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
