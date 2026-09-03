import { useCallback, useEffect, useRef, useState } from "react";
import { Plus, RefreshCw, Trash2 } from "lucide-react";
import { fetchMonitor } from "../api/client";
import CollapsiblePanel from "./CollapsiblePanel";
import type { MonitorResult, MonitorStock } from "../types";

const LS_KEY = "ai:monitorCodes";
const POLL_MS = 5 * 60 * 1000; // 5 分钟
const MAX_CODES = 20;

function loadSaved(): string[] {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    return Array.isArray(arr)
      ? arr.filter((x) => typeof x === "string" && /^\d{6}$/.test(x)).slice(0, MAX_CODES)
      : [];
  } catch {
    return [];
  }
}

/** 指令色调 */
const toneClass: Record<string, string> = {
  danger: "border-red-800/70 bg-red-950/50 text-red-300",
  warn: "border-amber-800/60 bg-amber-950/40 text-amber-300",
  good: "border-green-800/60 bg-green-950/40 text-green-300",
  neutral: "border-slate-700 bg-slate-800/60 text-slate-300",
};

const toneDot: Record<string, string> = {
  danger: "bg-red-400",
  warn: "bg-amber-400",
  good: "bg-green-400",
  neutral: "bg-slate-500",
};

function fmtTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "-";
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;
}

function num(v: number | undefined | null, digits = 2): string {
  return v == null || Number.isNaN(v) ? "-" : v.toFixed(digits);
}

