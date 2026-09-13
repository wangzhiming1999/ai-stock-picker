import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { BarChart3, X } from "lucide-react";
import { toast } from "sonner";
import { fetchStock, streamAnalysis } from "../api/client";
import StockCard from "./StockCard";
import StockSearchInput from "./StockSearchInput";
import { cardItem, stagger } from "../lib/motion";
import type { StockAnalysis, StockInfo, SSEEvent } from "../types";

type Phase = "idle" | "running" | "done" | "error";

interface AnalysisItem {
  analysis: StockAnalysis;
  info?: StockInfo;
}

interface Props {
  open: boolean;
  /** 外部请求分析的股票代码；变化时自动开始分析 */
  codes: string[] | null;
  /** 每次外部请求自增，用于区分「同一批代码再次请求分析」 */
  requestId: number;
  onClose: () => void;
  /** 一批分析结果落库后触发，用于刷新历史记录列表 */
  onBatchSaved?: () => void;
}

function parseCodesFromText(text: string): string[] {
  return text
    .split(/[\s,，;；、]+/)
    .map((s) => s.trim())
    .filter((s) => /^\d{6}$/.test(s));
}

/**
 * 深度分析 · 全局抽屉
 *
 * 为什么是抽屉而不是一级 tab：分析永远是流程「终点」——用户从今日作战或选机会里
 * 勾了几只票，下一步就是看分析结果。给它一个独立 tab，等于让用户走完流程后再
 * 自己导航到另一个地方，把一气呵成的动作切断了。
 *
 * 抽屉自带完整分析状态机（流式 SSE + 中止），所以 App 不需要再持有分析状态。
 */
