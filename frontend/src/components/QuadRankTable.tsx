import { useCallback, useEffect, useState } from "react";
import { fetchQuadRanking } from "../api/client";
import CollapsiblePanel from "./CollapsiblePanel";
import WatchStar from "./WatchStar";
import { safeArray } from "../lib/safe";
import type { QuadRankResult, QuadStock } from "../types";

interface Props {
  onPick: (codes: string[]) => void;
}

/** 分数 chip 颜色：>=7 绿 / 6 档黄 / 5 中性灰 / <5 红橙 */
function chipClass(v: number): string {
  if (v >= 8.5) return "bg-green-500/20 text-green-300";
  if (v >= 7) return "bg-emerald-500/15 text-emerald-300";
  if (v >= 6) return "bg-yellow-500/10 text-yellow-200";
  if (v >= 5) return "bg-slate-500/10 text-slate-400";
  return "bg-orange-500/10 text-orange-300";
}

function fmtScore(v: number | undefined): string {
  return v == null ? "-" : v.toFixed(1);
}

function ScoreCell({ v, title }: { v: number | undefined; title: string }) {
  return (
    <td className="px-2 py-2">
      <span title={title} className={`inline-block min-w-[2.2rem] rounded px-1.5 py-0.5 text-center text-xs font-semibold ${chipClass(v ?? 0)}`}>
        {fmtScore(v)}
      </span>
    </td>
  );
}

export default function QuadRankTable({ onPick }: Props) {
  const [data, setData] = useState<QuadRankResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const load = useCallback(async (force = false) => {
    setLoading(true);
    setErr("");
    try {
      setData(await fetchQuadRanking(force));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const items = safeArray<QuadStock>(data?.items);

  const toggle = (code: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  const pickSelected = () => {
    if (selected.size === 0) return;
    onPick(Array.from(selected));
  };

  return (
    <CollapsiblePanel
      id="quad-rank"
      title="四维牛股榜"
      subtitle={
        data
          ? `基本面·技术面·资金面·消息面俱佳 Top 10 · ${data.date} 收盘 · 考察 ${data.pool_size} 只`
          : "基本面·技术面·资金面·消息面俱佳 Top 10 · 每日更新"
      }
      defaultOpen
      action={
        <div className="flex items-center gap-2">
          {selected.size > 0 && (
            <button
              onClick={pickSelected}
              className="rounded-lg bg-green-600 px-3 py-1 text-xs font-medium text-white hover:bg-green-500"
            >
              勾选 {selected.size} 只去分析 →
            </button>
          )}
          <button
            onClick={() => void load(true)}
            disabled={loading}
            className="rounded-lg border border-slate-700 px-3 py-1 text-xs text-slate-400 hover:text-slate-200 disabled:opacity-50"
          >
            {loading ? "分析中..." : "刷新"}
          </button>
        </div>
      }
    >
      {err && <div className="rounded-lg border border-red-800 bg-red-950/40 px-3 py-2 text-sm text-red-300">{err}</div>}
      {!data && !err && (
        <div className="p-3 text-sm text-slate-500">正在计算四维评分，首次生成约 1~2 分钟，之后整日秒回...</div>
      )}
      {data && items.length === 0 && !err && <div className="p-3 text-sm text-slate-500">今日暂无符合四维条件的标的</div>}

      {data && items.length > 0 && (
        <div>
          <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-500">
            <span>
              候选池 <b className="text-slate-300">{data.pool_size}</b> 只
            </span>
            <span>
              四维全优(各面≥7) <b className={data.strict_count > 0 ? "text-green-400" : "text-slate-400"}>{data.strict_count}</b> 只
            </span>
            <span className="text-slate-600">评分口径：估值+趋势+量能+消息情绪，规则模型每日更新</span>
          </div>

          <div className="max-h-[560px] overflow-auto rounded-lg border border-slate-800">
            <table className="w-full text-sm" style={{ minWidth: 760 }}>
              <thead className="sticky top-0 z-10 bg-slate-900 text-left text-xs text-slate-400">
                <tr>
                  <th className="px-2 py-2"></th>
                  <th className="px-2 py-2">#</th>
                  <th className="px-2 py-2">股票</th>
                  <th className="px-2 py-2 text-right">现价</th>
                  <th className="px-2 py-2 text-center">基本面</th>
                  <th className="px-2 py-2 text-center">技术面</th>
                  <th className="px-2 py-2 text-center">资金面</th>
                  <th className="px-2 py-2 text-center">消息面</th>
                  <th className="px-2 py-2 text-center">综合</th>
                  <th className="px-2 py-2 text-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map((it) => {
                  const isSel = selected.has(it.code);
                  const up = it.change_pct >= 0;
                  return (
                    <tr
                      key={it.code}
                      onClick={() => toggle(it.code)}
                      className={`cursor-pointer border-t border-slate-800/60 transition-colors ${
                        isSel ? "bg-green-900/20" : "hover:bg-slate-800/40"
                      }`}
                    >
                      <td className="px-2 py-2">
                        <input
                          type="checkbox"
                          readOnly
                          checked={isSel}
                          onClick={(e) => e.stopPropagation()}
                          onChange={() => toggle(it.code)}
                          className="accent-green-500"
                        />
                      </td>
                      <td className="px-2 py-2 text-xs text-slate-500">{it.rank}</td>
                      <td className="px-2 py-2">
                        <div className="flex items-center gap-1.5">
                          <span className="font-medium text-slate-100">{it.name}</span>
                          {it.tags.map((t) => (
                            <span
                              key={t}
                              className="rounded bg-purple-900/40 px-1 py-0.5 text-[10px] leading-none text-purple-300"
                            >
                              {t}
                            </span>
                          ))}
                        </div>
                        <div className="text-[11px] text-slate-500">{it.code}</div>
                      </td>
                      <td className="px-2 py-2 text-right">
                        <div className="text-slate-200">{it.price.toFixed(2)}</div>
                        <div className={`text-[11px] ${up ? "text-green-400" : "text-red-400"}`}>
                          {up ? "+" : ""}
                          {it.change_pct.toFixed(2)}%
                        </div>
                      </td>
                      <ScoreCell v={it.scores?.fundamental} title={it.comments?.fundamental} />
                      <ScoreCell v={it.scores?.technical} title={it.comments?.technical} />
                      <ScoreCell v={it.scores?.capital} title={it.comments?.capital} />
                      <ScoreCell v={it.scores?.news} title={it.comments?.news} />
                      <td className="px-2 py-2 text-center">
                        <span className={`text-base font-bold ${it.overall_score >= 7 ? "text-brand" : "text-slate-300"}`}>
                          {it.overall_score.toFixed(1)}
                        </span>
                      </td>
                      <td className="px-2 py-2 text-right" onClick={(e) => e.stopPropagation()}>
                        <WatchStar code={it.code} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </CollapsiblePanel>
  );
}
