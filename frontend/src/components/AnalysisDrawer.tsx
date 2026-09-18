import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { BarChart3, PanelRightClose, X } from "lucide-react";
import { toast } from "sonner";
import { fetchStock, streamAnalysis } from "../api/client";
import StockCard from "./StockCard";
import StockSearchInput from "./StockSearchInput";
import { cardItem, stagger } from "../lib/motion";
import type { StockAnalysis, StockInfo, SSEEvent } from "../types";
import Button from "./Button";

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

/** 面板宽度记忆：拖窄过一次就一直是窄的，不用每次重调 */
const WIDTH_KEY = "ai:analysisDrawerWidth";
const DEFAULT_WIDTH = 768;
const MIN_WIDTH = 360;
const MAX_WIDTH = 1200;
/** 主界面至少留出的可见宽度 —— 这是「抽屉不挡事」的硬底线 */
const MIN_MAIN_WIDTH = 260;

function readInitialWidth(): number {
  try {
    const n = Number(localStorage.getItem(WIDTH_KEY));
    if (Number.isFinite(n) && n >= MIN_WIDTH && n <= MAX_WIDTH) return n;
  } catch {
    /* ignore */
  }
  return DEFAULT_WIDTH;
}

/** 当前视口允许的最大宽度：不占满，永远给主界面留一条可点的区域 */
function maxAllowedWidth(): number {
  if (typeof window === "undefined") return MAX_WIDTH;
  return Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, window.innerWidth - MIN_MAIN_WIDTH));
}

function parseCodesFromText(text: string): string[] {
  return text
    .split(/[\s,，;；、]+/)
    .map((s) => s.trim())
    .filter((s) => /^\d{6}$/.test(s));
}

/** 运行中的呼吸点：状态条和折叠胶囊共用，避免两处各写一遍 */
function RunningDot() {
  return (
    <span className="relative flex h-2.5 w-2.5 shrink-0">
      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand-light opacity-75" />
      <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-brand" />
    </span>
  );
}

/**
 * 深度分析 · 全局抽屉（非模态）
 *
 * 为什么是抽屉而不是一级 tab：分析永远是流程「终点」——用户从今日作战或选机会里
 * 勾了几只票，下一步就是看分析结果。给它一个独立 tab，等于让用户走完流程后再
 * 自己导航到另一个地方，把一气呵成的动作切断了。
 *
 * ⚠️ 为什么是**非模态**：一次分析要跑几十秒到几分钟。旧实现是全屏遮罩
 * （`fixed inset-0` + `bg-slate-950/70 backdrop-blur`）加 `body overflow: hidden`，
 * 于是在等待期间整个主界面既点不动也滚不动 —— 用户明明只是想顺便看一眼行情，
 * 却被锁在抽屉里干等。现在改为：无遮罩、不锁滚动、外层 `pointer-events-none`、
 * 面板自身 `pointer-events-auto`，主界面照常可点可滚。
 *
 * 三种「让开」的方式，语义互相独立：
 *   折叠（PanelRightClose / Esc）—— 面板收成右下角胶囊，**分析继续跑**，胶囊实时报进度
 *   关闭（X）                  —— 真的关掉；若正在运行会先中止（避免留在后台空烧 LLM）
 *   停止                       —— 中止但面板留着，方便换一批股票重跑
 *
 * 面板自带完整分析状态机（流式 SSE + 中止），所以 App 不需要再持有分析状态。
 */
