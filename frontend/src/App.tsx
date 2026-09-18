import { useEffect, useRef, useState } from "react";
import { LogIn } from "lucide-react";
import { motion } from "framer-motion";
import { Toaster } from "sonner";
import { useAuth } from "./auth/AuthContext";
import AlertBell from "./components/AlertBell";
import AnalysisDrawer from "./components/AnalysisDrawer";
import AuthModal from "./components/AuthModal";
import BrandLogo from "./components/BrandLogo";
import ErrorBoundary from "./components/ErrorBoundary";
import HoldingsPanel from "./components/HoldingsPanel";
import LimitDownBar from "./components/LimitDownBar";
import LimitUpBar from "./components/LimitUpBar";
import OpportunityPanel from "./components/OpportunityPanel";
import StockSearchInput from "./components/StockSearchInput";
import TodayPanel from "./components/TodayPanel";
import { DEFAULT_TAB, NAV, isTab, type Tab } from "./lib/nav";

const TAB_STORAGE_KEY = "ai:activeTab";

function readInitialTab(): Tab {
  try {
    const v = localStorage.getItem(TAB_STORAGE_KEY);
    if (isTab(v)) return v;
  } catch {
    /* ignore */
  }
  return DEFAULT_TAB;
}

/**
 * App · 外壳
 *
 * 只负责四件事：一级导航、全局搜索、登录态、分析抽屉。
 * 页面的编排在 TodayPanel / OpportunityPanel / HoldingsPanel 里，
 * 分析的状态机在 AnalysisDrawer 里——外壳不再持有业务状态。
 */
