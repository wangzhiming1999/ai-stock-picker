import { useEffect, useRef, useState } from "react";
import type { ComponentType, SVGProps } from "react";
import { BarChart3, Lightbulb, LogIn, ScanSearch, UserRound } from "lucide-react";
import { motion } from "framer-motion";
import { Toaster, toast } from "sonner";
import { useAuth } from "./auth/AuthContext";
import { fetchStock, streamAnalysis } from "./api/client";
import AuthModal from "./components/AuthModal";
import BrandLogo from "./components/BrandLogo";
import DiscoverPanel from "./components/DiscoverPanel";
import ErrorBoundary from "./components/ErrorBoundary";
import HistoryPanel from "./components/HistoryPanel";
import PortfolioPanel from "./components/PortfolioPanel";
import ScanPanel from "./components/ScanPanel";
import StockCard from "./components/StockCard";
import StockSearchInput from "./components/StockSearchInput";
import WatchlistPanel from "./components/WatchlistPanel";
import { cardItem, stagger } from "./lib/motion";
import type { StockAnalysis, StockInfo, SSEEvent } from "./types";

type Phase = "idle" | "running" | "done" | "error";
type Tab = "discover" | "scan" | "analyze" | "mine";

type IconComp = ComponentType<SVGProps<SVGSVGElement>>;

const TAB_LIST: { key: Tab; label: string; icon: IconComp; desc: string }[] = [
  { key: "discover", label: "发现好股", icon: Lightbulb, desc: "每日推荐 · 大盘推衍 · 板块热榜" },
  { key: "scan", label: "选股扫描", icon: ScanSearch, desc: "策略扫描 · 全市场 · 胜率 · 回测" },
  { key: "analyze", label: "深度分析", icon: BarChart3, desc: "AI 综合分析个股" },
  { key: "mine", label: "我的", icon: UserRound, desc: "持仓管理 · 历史记录" },
];

const TAB_STORAGE_KEY = "ai:activeTab";

interface AnalysisItem {
  analysis: StockAnalysis;
  info?: StockInfo;
}

function parseCodesFromText(text: string): string[] {
  return text
    .split(/[\s,，;；、]+/)
    .map((s) => s.trim())
    .filter((s) => /^\d{6}$/.test(s));
}

function readInitialTab(): Tab {
  try {
    const v = localStorage.getItem(TAB_STORAGE_KEY);
    if (v && TAB_LIST.some((t) => t.key === v)) return v as Tab;
  } catch {
    /* ignore */
  }
  return "discover";
}