export default function AnalysisDrawer({ open, codes, requestId, onClose, onBatchSaved }: Props) {
  const [input, setInput] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [status, setStatus] = useState("");
  const [items, setItems] = useState<AnalysisItem[]>([]);
  /** 本批**请求**的只数，用于「已完成 2/3 只」的进度 —— items 只反映已完成的 */
  const [total, setTotal] = useState(0);
  const [currentCode, setCurrentCode] = useState("");
  const [errorMsg, setErrorMsg] = useState("");
  const [infos, setInfos] = useState<Record<string, StockInfo>>({});
  const [debate, setDebate] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [width, setWidth] = useState(readInitialWidth);

  const abortRef = useRef<AbortController | null>(null);
  const panelRef = useRef<HTMLElement | null>(null);
  // 用 ref 持有回调，避免它进入 run 的依赖导致每次渲染都重建分析函数
  const batchSavedRef = useRef(onBatchSaved);
  batchSavedRef.current = onBatchSaved;
  // 辩论开关同样走 ref：run 的依赖必须保持为空，否则开关一变就会重跑分析
  const debateRef = useRef(debate);
  debateRef.current = debate;
  // 键盘监听要读到最新的 phase / input，但不该因为它们变化就重绑监听
  const phaseRef = useRef(phase);
  phaseRef.current = phase;
  const inputRef = useRef(input);
  inputRef.current = input;
  const widthRef = useRef(width);
  widthRef.current = width;

  const run = useCallback(async (raw: string) => {
    const list = parseCodesFromText(raw);
    if (list.length === 0) {
      setErrorMsg("请输入有效的 6 位股票代码，多个用逗号分隔，例如：600519, 000858, 300750");
      return;
    }

    setPhase("running");
    setErrorMsg("");
    setItems([]);
    setTotal(list.length);
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
        case "debate_start":
        case "debate_done":
        case "trade_plan_start":
        case "trade_plan_done":
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
      await Promise.all([infoTask, streamAnalysis(list, handleEvent, signal, true, debateRef.current)]);
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
    // 新的一批进来一定展开：否则用户点了「分析」却只看到胶囊，会以为没反应
    setCollapsed(false);
    const joined = codes.join(", ");
    setInput(joined);
    void run(joined);
    // codes 与 requestId 同步变化，用 requestId 作触发键即可
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, requestId, run]);

  // 卸载即中止：旧的「关闭」只是把组件摘掉，SSE 还在后台跑，白烧 token
  useEffect(() => () => abortRef.current?.abort(), []);

  const stop = () => {
    abortRef.current?.abort();
    setPhase("idle");
    setStatus("已手动停止");
  };

  /** 关闭 = 真的关掉。运行中先中止，并明说做了什么，不做静默丢结果 */
  const close = () => {
    if (phaseRef.current === "running") {
      abortRef.current?.abort();
      toast.info("已中止分析", { description: "关闭面板会中止正在进行的分析；想留在后台跑请用「收起」" });
    }
    onClose();
  };

  // 快捷键：Ctrl/Cmd+Enter 触发（需焦点在面板内，避免在别处误触）
  //         Esc 在运行中只收起（不中断、不丢结果），空闲时关闭
  //         主界面正在输入框里打字时不响应 Esc —— 非模态之后这是必须的，否则
  //         用户在主搜索框按 Esc 想清空，结果把抽屉关了
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      const el = document.activeElement as HTMLElement | null;
      const typing = !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
      const inPanel = !!(el && panelRef.current?.contains(el));

      if (e.key === "Escape" && (inPanel || !typing)) {
        if (phaseRef.current === "running") setCollapsed(true);
        else close();
        return;
      }
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && inPanel && phaseRef.current !== "running") {
        e.preventDefault();
        void run(inputRef.current);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // close 每帧重建无所谓，监听器本身不依赖它的身份
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, run]);

  /** 左边缘拖拽调宽 */
  const onResizeStart = (e: ReactPointerEvent<HTMLDivElement>) => {
    const handle = e.currentTarget;
    const startX = e.clientX;
    const startW = widthRef.current;
    handle.setPointerCapture(e.pointerId);

    const onMove = (ev: PointerEvent) => {
      const next = Math.min(Math.max(startW + (startX - ev.clientX), MIN_WIDTH), maxAllowedWidth());
      setWidth(next);
    };
    const onUp = () => {
      handle.removeEventListener("pointermove", onMove);
      handle.removeEventListener("pointerup", onUp);
      handle.removeEventListener("pointercancel", onUp);
      try {
        localStorage.setItem(WIDTH_KEY, String(Math.round(widthRef.current)));
      } catch {
        /* ignore */
      }
    };
    handle.addEventListener("pointermove", onMove);
    handle.addEventListener("pointerup", onUp);
    handle.addEventListener("pointercancel", onUp);
  };

  const avgScore = items.length
    ? items.reduce((s, i) => s + i.analysis.overall_score, 0) / items.length
    : 0;
  const totalScore = items.reduce((s, i) => s + Math.max(i.analysis.overall_score, 0), 0) || 1;

  const pillTitle =
    phase === "running"
      ? "分析中，主界面可继续操作"
      : phase === "done"
        ? "分析完成"
        : phase === "error"
          ? "分析失败"
          : "深度分析";
  const pillMeta =
    phase === "running"
      ? total > 0
        ? `已完成 ${items.length}/${total} 只`
        : "正在准备…"
      : phase === "done"
        ? items.length > 0
          ? `${items.length} 只 · 平均 ${avgScore.toFixed(1)} 分`
          : "已结束"
        : phase === "error"
          ? "点击查看原因"
          : items.length > 0
            ? `${items.length} 条结果`
            : "点击展开";

  return (
    <>
      <AnimatePresence>
        {open && !collapsed && (
          <div className="pointer-events-none fixed inset-0 z-50 flex justify-end">
            <motion.aside
              ref={panelRef}
              initial={{ x: "100%" }}
              animate={{ x: 0 }}
              exit={{ x: "100%" }}
              transition={{ type: "spring", stiffness: 380, damping: 36 }}
              role="region"
              aria-label="深度分析"
              /* 不占满视口：永远给主界面留一条可点的区域；移动端没有并排空间，故 min 到 100% 即全宽 */
              style={{ width: `min(${width}px, 100%)` }}
              /* 移动端给底部导航让出 4rem，否则收起前的面板会把导航压住，连 tab 都切不了 */
              className="pointer-events-auto relative flex h-[calc(100dvh-4rem)] flex-col border-l border-slate-800 bg-slate-950 shadow-2xl sm:h-full"
            >
              {/* 左边缘拖拽调宽（桌面端） */}
              <div
                onPointerDown={onResizeStart}
                role="separator"
                aria-orientation="vertical"
                aria-label="调整面板宽度"
                title="拖拽调整宽度"
                className="absolute inset-y-0 left-0 z-10 hidden w-2 -translate-x-1/2 cursor-col-resize transition-colors hover:bg-brand/50 sm:block"
              />

              {/* 抽屉头 */}
              <div className="flex items-center justify-between gap-3 border-b border-slate-800 px-4 py-3 sm:px-6">
                <div className="flex min-w-0 items-center gap-2">
                  <BarChart3 className="h-4 w-4 shrink-0 text-brand-light" aria-hidden />
                  <h2 className="text-sm font-semibold text-white">深度分析</h2>
                  <span className="hidden truncate text-xs text-ink-faint sm:inline">
                    AI 综合行情、K线趋势与最新新闻
                  </span>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <button
                    onClick={() => setCollapsed(true)}
                    aria-label="收起"
                    title="收起（分析继续在后台跑，主界面可继续操作）"
                    className="rounded-lg p-1.5 text-ink-muted hover:bg-slate-800 hover:text-white"
                  >
                    <PanelRightClose className="h-4 w-4" />
                  </button>
                  <button
                    onClick={close}
                    aria-label="关闭"
                    title="关闭（正在运行的分析会被中止）"
                    className="rounded-lg p-1.5 text-ink-muted hover:bg-slate-800 hover:text-white"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
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
                      <Button variant="primary" size="xl"
                        onClick={() => void run(input)}
                        >
                        开始分析
                      </Button>
                    )}
                  </div>
                  <p className="mt-2 text-xs text-ink-faint">
                    提示：Ctrl + Enter 触发分析 · Esc 收起 · 分析期间主界面可继续操作
                  </p>
                  <label className="mt-2 flex cursor-pointer items-start gap-2 text-xs text-ink-muted">
                    <input
                      type="checkbox"
                      checked={debate}
                      onChange={(e) => setDebate(e.target.checked)}
                      disabled={phase === "running"}
                      className="mt-0.5 accent-blue-600"
                    />
                    <span>
                      多空研究员对辩
                      <span className="ml-1 text-ink-faint">
                        （每只票额外 2 轮 LLM 调用，更慢；结论仅为分歧与风险提示，不构成买卖依据）
                      </span>
                    </span>
                  </label>
                </div>

                {/* 状态 */}
                {(phase === "running" || phase === "done") && status && (
                  <div className="mt-4 flex items-center gap-2 rounded-xl border border-slate-800 bg-slate-900 px-4 py-3 text-sm text-ink-soft">
                    {phase === "running" ? (
                      <>
                        <RunningDot />
                        <span>{status}</span>
                        {total > 0 && (
                          <span className="ml-auto shrink-0 text-xs text-ink-faint tabular-nums">
                            {items.length}/{total}
                          </span>
                        )}
                        {currentCode && <span className="text-xs text-ink-faint">({currentCode})</span>}
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
                      <BarChart3 className="h-7 w-7 text-brand-light" aria-hidden />
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

      {/* 收起后的常驻胶囊：实时报进度，点开还原 —— 这是「分析不挡事」的关键 */}
      <AnimatePresence>
        {open && collapsed && (
          <motion.button
            type="button"
            initial={{ opacity: 0, y: 12, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 12, scale: 0.96 }}
            transition={{ duration: 0.18 }}
            onClick={() => setCollapsed(false)}
            aria-label="展开深度分析面板"
            className="fixed bottom-16 right-3 z-50 flex max-w-[86vw] items-center gap-2.5 rounded-full border border-slate-700 bg-slate-900/95 py-2 pl-3 pr-4 text-left shadow-2xl backdrop-blur sm:bottom-6 sm:right-6"
          >
            {phase === "running" ? <RunningDot /> : <BarChart3 className="h-4 w-4 shrink-0 text-brand-light" aria-hidden />}
            <span className="min-w-0">
              <span className="block truncate text-xs font-medium text-ink">{pillTitle}</span>
              <span className="block truncate text-xs text-ink-faint">{pillMeta}</span>
            </span>
          </motion.button>
        )}
      </AnimatePresence>
    </>
  );
}