export default function MonitorPanel() {
  const [codes, setCodes] = useState<string[]>(loadSaved);
  const [input, setInput] = useState("");
  const [data, setData] = useState<MonitorResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const busyRef = useRef(false);

  const persist = (arr: string[]) => {
    setCodes(arr);
    try {
      localStorage.setItem(LS_KEY, JSON.stringify(arr));
    } catch {
      /* ignore */
    }
  };

  const refresh = useCallback(
    async (silent = false) => {
      if (codes.length === 0) return;
      if (busyRef.current) return;
      busyRef.current = true;
      if (!silent) setLoading(true);
      setErr("");
      try {
        setData(await fetchMonitor(codes));
      } catch (e) {
        if (!silent) setErr((e as Error).message);
      } finally {
        busyRef.current = false;
        setLoading(false);
      }
    },
    [codes]
  );

  const codesKey = codes.join(",");

  // 名单变化 → 立即刷新
  useEffect(() => {
    if (codes.length === 0) {
      setData(null);
      return;
    }
    void refresh(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [codesKey]);

  // 5 分钟轮询 + 切回页面时立即刷新（页面隐藏时不发请求）
  useEffect(() => {
    if (codes.length === 0) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh(true);
    }, POLL_MS);
    const onVis = () => {
      if (document.visibilityState === "visible") void refresh(true);
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVis);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [codesKey]);

  const addCodes = () => {
    const parsed = input.match(/\d{6}/g) ?? [];
    const uniq = parsed.filter((c) => !codes.includes(c));
    if (!uniq.length) {
      setErr("未识别到 6 位股票代码");
      return;
    }
    if (codes.length + uniq.length > MAX_CODES) {
      setErr(`最多同时监控 ${MAX_CODES} 只`);
      return;
    }
    persist([...codes, ...uniq].slice(0, MAX_CODES));
    setInput("");
    setErr("");
  };

  const remove = (code: string) => {
    persist(codes.filter((c) => c !== code));
    if (codes.length === 1) setData(null);
  };

  const byCode = new Map<string, MonitorStock>();
  (data?.items ?? []).forEach((it) => byCode.set(it.code, it));

  return (
    <CollapsiblePanel
      id="monitor"
      title="盯盘监控"
      subtitle="自定义名单 · 信号位 + 操作指令 · 5 分钟自动轮询（名单保存在本机）"
      defaultOpen
      action={
        <button
          onClick={() => void refresh()}
          disabled={loading || codes.length === 0}
          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-1 text-xs text-slate-400 hover:text-slate-200 disabled:opacity-50"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          {loading ? "刷新中..." : "立即刷新"}
        </button>
      }
    >
      {/* 添加栏 */}
      <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="flex flex-1 gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addCodes();
              }
            }}
            placeholder="输入股票代码，空格/逗号分隔，如 600519 000858"
            className="flex-1 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:border-brand focus:outline-none"
          />
          <button
            onClick={addCodes}
            className="inline-flex items-center gap-1 rounded-lg bg-slate-800 px-3 py-2 text-sm text-slate-200 hover:bg-slate-700"
          >
            <Plus className="h-4 w-4" /> 添加
          </button>
        </div>
        <span className="text-[11px] text-slate-500">
          {data && (
            <>
              上次更新 <b className="text-slate-300">{fmtTime(data.updated_at)}</b> ·{" "}
            </>
          )}
          每 5 分钟自动轮询 · {codes.length}/{MAX_CODES}
        </span>
      </div>

      {err && <div className="mb-2 rounded-lg border border-red-800 bg-red-950/40 px-3 py-2 text-xs text-red-300">{err}</div>}

      {codes.length === 0 && !data && (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-slate-700 py-8 text-center">
          <p className="text-sm text-slate-300">还没有监控的股票</p>
          <p className="mt-1 max-w-sm text-xs text-slate-500">
            输入你要盯的股票代码，每 5 分钟自动拉最新行情，结合支撑/压力/止损位给出
            「持有观察 / 回踩可买 / 压力减仓 / 止损离场」指令
          </p>
        </div>
      )}

      {codes.length > 0 && (
        <div className="max-h-[520px] overflow-auto rounded-lg border border-slate-800">
          <table className="w-full text-sm" style={{ minWidth: 800 }}>
            <thead className="sticky top-0 z-10 bg-slate-900 text-left text-xs text-slate-400">
              <tr>
                <th className="px-2 py-2">#</th>
                <th className="px-2 py-2">股票</th>
                <th className="px-2 py-2 text-right">现价</th>
                <th className="px-2 py-2 text-right">支撑位</th>
                <th className="px-2 py-2 text-right">压力位</th>
                <th className="px-2 py-2 text-right">止损位</th>
                <th className="px-2 py-2 text-center">信号</th>
                <th className="px-2 py-2">指令</th>
                <th className="px-2 py-2 text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {codes.map((code, idx) => {
                const it = byCode.get(code);
                if (!it) {
                  return (
                    <tr key={code} className="border-t border-slate-800/60">
                      <td className="px-2 py-2 text-xs text-slate-500">{idx + 1}</td>
                      <td className="px-2 py-2">
                        <span className="text-slate-400">{code}</span>
                      </td>
                      <td colSpan={6} className="px-2 py-2 text-xs text-slate-500">
                        {data ? "暂无行情（可能停牌或代码有误）" : "加载中..."}
                      </td>
                      <td className="px-2 py-2 text-right">
                        <button
                          onClick={() => remove(code)}
                          className="rounded p-1 text-slate-600 hover:bg-red-950/40 hover:text-red-400"
                          title="移除"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </td>
                    </tr>
                  );
                }
                const { signal: s, advice: a } = it;
                const up = it.change_pct >= 0;
                return (
                  <tr key={code} className="border-t border-slate-800/60 hover:bg-slate-800/30">
                    <td className="px-2 py-2 text-xs text-slate-500">{idx + 1}</td>
                    <td className="px-2 py-2">
                      <div className="font-medium text-slate-100">{it.name}</div>
                      <div className="text-[11px] text-slate-500">{code}</div>
                    </td>
                    <td className="px-2 py-2 text-right">
                      <div className="text-slate-200">{num(it.price)}</div>
                      <div className={`text-[11px] ${up ? "text-green-400" : "text-red-400"}`}>
                        {up ? "+" : ""}
                        {num(it.change_pct, 2)}%
                      </div>
                    </td>
                    <td className="px-2 py-2 text-right text-slate-300">{num(s?.support)}</td>
                    <td className="px-2 py-2 text-right text-slate-300">{num(s?.resistance)}</td>
                    <td className="px-2 py-2 text-right">
                      <span className="text-red-400/90">{num(s?.stop_loss)}</span>
                    </td>
                    <td className="px-2 py-2 text-center">
                      <span
                        className={`inline-flex min-w-[2rem] items-center justify-center rounded px-1.5 py-0.5 text-xs font-semibold ${
                          (s?.strength ?? 0) >= 7
                            ? "bg-purple-900/50 text-purple-300"
                            : (s?.strength ?? 0) >= 5
                              ? "bg-slate-700/60 text-slate-200"
                              : "bg-slate-800 text-slate-500"
                        }`}
                      >
                        {num(s?.strength, 1)}
                      </span>
                    </td>
                    <td className="px-2 py-2">
                      <span
                        title={a?.hint}
                        className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-medium ${toneClass[a?.tone ?? "neutral"]}`}
                      >
                        <span className={`h-1.5 w-1.5 rounded-full ${toneDot[a?.tone ?? "neutral"]}`} />
                        {a?.label ?? "等待信号"}
                      </span>
                      <div className="mt-0.5 truncate text-[10px] text-slate-500" style={{ maxWidth: 220 }}>
                        {a?.dist ? `支撑距 ${num(a.dist.to_support, 1)}% · 压力距 ${num(a.dist.to_resistance, 1)}%` : " "}
                      </div>
                    </td>
                    <td className="px-2 py-2 text-right">
                      <button
                        onClick={() => remove(code)}
                        className="rounded p-1 text-slate-600 hover:bg-red-950/40 hover:text-red-400"
                        title="移除监控"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <p className="mt-2 text-[10px] text-slate-600">
        信号基于日 K 线布林带/均线/斐波那契回撤自动计算，指令仅供参考，不构成投资建议。数据约 3 秒延迟。
      </p>
    </CollapsiblePanel>
  );
}
