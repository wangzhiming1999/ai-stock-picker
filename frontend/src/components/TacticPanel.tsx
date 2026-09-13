import { Fragment, useEffect, useMemo, useState } from "react";
import { listTactics, tacticScan } from "../api/client";
import { fmtNum } from "../lib/safe";
import { pnlTone } from "../lib/tone";
import CollapsiblePanel from "./CollapsiblePanel";
import type { TacticDef, TacticResult, TacticScanResult } from "../types";

interface Props {
  onPick: (codes: string[]) => void;
  /** 批量加自选（未登录时由上层弹登录） */
  onImport: (codes: string[]) => void;
}

const DIRECTION_LABEL: Record<TacticDef["direction"], string> = { buy: "买点", sell: "卖点" };

function buttonClass(direction: TacticDef["direction"], active: boolean): string {
  if (direction === "buy") {
    return active ? "border-green-500 bg-green-600/15" : "border-slate-700 hover:border-green-600/70";
  }
  return active ? "border-red-500 bg-red-600/15" : "border-slate-700 hover:border-red-600/70";
}

function DirectionTag({ direction }: { direction: TacticDef["direction"] }) {
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-[11px] ${
        direction === "buy" ? "bg-green-600/20 text-green-300" : "bg-red-600/20 text-red-300"
      }`}
    >
      {DIRECTION_LABEL[direction]}
    </span>
  );
}

export default function TacticPanel({ onPick, onImport }: Props) {
  const [tactics, setTactics] = useState<TacticDef[]>([]);
  const [active, setActive] = useState("all");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<TacticScanResult | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  useEffect(() => {
    let alive = true;
    listTactics()
      .then((items) => {
        if (alive) setTactics(items);
      })
      .catch(() => {
        if (alive) setError("技巧清单加载失败，请稍后重试");
      });
    return () => {
      alive = false;
    };
  }, []);

  const categories = useMemo(() => Array.from(new Set(tactics.map((t) => t.category))), [tactics]);
  const items = result?.items ?? [];

  const run = async (key: string) => {
    setActive(key);
    setRunning(true);
    setError("");
    setResult(null);
    setSelected(new Set());
    setExpanded(new Set());
    try {
      const r = await tacticScan({
        tactic: key === "all" ? undefined : key,
        limit: 20,
        minAmountYi: 3,
        force: true,
      });
      setResult(r);
    } catch (e) {
      setError((e as Error).message || "形态扫描失败");
    } finally {
      setRunning(false);
    }
  };

  const toggle = (code: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  const toggleExpand = (code: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  return (
    <CollapsiblePanel
      id="scan_tactics"
      title="实战形态"
      subtitle="按技巧找买点与卖点 · 全部条件成立才命中，宁缺毋滥"
      action={
        items.length > 0 ? (
          <div className="flex items-center gap-2">
            <button
              onClick={() => onImport(items.map((s) => s.code))}
              className="rounded-lg border border-slate-600 px-3 py-1 text-xs text-slate-300 hover:border-slate-400 hover:text-white"
            >
              全部加自选
            </button>
            <button
              onClick={() => onPick(Array.from(selected))}
              disabled={selected.size === 0}
              className="rounded-lg bg-green-600 px-3 py-1 text-xs font-medium text-white hover:bg-green-500 disabled:opacity-40"
            >
              勾选 {selected.size} 只去分析 →
            </button>
          </div>
        ) : undefined
      }
    >
      <div className="mb-3">
        <button
          onClick={() => void run("all")}
          disabled={running}
          aria-pressed={active === "all"}
          className={`rounded-lg border px-3 py-2 text-left text-sm transition disabled:opacity-60 ${
            active === "all" ? "border-brand bg-brand/10 text-white" : "border-slate-700 text-slate-200 hover:border-slate-500"
          }`}
        >
          全部技巧
          <span className="ml-2 text-[11px] text-slate-500">{tactics.length || 6} 条一起查</span>
        </button>
      </div>

      {categories.map((cat) => (
        <div key={cat} className="mb-3">
          <p className="mb-1 text-[11px] font-semibold tracking-wide text-slate-500">{cat}</p>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {tactics
              .filter((t) => t.category === cat)
              .map((t) => (
                <button
                  key={t.key}
                  onClick={() => void run(t.key)}
                  disabled={running}
                  aria-pressed={active === t.key}
                  className={`rounded-lg border p-3 text-left transition disabled:opacity-60 ${buttonClass(t.direction, active === t.key)}`}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-slate-100">{t.name}</span>
                    <DirectionTag direction={t.direction} />
                  </div>
                  <div className="mt-0.5 text-[11px] text-slate-500">{t.desc}</div>
                </button>
              ))}
          </div>
        </div>
      ))}

      {running && (
        <div role="status" className="rounded-lg bg-slate-800/50 px-3 py-2 text-sm text-slate-400">
          形态扫描中（拉取行情与 K 线；多周期共振需约 900 根日线，耗时更久）...
        </div>
      )}

      {!running && error && (
        <div role="alert" className="rounded-lg border border-red-800 bg-red-950/40 px-3 py-2 text-sm text-red-300">
          {error}
          <button onClick={() => void run(active)} className="ml-3 cursor-pointer font-medium text-red-200 underline">
            重试
          </button>
        </div>
      )}

      {!running && result && items.length === 0 && (
        <div role="status" className="rounded-lg border border-slate-700 bg-slate-800/40 px-3 py-3 text-sm text-slate-300">
          已检查 {result.checked} 只候选，当前没有「全部条件成立」的形态。形态识别宁缺毋滥，未命中属正常。
        </div>
      )}

      {!running && items.length > 0 && (
        <div className="max-h-[28rem] overflow-y-auto rounded-lg border border-slate-800">
          <table className="w-full text-sm">
            <caption className="sr-only">实战形态扫描结果</caption>
            <thead className="sticky top-0 bg-slate-900 text-left text-xs text-slate-400">
              <tr>
                <th scope="col" className="px-3 py-2">勾选</th>
                <th scope="col" className="px-3 py-2">名称</th>
                <th scope="col" className="px-3 py-2">代码</th>
                <th scope="col" className="px-3 py-2 text-right">涨跌幅</th>
                <th scope="col" className="px-3 py-2">命中技巧</th>
                <th scope="col" className="px-3 py-2">操作提示</th>
              </tr>
            </thead>
            <tbody>
              {items.map((s) => (
                <Fragment key={s.code}>
                  <tr
                    onClick={() => toggle(s.code)}
                    className={`cursor-pointer border-t border-slate-800/60 hover:bg-slate-800/40 ${
                      selected.has(s.code) ? "bg-slate-800/70" : ""
                    }`}
                  >
                    <td className="px-3 py-1.5">
                      <input
                        type="checkbox"
                        readOnly
                        checked={selected.has(s.code)}
                        aria-label={`选择 ${s.name}`}
                        className="accent-brand"
                      />
                    </td>
                    <td className="px-3 py-1.5 text-slate-200">{s.name}</td>
                    <td className="px-3 py-1.5 text-slate-500">{s.code}</td>
                    <td
                      className={`px-3 py-1.5 text-right ${pnlTone(s.change_pct)}`}
                    >
                      {(s.change_pct ?? 0) >= 0 ? "+" : ""}
                      {fmtNum(s.change_pct ?? 0)}%
                    </td>
                    <td className="px-3 py-1.5">
                      <div className="flex flex-wrap items-center gap-1">
                        {s.tactics.map((t: TacticResult) => (
                          <span key={t.key} className="rounded bg-slate-800 px-1.5 py-0.5 text-[11px] text-slate-300">
                            {t.name}
                          </span>
                        ))}
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleExpand(s.code);
                          }}
                          aria-expanded={expanded.has(s.code)}
                          className="cursor-pointer text-[11px] text-slate-400 underline hover:text-slate-200"
                        >
                          {expanded.has(s.code) ? "收起条件" : "看条件"}
                        </button>
                      </div>
                    </td>
                    <td className="px-3 py-1.5 text-slate-300">{s.best_action ?? s.tactics[0]?.action}</td>
                  </tr>
                  {expanded.has(s.code) && (
                    <tr className="border-t border-slate-800/60 bg-slate-900/60">
                      <td colSpan={6} className="px-3 py-2">
                        <div className="space-y-2">
                          {s.tactics.map((t: TacticResult) => (
                            <div key={t.key}>
                              <div className="flex items-center gap-2">
                                <span className="text-xs font-semibold text-slate-200">{t.name}</span>
                                <DirectionTag direction={t.direction} />
                                <span className="text-[11px] text-slate-500">
                                  {t.passed}/{t.total} 条件成立
                                </span>
                              </div>
                              <ul className="mt-1 space-y-0.5">
                                {t.conditions.map((cond, i) => (
                                  <li key={i} className="flex items-start gap-2 text-[11px]">
                                    <span className={cond.passed ? "text-green-400" : "text-slate-500"}>
                                      {cond.passed ? "✓" : "✗"}
                                    </span>
                                    <span className="text-slate-300">{cond.name}</span>
                                    <span className="text-slate-500">{cond.detail}</span>
                                  </li>
                                ))}
                              </ul>
                            </div>
                          ))}
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="mt-3 text-[11px] text-slate-500">
        形态由 K 线量价条件确定性推导，标注「算法推导」，不构成投资建议；命中不代表必然上涨，实盘请自行判断。
      </p>
    </CollapsiblePanel>
  );
}