export default function AnalysisDrawer({ open, codes, requestId, onClose, onBatchSaved }: Props) {
  const [input, setInput] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [status, setStatus] = useState("");
  const [items, setItems] = useState<AnalysisItem[]>([]);
  const [currentCode, setCurrentCode] = useState("");
  const [errorMsg, setErrorMsg] = useState("");
  const [infos, setInfos] = useState<Record<string, StockInfo>>({});

  const abortRef = useRef<AbortController | null>(null);
  // 用 ref 持有回调，避免它进入 run 的依赖导致每次渲染都重建分析函数
  const batchSavedRef = useRef(onBatchSaved);
  batchSavedRef.current = onBatchSaved;

  const run = useCallback(async (raw: string) => {
    const list = parseCodesFromText(raw);
    if (list.length === 0) {
      setErrorMsg("请输入有效的 6 位股票代码，多个用逗号分隔，例如：600519, 000858, 300750");
      return;
    }

    setPhase("running");
    setErrorMsg("");
    setItems([]);
    setStatus("正在准备...");
    setInfos({});

    abortRef.current?.abort();
    abortRef.current = new AbortController();
    const signal = abortRef.current.signal;

    const infoTask = Promise.all(list.map((code) => fetchStock(code).catch(() => undefined))).then((results) => {
      const map: Record<string, StockInfo> = {};
      for (const info of results) {
        if (info) map[info.code] = info;
      }
      setInfos(map);
    });

    const handleEvent = (e: SSEEvent) => {
      switch (e.type) {
        case "status":
          setStatus(e.message);
          break;
        case "stock_start":
          setCurrentCode(e.payload?.code ?? "");
          setStatus(e.message);
          break;
        case "delta":
          break;
        case "stock_done": {
          const result = e.payload?.result;
          if (result) {
            setItems((prev) => [...prev, { analysis: result }]);
            setStatus(e.message);
          }
          break;
        }
        case "stock_error":
          setStatus(e.message);
          break;
        case "batch_saved":
          batchSavedRef.current?.();
          break;
        case "done":
          setPhase("done");
          setStatus(e.message);
          toast.success("分析完成", { description: e.message });
          break;
        case "error":
          setPhase("error");
          setErrorMsg(e.message);
          toast.error("分析失败", { description: e.message });
          break;
      }
    };

    try {
      await Promise.all([infoTask, streamAnalysis(list, handleEvent, signal, true)]);
      setPhase((p) => (p === "running" ? "done" : p));
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        const msg = (err as Error).message || "分析失败，请检查后端服务是否启动、API Key 是否配置";
        setPhase("error");
        setErrorMsg(msg);
        toast.error("分析失败", { description: msg });
      }
    }
  }, []);

  // 外部请求分析（从别的页面勾选股票进来）：requestId 变化即触发
  useEffect(() => {
    if (!open || !codes || codes.length === 0) return;
    const joined = codes.join(", ");
    setInput(joined);
    void run(joined);
    // codes 与 requestId 同步变化，用 requestId 作触发键即可
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, requestId, run]);

  const stop = () => {
    abortRef.current?.abort();
    setPhase("idle");
    setStatus("已手动停止");
  };

  // 打开时锁背景滚动 + Ctrl/Cmd+Enter 重新分析 + Esc 关闭
  useEffect(() => {
    if (!open) return;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && phase !== "running") {
        e.preventDefault();
        void run(input);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prevOverflow;
      window.removeEventListener("keydown", onKey);
    };
  }, [open, phase, input, run, onClose]);

  const avgScore = items.length
    ? items.reduce((s, i) => s + i.analysis.overall_score, 0) / items.length
    : 0;
  const totalScore = items.reduce((s, i) => s + Math.max(i.analysis.overall_score, 0), 0) || 1;

  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true" aria-label="深度分析">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="absolute inset-0 bg-slate-950/70 backdrop-blur-sm"
          />

          <motion.aside
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", stiffness: 380, damping: 36 }}
            className="relative flex h-full w-full max-w-3xl flex-col border-l border-slate-800 bg-slate-950 shadow-2xl"
          >
            {/* 抽屉头 */}
            <div className="flex items-center justify-between gap-3 border-b border-slate-800 px-4 py-3 sm:px-6">
              <div className="flex items-center gap-2">
                <BarChart3 className="h-4 w-4 text-brand-light" />
                <h2 className="text-sm font-semibold text-white">深度分析</h2>
                <span className="hidden text-xs text-ink-faint sm:inline">AI 综合行情、K线趋势与最新新闻</span>
              </div>
              <button
                onClick={onClose}
                aria-label="关闭"
                className="rounded-lg p-1.5 text-ink-muted hover:bg-slate-800 hover:text-white"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto px-4 py-4 sm:px-6">
              {/* 输入区 */}
              <div className="rounded-2xl border border-slate-800 bg-slate-900 p-4">
                <label className="mb-2 block text-sm font-medium text-ink-soft">
                  股票搜索 <span className="ml-1 text-xs font-normal text-ink-faint">（代码/名称 · 支持多只）</span>
                </label>
                <div className="flex flex-col gap-3 sm:flex-row">
                  <StockSearchInput
                    value={input}
                    onChange={setInput}
                    onPickCode={(code) => {
                      setInput((prev) => {
                        const existing = parseCodesFromText(prev);
                        if (existing.includes(code)) return prev;
                        return [...existing, code].join(", ");
                      });
                    }}
                    disabled={phase === "running"}
                  />
                  {phase === "running" ? (
                    <button
                      onClick={stop}
                      className="rounded-lg border border-slate-600 bg-slate-800 px-6 py-2.5 text-sm font-medium text-ink hover:bg-slate-700"
                    >
                      停止
                    </button>
                  ) : (
                    <button
                      onClick={() => void run(input)}
                      className="rounded-lg bg-brand px-6 py-2.5 text-sm font-medium text-white hover:bg-brand-dark disabled:opacity-50"
                    >
                      开始分析
                    </button>
                  )}
                </div>
                <p className="mt-2 text-xs text-ink-faint">提示：支持 Ctrl + Enter 快捷触发；Esc 关闭</p>
              </div>

              {/* 状态 */}
              {(phase === "running" || phase === "done") && status && (
                <div className="mt-4 flex items-center gap-2 rounded-xl border border-slate-800 bg-slate-900 px-4 py-3 text-sm text-ink-soft">
                  {phase === "running" ? (
                    <>
                      <span className="relative flex h-2.5 w-2.5">
                        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand-light opacity-75" />
                        <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-brand" />
                      </span>
                      <span>{status}</span>
                      {currentCode && <span className="ml-2 text-xs text-ink-faint">({currentCode})</span>}
                    </>
                  ) : (
                    <span className="text-brand-light">✓ {status}</span>
                  )}
                </div>
              )}

              {/* 错误 */}
              {phase === "error" && errorMsg && (
                <div className="mt-4 rounded-lg border border-red-800 bg-red-950/40 px-4 py-3 text-sm text-red-300">
                  {errorMsg}
                </div>
              )}

              {/* 结果 */}
              {items.length > 0 && (
                <div className="mt-6">
                  <div className="mb-3 flex items-center justify-between">
                    <h3 className="text-base font-semibold text-white">分析结果</h3>
                    <div className="flex items-center gap-2 text-sm">
                      <span className="text-ink-muted">平均分</span>
                      <span className="text-lg font-bold text-brand-light tabular-nums">{avgScore.toFixed(1)}</span>
                    </div>
                  </div>
                  <div className="mb-5 flex h-7 w-full overflow-hidden rounded-xl border border-slate-800 bg-slate-900">
                    {items.map((item, idx) => (
                      <div
                        key={item.analysis.code + idx}
                        className="flex items-center justify-center overflow-hidden border-r border-slate-900 text-xs font-medium text-white/90 last:border-r-0"
                        style={{
                          width: `${(Math.max(item.analysis.overall_score, 0) / totalScore) * 100}%`,
                          background: "linear-gradient(to top, rgba(37,99,235,0.85), rgba(37,99,235,0.45))",
                        }}
                        title={`${item.analysis.name} ${item.analysis.overall_score.toFixed(1)}`}
                      >
                        {item.analysis.name}
                      </div>
                    ))}
                  </div>
                  <motion.div
                    className="grid gap-5"
                    variants={stagger}
                    initial="hidden"
                    animate="visible"
                    key={items.length}
                  >
                    {items.map((item, idx) => (
                      <motion.div key={item.analysis.code + idx} variants={cardItem}>
                        <StockCard analysis={item.analysis} info={infos[item.analysis.code]} />
                      </motion.div>
                    ))}
                  </motion.div>
                </div>
              )}

              {/* 空状态 */}
              {phase === "idle" && items.length === 0 && (
                <div className="mt-10 text-center">
                  <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl border border-slate-800 bg-slate-900">
                    <BarChart3 className="h-7 w-7 text-brand-light" />
                  </div>
                  <p className="mt-3 text-sm text-ink-faint">
                    输入 A 股代码，AI 将综合行情、K线趋势与最新新闻给出选股评分
                  </p>
                </div>
              )}
            </div>
          </motion.aside>
        </div>
      )}
    </AnimatePresence>
  );
}
