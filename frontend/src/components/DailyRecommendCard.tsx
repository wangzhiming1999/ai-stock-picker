import { useCallback, useEffect, useState } from "react";
import { CalendarDays, Eye, ShieldCheck } from "lucide-react";
import { fetchDailyRecommend } from "../api/client";
import { fmtDate, fmtDayLabel, isTodayCN } from "../lib/dates";
import CollapsiblePanel from "./CollapsiblePanel";
import WatchStar from "./WatchStar";
import type { DailyRecommendResult } from "../types";
import { pnlTone } from "../lib/tone";

function plainStatus(status: string): string {
  return status
    .replace("风险收益比不足", "上涨空间暂时不够覆盖下跌风险")
    .replace("策略强度不足", "上涨信号还不够强")
    .replace("等待趋势确认", "还没形成稳定上涨趋势")
    .replace("等待动量确认", "上涨力度还需要确认");
}

interface Props {
  onPick: (codes: string[]) => void;
  /** 折叠态：被外层 CollapsiblePanel 包裹时，不再渲染自身面板头，避免双层标题 */
  collapsed?: boolean;
}

export default function DailyRecommendCard({ onPick, collapsed = false }: Props) {
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

  const actions = data?.recommendations?.length ? (
    <button
      onClick={pickAll}
      className="rounded-lg bg-green-600 px-3 py-1 text-xs font-medium text-white hover:bg-green-500"
    >
      全部去分析 →
    </button>
  ) : null;

  const refreshBtn = (
    <button
      onClick={() => void load(true)}
      disabled={loading}
      className="rounded-lg border border-slate-700 px-3 py-1 text-xs text-slate-400 hover:text-slate-200 disabled:opacity-50"
    >
      {loading ? "生成中..." : "强制刷新"}
    </button>
  );

  const body = (
    <>
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
          <span className="ml-auto rounded bg-slate-900 px-1.5 py-0.5 text-[11px] text-slate-400">
            {data.source === "llm" ? "AI 精选" : data.source === "rule" ? "规则推荐" : "暂无推荐"} · {data.candidates} 个通过
            {data.rejected ? ` · ${data.rejected} 个被风控过滤` : ""}
          </span>
        </div>
      )}

      {!data && !err && <div className="p-3 text-sm text-slate-500">正在扫描全市场并生成 AI 推荐...</div>}

      {data?.message && <div className="rounded-lg bg-slate-800/50 px-3 py-2 text-sm text-slate-400">{data.message}</div>}

      {data?.recommendations?.length ? (
        <div className="space-y-3">
          <div className="rounded-lg border border-emerald-800/40 bg-emerald-500/5 px-3 py-2 text-xs text-emerald-200">
            以下标的已通过基础风控，但仍须满足卡片里的“触发”条件；未触发就不买。
          </div>
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
                  <span className={`text-xs font-medium ${pnlTone(r.change_pct)}`}>
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
              {!!r.tags?.length && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {r.tags.map((tag) => (
                    <span key={tag} className="rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 text-[10px] text-slate-400">
                      {tag}
                    </span>
                  ))}
                </div>
              )}
              {(r.trigger || r.invalidation || r.target) && (
                <div className="mt-2 grid gap-1 rounded-md border border-slate-800 bg-slate-900/70 p-2 text-[11px] sm:grid-cols-3">
                  <div><span className="text-slate-500">触发：</span><span className="text-green-300">{r.trigger || "等待确认"}</span></div>
                  <div><span className="text-slate-500">失效：</span><span className="text-red-300">{r.invalidation || "转弱放弃"}</span></div>
                  <div><span className="text-slate-500">目标：</span><span className="text-slate-300">{r.target || "待确认"}</span></div>
                </div>
              )}
            </div>
          ))}
          </div>
        </div>
      ) : null}

      {data && !data.recommendations.length && !!data.watchlist?.length && (
        <div className="mt-3 space-y-3">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="flex items-center gap-1.5 text-sm font-semibold text-amber-200">
                <Eye className="h-4 w-4" /> 先观察，别急着买
              </div>
              <p className="mt-0.5 text-xs text-slate-500">这些股票接近条件，但现在买入风险仍偏高</p>
            </div>
            <span className="rounded-full border border-amber-800/60 bg-amber-500/10 px-2.5 py-1 text-xs text-amber-300">
              {data.watchlist.length} 只待确认
            </span>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            {data.watchlist.map((item) => (
              <button
                key={item.code}
                type="button"
                onClick={() => onPick([item.code])}
                className="group rounded-lg border border-slate-800 bg-slate-950/50 p-3 text-left transition hover:border-amber-700/70 hover:bg-amber-950/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500"
              >
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <span className="font-medium text-slate-100">{item.name}</span>
                    <span className="ml-1.5 text-xs text-slate-500">{item.code}</span>
                  </div>
                  <span className="text-xs font-semibold text-amber-300">{item.score.toFixed(1)}</span>
                </div>
                <div className="mt-2 flex items-center gap-1.5 text-xs text-slate-400">
                  <ShieldCheck className="h-3.5 w-3.5 text-amber-400" />
                  <span>{plainStatus(item.status)}</span>
                </div>
                <p className="mt-1.5 text-[11px] leading-relaxed text-slate-500 group-hover:text-slate-400">{item.trigger}</p>
              </button>
            ))}
          </div>
        </div>
      )}
    </>
  );

  if (collapsed) {
    return (
      <div className="space-y-3">
        <div className="flex items-center justify-end gap-2">
          {actions}
          {refreshBtn}
        </div>
        {body}
      </div>
    );
  }

  return (
    <CollapsiblePanel
      id="daily_recommend"
      title={data ? `今天有哪些可行动机会 · ${fmtDate(data.date)}` : "今天有哪些可行动机会"}
      subtitle="通过基础风控后仍需等待触发条件，不是看到名单就直接买"
      action={
        <div className="flex items-center gap-2">
          {actions}
          {refreshBtn}
        </div>
      }
    >
      {body}
    </CollapsiblePanel>
  );
}
