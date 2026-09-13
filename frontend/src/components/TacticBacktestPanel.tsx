import { Fragment, useState } from "react";
import { FlaskConical } from "lucide-react";
import { tacticBacktest } from "../api/client";
import { fmtNum } from "../lib/safe";
import CollapsiblePanel from "./CollapsiblePanel";
import type { TacticBacktestItem, TacticBacktestResult } from "../types";

const HORIZONS = [5, 10, 20];

function statusBadge(item: TacticBacktestItem) {
  if (item.status === "not_backtestable") return { text: "无法回测", cls: "bg-slate-700 text-slate-300" };
  if (item.status === "insufficient_data") return { text: "样本不足", cls: "bg-amber-950/60 text-amber-300" };
  return { text: "已回测", cls: "bg-sky-950/60 text-sky-300" };
}

/** 超额着色：edge 已在后端按方向调整（买入看涨、卖出看跌），正数即形态优于基准 */
function edgeClass(v?: number | null): string {
  if (v == null) return "text-slate-500";
  return v > 0 ? "text-green-400" : v < 0 ? "text-red-400" : "text-slate-400";
}

function signed(v?: number | null, digits = 2): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${fmtNum(v, digits)}`;
}

export default function TacticBacktestPanel() {
  const [horizon, setHorizon] = useState(10);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<TacticBacktestResult | null>(null);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const run = async () => {
    setRunning(true);
    setError("");
    setResult(null);
    setExpanded(new Set());
    try {
      setResult(await tacticBacktest({ horizonDays: horizon, evalBars: 250 }));
    } catch (e) {
      setError((e as Error).message || "形态回测失败");
    } finally {
      setRunning(false);
    }
  };

  const toggle = (key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const items = result?.items ?? [];

  return (
    <CollapsiblePanel
      id="tactic_backtest"
      title="形态回测验证"
      subtitle="walk-forward 检验技巧的真实表现 · 与同区间基准对比，样本不足不给结论"
    >
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="text-xs text-slate-500">持有期</span>
        <div className="inline-flex rounded-lg border border-slate-700 p-0.5">
          {HORIZONS.map((h) => (
            <button
              key={h}
              onClick={() => setHorizon(h)}
              aria-pressed={horizon === h}
              className={`rounded-md px-3 py-1 text-xs transition-colors ${
                horizon === h ? "bg-brand/15 text-brand" : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {h} 日
            </button>
          ))}
        </div>
        <button
          onClick={() => void run()}
          disabled={running}
          className="inline-flex items-center gap-1.5 rounded-lg bg-brand px-4 py-1.5 text-sm font-medium text-white hover:bg-brand-dark disabled:opacity-50"
        >
          <FlaskConical className="h-4 w-4" />
          {running ? "回测中（需十几秒）..." : "运行回测验证"}
        </button>
      </div>

      {running && (
        <div role="status" className="rounded-lg bg-slate-800/50 px-3 py-2 text-sm text-slate-400">
          正在多只票上逐日重放形态判定（walk-forward），多周期共振需要 900+ 根日线，耗时较久...
        </div>
      )}

      {!running && error && (
        <div role="alert" className="rounded-lg border border-red-800 bg-red-950/40 px-3 py-2 text-sm text-red-300">
          {error}
          <button onClick={() => void run()} className="ml-3 cursor-pointer font-medium text-red-200 underline">
            重试
          </button>
        </div>
      )}

      {!running && result && items.length === 0 && (
        <div role="status" className="rounded-lg border border-slate-700 bg-slate-800/40 px-3 py-3 text-sm text-slate-300">
          {result.error || "没有可回测的结果"}
        </div>
      )}

      {!running && items.length > 0 && (
        <>
          <div className="mb-2 text-[11px] text-slate-500">
            股票池 {result?.pool_size} 只 · 每只评估最近 {result?.eval_bars} 个交易日 · 持有期{" "}
            {result?.horizon_days} 个交易日 · 命中去重（同一波行情只计一次）
          </div>
          <div className="overflow-x-auto rounded-lg border border-slate-800">
            <table className="w-full text-sm" style={{ minWidth: 860 }}>
              <caption className="sr-only">形态回测验证结果</caption>
              <thead className="bg-slate-900 text-left text-xs text-slate-400">
                <tr>
                  <th scope="col" className="px-3 py-2">技巧</th>
                  <th scope="col" className="px-3 py-2 text-right">命中/样本</th>
                  <th scope="col" className="px-3 py-2 text-right">胜率</th>
                  <th scope="col" className="px-3 py-2 text-right">基准胜率</th>
                  <th scope="col" className="px-3 py-2 text-right">胜率超额</th>
                  <th scope="col" className="px-3 py-2 text-right">平均收益</th>
                  <th scope="col" className="px-3 py-2 text-right">基准收益</th>
                  <th scope="col" className="px-3 py-2 text-right">收益超额</th>
                  <th scope="col" className="px-3 py-2">状态</th>
                </tr>
              </thead>
              <tbody>
                {items.map((it) => {
                  const badge = statusBadge(it);
                  const measurable = it.status === "ok";
                  return (
                    <Fragment key={it.key}>
                      <tr className="border-t border-slate-800/60">
                        <td className="px-3 py-2">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className="text-slate-200">{it.name}</span>
                            <span
                              className={`rounded px-1.5 py-0.5 text-[10px] ${
                                it.direction === "buy"
                                  ? "bg-green-600/20 text-green-300"
                                  : "bg-red-600/20 text-red-300"
                              }`}
                            >
                              {it.direction === "buy" ? "买点" : "卖点"}
                            </span>
                            {(it.note || (it.by_stock?.length ?? 0) > 0) && (
                              <button
                                onClick={() => toggle(it.key)}
                                aria-expanded={expanded.has(it.key)}
                                className="cursor-pointer text-[11px] text-slate-400 underline hover:text-slate-200"
                              >
                                {expanded.has(it.key) ? "收起" : "明细"}
                              </button>
                            )}
                          </div>
                          {!measurable && it.note && (
                            <div className="mt-0.5 text-[11px] text-slate-500">{it.note}</div>
                          )}
                        </td>
                        <td className="px-3 py-2 text-right text-slate-300">
                          {it.signals} / {it.eval_points}
                        </td>
                        <td className="px-3 py-2 text-right text-slate-200">
                          {it.win_rate == null ? "—" : `${fmtNum(it.win_rate, 1)}%`}
                        </td>
                        <td className="px-3 py-2 text-right text-slate-400">
                          {it.baseline_win_rate == null ? "—" : `${fmtNum(it.baseline_win_rate, 1)}%`}
                        </td>
                        <td className={`px-3 py-2 text-right font-medium ${edgeClass(it.edge_win_rate)}`}>
                          {it.edge_win_rate == null ? "—" : `${signed(it.edge_win_rate, 1)}pt`}
                        </td>
                        <td className="px-3 py-2 text-right text-slate-200">
                          {it.avg_return == null ? "—" : `${signed(it.avg_return)}%`}
                        </td>
                        <td className="px-3 py-2 text-right text-slate-400">
                          {it.baseline_avg_return == null ? "—" : `${signed(it.baseline_avg_return)}%`}
                        </td>
                        <td className={`px-3 py-2 text-right font-medium ${edgeClass(it.edge_return)}`}>
                          {it.edge_return == null ? "—" : `${signed(it.edge_return)}%`}
                        </td>
                        <td className="px-3 py-2">
                          <span className={`rounded px-1.5 py-0.5 text-[10px] ${badge.cls}`}>{badge.text}</span>
                        </td>
                      </tr>
                      {expanded.has(it.key) && (
                        <tr className="border-t border-slate-800/60 bg-slate-900/60">
                          <td colSpan={9} className="px-3 py-2">
                            <div className="space-y-1.5 text-[11px] text-slate-400">
                              {it.win_definition && <div>胜率口径：{it.win_definition}</div>}
                              {it.note && <div>说明：{it.note}</div>}
                              {measurable && (
                                <div>
                                  期间平均最大浮盈 {signed(it.avg_max_gain)}%，平均最大浮亏{" "}
                                  {signed(it.avg_max_drawdown)}%
                                </div>
                              )}
                              {(it.by_stock?.length ?? 0) > 0 && (
                                <div className="flex flex-wrap gap-x-3 gap-y-1">
                                  {it.by_stock!.map((s) => (
                                    <span key={s.code} className="text-slate-500">
                                      {s.code}: {s.signals} 次 / {signed(s.avg_return)}
                                    </span>
                                  ))}
                                </div>
                              )}
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}

      <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
        口径说明：walk-forward 只用「截至当日」的 K 线判定，命中后按当日收盘价入场；胜率按方向定义（买入形态看涨、卖出形态看跌）；
        必须与同区间同持有期的<strong className="text-slate-400">基准</strong>对比才有意义——牛市里任何买入信号胜率都高。
        分时背离需要分钟级历史，当前数据源无法回测；天量见天价的「换手率 &gt;30%」缺历史换手率，回测中按数据缺失处理。
        结果仅为历史统计，不代表未来收益，不构成投资建议。
      </p>
    </CollapsiblePanel>
  );
}