export default function App() {
  const { user, signOut } = useAuth();
  const [authOpen, setAuthOpen] = useState(false);
  const [tab, setTab] = useState<Tab>(readInitialTab);
  const [codes, setCodes] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [status, setStatus] = useState("");
  const [items, setItems] = useState<AnalysisItem[]>([]);
  const [currentCode, setCurrentCode] = useState<string>("");
  const [errorMsg, setErrorMsg] = useState("");
  const [infos, setInfos] = useState<Record<string, StockInfo>>({});
  const [historyRefresh, setHistoryRefresh] = useState(0);
  const [quickText, setQuickText] = useState("");
  // 已挂载过的 Tab：首次访问后常驻 DOM（隐藏而非卸载），避免切换时重复拉数据
  const [mountedTabs, setMountedTabs] = useState<Set<Tab>>(() => new Set([tab]));

  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    try {
      localStorage.setItem(TAB_STORAGE_KEY, tab);
    } catch {
      /* ignore */
    }
    // 记录当前 Tab 已访问（保持挂载）：仅在新增 tab 时才换引用，避免不必要的重渲染
    setMountedTabs((prev) => {
      if (prev.has(tab)) return prev;
      const next = new Set(prev);
      next.add(tab);
      return next;
    });
  }, [tab]);

  // 组件（如加自选）触发登录请求
  useEffect(() => {
    const handler = () => setAuthOpen(true);
    window.addEventListener("stock:require-auth", handler);
    return () => window.removeEventListener("stock:require-auth", handler);
  }, []);

  const isTabVisible = (t: Tab) => (tab === t ? "" : "hidden");

  const changeTab = (t: Tab) => {
    setTab(t);
  };

  const runAnalysis = async (raw?: string) => {
    // raw 显式传入优先（勾选跳转场景），避免闭包读到 setState 前的旧 codes
    const list = parseCodesFromText(raw ?? codes);
    if (list.length === 0) {
      setErrorMsg("请输入有效的 6 位股票代码，多个用逗号分隔，例如：600519, 000858, 300750");
      return;
    }

    setPhase("running");
    setErrorMsg("");
    setItems([]);
    setStatus("正在准备...");
    setInfos({});

    abortRef.current = new AbortController();
    const signal = abortRef.current.signal;

    const infoTask = Promise.all(
      list.map((code) => fetchStock(code).catch(() => undefined))
    ).then((results) => {
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
          setHistoryRefresh((n) => n + 1);
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
      await Promise.all([infoTask, streamAnalysis(list, handleEvent, signal)]);
      // 兜底：服务端连接关闭但未发 done 事件时结束 running 态，避免永远"运行中"
      setPhase((p) => (p === "running" ? "done" : p));
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        const msg = (err as Error).message || "分析失败，请检查后端服务是否启动、API Key 是否配置";
        setPhase("error");
        setErrorMsg(msg);
        toast.error("分析失败", { description: msg });
      }
    }
  };

  const stop = () => {
    abortRef.current?.abort();
    setPhase("idle");
    setStatus("已手动停止");
  };

  // 从发现/扫描面板勾选股票 → 直达深度分析
  const handlePick = (codesList: string[]) => {
    const joined = codesList.join(", ");
    setCodes(joined);
    changeTab("analyze");
    // 显式传参启动，避免闭包读到旧 codes
    void runAnalysis(joined);
  };

  // 头部快捷搜索
  const handleQuickPick = (code: string) => {
    setCodes(code);
    setQuickText("");
    changeTab("analyze");
    void runAnalysis(code);
  };

  // Ctrl/Cmd + Enter 快捷分析
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && tab === "analyze") {
        e.preventDefault();
        if (phase !== "running") void runAnalysis();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, phase, codes]);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <Toaster theme="dark" position="top-center" richColors toastOptions={{ style: { background: "#0f172a", border: "1px solid #334155" } }} />
      {/* 顶部 */}
      <header className="sticky top-0 z-40 border-b border-slate-800/80 bg-slate-900/80 backdrop-blur">
        <div className="mx-auto max-w-6xl px-4 py-3 sm:px-6">
          <div className="flex items-center justify-between gap-3">
            <BrandLogo onClick={() => changeTab("discover")} />

            {/* 全局快捷搜索 */}
            <div className="relative flex-1 max-w-md">
              <StockSearchInput value={quickText} onChange={setQuickText} onPickCode={handleQuickPick} />
            </div>

            <div className="flex shrink-0 items-center gap-2">
              {user ? (
                <motion.div
                  initial={{ opacity: 0, scale: 0.95 }}
                  animate={{ opacity: 1, scale: 1 }}
                  className="flex items-center gap-2 rounded-lg border border-slate-700 px-3 py-1.5"
                >
                  <span className="hidden max-w-[140px] truncate text-xs text-slate-300 md:inline">{user.email}</span>
                  <button onClick={signOut} className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-200">
                    <LogIn className="h-3.5 w-3.5" />
                    退出
                  </button>
                </motion.div>
              ) : (
                <motion.button
                  onClick={() => setAuthOpen(true)}
                  whileHover={{ scale: 1.04 }}
                  whileTap={{ scale: 0.95 }}
                  className="flex items-center gap-1.5 rounded-lg bg-brand px-4 py-1.5 text-xs font-medium text-white shadow-[0_2px_8px_rgba(220,38,38,0.3)] hover:bg-brand-dark"
                >
                  <LogIn className="h-3.5 w-3.5" />
                  登录
                </motion.button>
              )}
            </div>
          </div>
        </div>
      </header>

      <AuthModal open={authOpen} onClose={() => setAuthOpen(false)} />

      <main className="mx-auto max-w-6xl px-4 pb-20 pt-4 sm:px-6 sm:pt-6">
        {/* Tab 导航（桌面横向排列 / 移动横向滚动） */}
        <nav className="relative mb-5 grid grid-cols-4 gap-1 rounded-xl border border-slate-800 bg-slate-900/60 p-1">
          {TAB_LIST.map((t) => {
            const Icon = t.icon;
            const active = tab === t.key;
            return (
              <button
                key={t.key}
                onClick={() => changeTab(t.key)}
                className={`relative flex min-w-0 flex-col items-center gap-1 rounded-lg px-2 py-2.5 text-sm font-medium transition-colors ${
                  active ? "text-white" : "text-slate-400 hover:bg-slate-800/60 hover:text-slate-200"
                }`}
              >
                {active && (
                  <motion.span
                    layoutId="tab-pill"
                    className="absolute inset-0 rounded-lg bg-brand shadow-[0_0_12px_rgba(220,38,38,0.35)]"
                    transition={{ type: "spring", stiffness: 400, damping: 32 }}
                  />
                )}
                <span className="relative flex items-center gap-1.5">
                  <Icon className={`h-4 w-4 ${active ? "text-white" : ""}`} strokeWidth={2.2} />
                  {t.label}
                </span>
                <span className={`relative hidden text-[10px] font-normal sm:block ${active ? "text-white/70" : "text-slate-500"}`}>
                  {t.desc}
                </span>
              </button>
            );
          })}
        </nav>

        <ErrorBoundary>
          {/* 深度分析：常驻 DOM，切走仅隐藏（保留结果，避免重复加载） */}
        <div className={isTabVisible("analyze")}>
            {/* 输入区 */}
            <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 sm:p-5">
              <label className="mb-2 block text-sm font-medium text-slate-300">
                股票搜索 <span className="ml-1 text-xs font-normal text-slate-500">（代码/名称 · 支持多只）</span>
              </label>
              <div className="flex flex-col gap-3 sm:flex-row">
                <StockSearchInput
                  value={codes}
                  onChange={setCodes}
                  onPickCode={(code) => {
                    setCodes((prev) => {
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
                    className="rounded-lg border border-slate-600 bg-slate-800 px-6 py-2.5 text-sm font-medium text-slate-200 hover:bg-slate-700"
                  >
                    停止
                  </button>
                ) : (
                  <button
                    onClick={() => void runAnalysis()}
                    className="rounded-lg bg-brand px-6 py-2.5 text-sm font-medium text-white hover:bg-brand-dark disabled:opacity-50"
                  >
                    开始分析
                  </button>
                )}
              </div>
              <p className="mt-2 text-xs text-slate-500">提示：支持 Ctrl + Enter 快捷触发；在"发现好股 / 选股扫描"中勾选股票即可一键直达分析</p>
            </div>

            {/* 状态 */}
            {(phase === "running" || phase === "done") && status && (
              <div className="mt-4 flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-900/60 px-4 py-3 text-sm text-slate-300">
                {phase === "running" ? (
                  <>
                    <span className="relative flex h-2.5 w-2.5">
                      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-green-400 opacity-75" />
                      <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-green-500" />
                    </span>
                    <span>{status}</span>
                    {currentCode && <span className="ml-2 text-xs text-slate-500">({currentCode})</span>}
                  </>
                ) : (
                  <span className="text-green-400">✓ {status}</span>
                )}
              </div>
            )}

            {/* 错误 */}
            {phase === "error" && errorMsg && (
              <div className="mt-4 rounded-lg border border-red-800 bg-red-950/40 px-4 py-3 text-sm text-red-300">
                {errorMsg}
              </div>
            )}

            {/* 结果列表 */}
            {items.length > 0 && (
              <div className="mt-8">
                <div className="mb-4 flex items-center justify-between">
                  <h2 className="text-lg font-bold text-white">分析结果</h2>
                  <div className="flex items-center gap-4 text-sm">
                    <span className="text-slate-400">平均分</span>
                    <span className="text-xl font-bold text-brand">
                      {(items.reduce((s, i) => s + i.analysis.overall_score, 0) / items.length).toFixed(1)}
                    </span>
                  </div>
                </div>
                <div className="mb-6 flex h-8 w-full overflow-hidden rounded-lg border border-slate-800">
                  {items.map((item, idx) => (
                    <div
                      key={item.analysis.code + idx}
                      className="flex items-center justify-center overflow-hidden border-r border-slate-800 last:border-r-0 text-xs font-medium"
                      style={{
                        width: `${(item.analysis.overall_score / Math.max(...items.map((i) => i.analysis.overall_score), 1)) * (100 / items.length)}%`,
                        background: `linear-gradient(to top, rgba(220,38,38,0.85), rgba(220,38,38,0.45))`,
                      }}
                      title={`${item.analysis.name} ${item.analysis.overall_score.toFixed(1)}`}
                    >
                      {item.analysis.name}
                    </div>
                  ))}
                </div>
                <motion.div className="grid gap-6 lg:grid-cols-2" variants={stagger} initial="hidden" animate="visible" key={items.length}>
                  {items.map((item, idx) => (
                    <motion.div key={item.analysis.code + idx} variants={cardItem}>
                      <StockCard analysis={item.analysis} info={infos[item.analysis.code]} />
                    </motion.div>
                  ))}
                </motion.div>
              </div>
            )}

            {/* 空状态 */}
            {phase === "idle" && (
              <div className="mt-12 text-center">
                <motion.div
                  initial={{ opacity: 0, scale: 0.9 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ duration: 0.4 }}
                  className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl border border-slate-800 bg-slate-900 text-3xl"
                >
                  <BarChart3 className="h-8 w-8 text-brand" />
                </motion.div>
                <p className="mt-4 text-sm text-slate-500">
                  输入 A 股代码，AI 将综合行情、K线趋势与最新新闻给出选股评分
                </p>
              </div>
            )}
        </div>

        {/* 发现好股：常驻 DOM */}
        {mountedTabs.has("discover") && (
          <div className={isTabVisible("discover")}>
            <DiscoverPanel onPick={handlePick} />
          </div>
        )}

        {/* 选股扫描：常驻 DOM */}
        {mountedTabs.has("scan") && (
          <div className={isTabVisible("scan")}>
            <ScanPanel onPick={handlePick} />
          </div>
        )}

        {/* 我的：常驻 DOM（登录引导无网络请求；面板仅登录后挂载一次） */}
        {mountedTabs.has("mine") && (
          <div className={isTabVisible("mine")}>
            <div className="space-y-5">
              {!user ? (
                <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-8 text-center">
                  <motion.div
                    initial={{ opacity: 0, scale: 0.9 }}
                    animate={{ opacity: 1, scale: 1 }}
                    transition={{ duration: 0.35 }}
                    className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl border border-slate-800 bg-slate-900"
                  >
                    <UserRound className="h-7 w-7 text-brand" />
                  </motion.div>
                  <h2 className="mt-4 text-base font-semibold text-slate-200">登录后管理你的持仓与历史记录</h2>
                  <p className="mt-1 text-sm text-slate-500">持仓数据、风险等级建议与历史分析将按账号隔离保存</p>
                  <button
                    onClick={() => setAuthOpen(true)}
                    className="mt-5 rounded-lg bg-brand px-6 py-2 text-sm font-medium text-white hover:bg-brand-dark"
                  >
                    登录 / 注册
                  </button>
                </div>
              ) : (
                <>
                  <WatchlistPanel onAnalyze={handleQuickPick} />
                  <PortfolioPanel />
                  <HistoryPanel refreshKey={historyRefresh} />
                </>
              )}
            </div>
          </div>
        )}
        </ErrorBoundary>
      </main>

      {/* 移动端底部导航 */}
      <nav className="fixed inset-x-0 bottom-0 z-40 border-t border-slate-800 bg-slate-900/95 backdrop-blur sm:hidden">
        <div className="grid grid-cols-4">
          {TAB_LIST.map((t) => {
            const Icon = t.icon;
            const active = tab === t.key;
            return (
              <motion.button
                key={t.key}
                onClick={() => changeTab(t.key)}
                whileTap={{ scale: 0.92 }}
                className={`flex flex-col items-center gap-0.5 py-2.5 text-[11px] font-medium transition-colors ${
                  active ? "text-brand" : "text-slate-500"
                }`}
              >
                <Icon className={`h-5 w-5 ${active ? "fill-brand/10" : ""}`} strokeWidth={active ? 2.4 : 2} />
                {t.label}
              </motion.button>
            );
          })}
        </div>
      </nav>

      <footer className="mx-auto hidden max-w-6xl px-6 pb-8 text-center text-xs text-slate-600 sm:block">
        数据来源：akshare（腾讯/新浪）· 分析模型：DeepSeek · 仅供研究学习，不构成投资建议
      </footer>
    </div>
  );
}