export default function App() {
  const { user, signOut } = useAuth();
  const [authOpen, setAuthOpen] = useState(false);

  const initialTab = useRef(readInitialTab()).current;
  const [tab, setTab] = useState<Tab>(initialTab);
  const [quickText, setQuickText] = useState("");
  // 已挂载过的 Tab：首次访问后常驻 DOM（隐藏而非卸载），避免切换时重复拉数据
  const [mountedTabs, setMountedTabs] = useState<Set<Tab>>(() => new Set<Tab>([initialTab]));

  // 分析抽屉：codes + 自增 id，重复点同一批股票也能重新分析
  const [analysisReq, setAnalysisReq] = useState<{ codes: string[]; id: number } | null>(null);
  const [historyRefresh, setHistoryRefresh] = useState(0);

  useEffect(() => {
    try {
      localStorage.setItem(TAB_STORAGE_KEY, tab);
    } catch {
      /* ignore */
    }
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

  /** 从任意页面勾选股票 → 打开分析抽屉（不再切 tab） */
  const openAnalysis = (codes: string[]) => {
    if (codes.length === 0) return;
    setAnalysisReq((prev) => ({ codes, id: (prev?.id ?? 0) + 1 }));
  };

  /** 头部快捷搜索 → 直接分析单只 */
  const handleQuickPick = (code: string) => {
    setQuickText("");
    openAnalysis([code]);
  };

  return (
    <div className="min-h-screen bg-slate-950 text-ink-strong">
      <Toaster
        theme="dark"
        position="top-center"
        richColors
        toastOptions={{ style: { background: "#0f172a", border: "1px solid #334155" } }}
      />

      {/* 顶部 */}
      <header className="sticky top-0 z-40 border-b border-slate-800/80 bg-slate-900/80 backdrop-blur">
        <div className="mx-auto max-w-6xl px-4 py-3 sm:px-6">
          <div className="flex items-center justify-between gap-3">
            <BrandLogo onClick={() => setTab(DEFAULT_TAB)} />

            {/* 全局快捷搜索 */}
            <div className="relative hidden max-w-md flex-1 sm:block">
              <StockSearchInput value={quickText} onChange={setQuickText} onPickCode={handleQuickPick} />
            </div>

            <div className="flex shrink-0 items-center gap-2">
              {user && <AlertBell />}
              {user ? (
                <motion.div
                  initial={{ opacity: 0, scale: 0.95 }}
                  animate={{ opacity: 1, scale: 1 }}
                  className="flex items-center gap-2 rounded-lg border border-slate-700 px-3 py-1.5"
                >
                  <span className="hidden max-w-[140px] truncate text-xs text-ink-soft md:inline">{user.email}</span>
                  <button onClick={signOut} className="flex items-center gap-1 text-xs text-ink-faint hover:text-ink">
                    <LogIn className="h-3.5 w-3.5" aria-hidden />
                    退出
                  </button>
                </motion.div>
              ) : (
                <motion.button
                  onClick={() => setAuthOpen(true)}
                  whileHover={{ scale: 1.04 }}
                  whileTap={{ scale: 0.95 }}
                  className="flex items-center gap-1.5 rounded-lg bg-brand px-4 py-1.5 text-xs font-medium text-white shadow-[0_2px_8px_rgba(37,99,235,0.35)] hover:bg-brand-dark"
                >
                  <LogIn className="h-3.5 w-3.5" aria-hidden />
                  登录
                </motion.button>
              )}
            </div>
          </div>
        </div>
      </header>

      {/* 涨跌停两条常驻温度带：全局可见的市场情绪读数，展开看梯队 / 板块 / 回测。
          刻意都不进 NAV —— 它们是「读市场」而非「做一件事」，不占一级入口。
          跌停那条带的是**负期望**结论（跌停次日抄底实测 −4.47%/次），所以它只读不推。 */}
      <LimitUpBar />
      <LimitDownBar />

      <AuthModal open={authOpen} onClose={() => setAuthOpen(false)} />

      <main className="mx-auto max-w-6xl px-4 pb-20 pt-4 sm:px-6 sm:pt-6">
        {/* 一级导航（桌面三栏 / 移动横向等分） */}
        <nav aria-label="主要功能" className="mb-5 hidden grid-cols-3 gap-1 rounded-2xl border border-slate-800 bg-slate-900 p-1 sm:grid">
          {NAV.map((t) => {
            const Icon = t.icon;
            const active = tab === t.key;
            return (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                aria-current={active ? "page" : undefined}
                className={`relative flex min-w-0 flex-col items-center gap-1 rounded-lg px-2 py-2.5 text-sm font-medium transition-colors ${
                  active ? "text-white" : "text-ink-muted hover:bg-slate-800/70 hover:text-ink"
                }`}
              >
                {active && (
                  <motion.span
                    layoutId="tab-pill"
                    className="absolute inset-0 rounded-lg bg-brand shadow-[0_0_12px_rgba(37,99,235,0.4)]"
                    transition={{ type: "spring", stiffness: 400, damping: 32 }}
                  />
                )}
                <span className="relative flex items-center gap-1.5">
                  <Icon className={`h-4 w-4 ${active ? "text-white" : ""}`} strokeWidth={2.2} />
                  {t.label}
                </span>
                <span className={`relative hidden text-xs font-normal sm:block ${active ? "text-white/70" : "text-ink-faint"}`}>
                  {t.desc}
                </span>
              </button>
            );
          })}
        </nav>

        <ErrorBoundary>
          {/* 今日作战：默认首屏，主视图按时段自动切换 */}
          {mountedTabs.has("today") && (
            <div className={isTabVisible("today")}>
              <TodayPanel onPick={openAnalysis} />
            </div>
          )}

          {/* 选机会：推荐 / 扫描 / 验证 */}
          {mountedTabs.has("opportunity") && (
            <div className={isTabVisible("opportunity")}>
              <OpportunityPanel onPick={openAnalysis} />
            </div>
          )}

          {/* 持仓：未登录时由面板自己渲染登录引导 */}
          {mountedTabs.has("holdings") && (
            <div className={isTabVisible("holdings")}>
              <HoldingsPanel
                authed={!!user}
                onAnalyze={handleQuickPick}
                onRequestAuth={() => setAuthOpen(true)}
                historyRefresh={historyRefresh}
              />
            </div>
          )}

          {/* 分析抽屉：全局浮层，不再占一级 tab */}
          <AnalysisDrawer
            open={analysisReq !== null}
            codes={analysisReq?.codes ?? null}
            requestId={analysisReq?.id ?? 0}
            onClose={() => setAnalysisReq(null)}
            onBatchSaved={() => setHistoryRefresh((n) => n + 1)}
          />
        </ErrorBoundary>
      </main>

      {/* 移动端底部导航 */}
      <nav
        aria-label="主要功能"
        className="fixed inset-x-0 bottom-0 z-40 border-t border-slate-800 bg-slate-900/95 backdrop-blur sm:hidden"
      >
        <div className="grid grid-cols-3">
          {NAV.map((t) => {
            const Icon = t.icon;
            const active = tab === t.key;
            return (
              <motion.button
                key={t.key}
                onClick={() => setTab(t.key)}
                aria-current={active ? "page" : undefined}
                whileTap={{ scale: 0.92 }}
                className={`flex flex-col items-center gap-0.5 py-2.5 text-xs font-medium transition-colors ${
                  active ? "text-brand-light" : "text-ink-faint"
                }`}
              >
                <Icon className={`h-5 w-5 ${active ? "fill-brand/10" : ""}`} strokeWidth={active ? 2.4 : 2} />
                {t.label}
              </motion.button>
            );
          })}
        </div>
      </nav>

      <footer className="mx-auto hidden max-w-6xl px-6 pb-8 text-center text-xs text-ink-faint sm:block">
        数据来源：akshare（腾讯/新浪）· 分析模型：DeepSeek · 仅供研究学习，不构成投资建议
      </footer>
    </div>
  );
}
