import { useCallback, useEffect, useRef, useState } from "react";
import { Compass, LogIn } from "lucide-react";
import { motion } from "framer-motion";
import { Toaster } from "sonner";
import { useAuth } from "./auth/AuthContext";
import AlertBell from "./components/AlertBell";
import AnalysisDrawer from "./components/AnalysisDrawer";
import AuthModal from "./components/AuthModal";
import BrandLogo from "./components/BrandLogo";
import Button, { buttonVariants } from "./components/ui/Button";
import ErrorBoundary from "./components/ui/ErrorBoundary";
import FeatureMapModal from "./components/FeatureMapModal";
import HoldingsPanel from "./components/HoldingsPanel";
import OpportunityPanel from "./components/OpportunityPanel";
import ResearchPanel from "./components/ResearchPanel";
import StockSearchInput from "./components/StockSearchInput";
import TodayPanel from "./components/TodayPanel";
import { emitBus, useBus } from "./lib/bus";
import { requestBlockFocus } from "./lib/blockFocus";
import { DOMAIN_TAB, type Domain, type FeatureEntry, type NavJump } from "./lib/featureMap";
import { DEFAULT_TAB, NAV, isTab, type Tab } from "./lib/nav";
import { PAGE_WRAP } from "./lib/ui";

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
 * 页面的编排在四个 Panel 里，分析的状态机在 AnalysisDrawer 里 —— 外壳不持有业务状态。
 *
 * ## 层级（重构后的最终形态）
 *   ┌ 顶栏（sticky，高度写在 index.css 的 --header-h）
 *   │   第一行：品牌 · 全局搜索 · 全部功能 · 预警 · 账户
 *   │   第二行：一级导航（sm 及以上；移动端在底部）
 *   ├ 市场温度带（涨停 / 跌停）—— 常驻，读市场情绪
 *   ├ main
 *   │   PageHeader（这一页是什么）
 *   │   SubNav（吸顶，这一页有哪些子页）
 *   │   子页内容
 *   └ 移动端底部导航
 *
 * **为什么把一级导航放进吸顶顶栏**：重构前它跟着内容一起滚走，于是用户往下滚两屏
 * 之后既不知道自己在哪一页、也没法换页。现在「我在哪一页」和「这一页有哪些子页」
 * 在任何滚动位置都同时可见 —— 这是"找不到"的结构性解法，不是再加一个索引导航。
 *
 * ⚠️ 不要往这里塞业务逻辑。需要新页面 = 在 nav.ts 加一条 + 写一个 Panel
 *    （`featureMap.test.ts` 会检查新页面是否真的有子页与功能登记）。
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

  // 功能地图：任何页面都能打开；focusDomain 决定打开后滚到哪一组
  const [mapOpen, setMapOpen] = useState(false);
  const [mapFocus, setMapFocus] = useState<Domain | null>(null);
  // 跨子页跳转（见 lib/featureMap.ts:NavJump）
  const [jump, setJump] = useState<NavJump | null>(null);

  const openMap = useCallback((domain: Domain | null) => {
    setMapFocus(domain);
    setMapOpen(true);
  }, []);

  const gotoFeature = useCallback((f: FeatureEntry) => {
    setMapOpen(false);
    if (f.domain === "global") {
      // 常驻条 / 顶部搜索在每一页都在，不必切 tab，只把目标展开或聚焦
      if (f.anchor) emitBus(f.anchor);
      return;
    }
    const target = DOMAIN_TAB[f.domain];
    setTab(target);
    setJump((prev) => ({ tab: target, sub: f.sub, id: (prev?.id ?? 0) + 1 }));

    if (f.block) {
      // 目标区块自己认领这次请求：它可能还没挂载（lazy + Suspense），
      // 也可能因为数据没到而根本没渲染（`{data && <CollapsiblePanel/>}`）。
      // ⚠️ 这里**不要**再滚顶部 —— 两个滚动指令会互相打断，最后停在哪取决于谁后发生。
      requestBlockFocus(f.block);
    } else {
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  }, []);

  // 顶部搜索框的聚焦请求（功能地图里的「全局搜索 · 深度分析」）
  const searchWrapRef = useRef<HTMLDivElement>(null);
  useBus("search", () => {
    window.scrollTo({ top: 0, behavior: "smooth" });
    searchWrapRef.current?.querySelector("input")?.focus();
  });

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

  // 换一级页时回到顶部：否则从长页切到短页会停在半空，看起来像"这页是空的"
  const changeTab = useCallback((t: Tab) => {
    setTab(t);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

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
    <div className="min-h-screen bg-surface-canvas text-ink">
      <Toaster
        theme="dark"
        position="top-center"
        richColors
        toastOptions={{ style: { background: "#0d1424", border: "1px solid #2b3a5a" } }}
      />

      {/* ── 顶栏 ────────────────────────────────────────────────
          sticky 且含一级导航：任一滚动位置都能看到"我在哪一页、能去哪一页"。
          两行高度固定（h-14 / h-11），与 index.css 的 --header-h 对应。 */}
      <header className="sticky top-0 z-40 border-b border-surface-line bg-surface-panel/90 backdrop-blur">
        <div className={PAGE_WRAP}>
          <div className="flex h-14 items-center justify-between gap-3">
            <BrandLogo onClick={() => changeTab(DEFAULT_TAB)} />

            {/* 全局快捷搜索 */}
            <div className="relative hidden max-w-md flex-1 sm:block" ref={searchWrapRef}>
              <StockSearchInput value={quickText} onChange={setQuickText} onPickCode={handleQuickPick} />
            </div>

            <div className="flex shrink-0 items-center gap-2">
              {/* 功能地图：一级导航只有 4 项，但功能有 20+ 个，所以索引常驻在头部 */}
              <Button
                variant="outline"
                size="md"
                onClick={() => openMap(null)}
                title="全部功能 · 一眼看到这个工具有什么"
              >
                <Compass className="h-3.5 w-3.5" aria-hidden />
                <span className="hidden sm:inline">全部功能</span>
              </Button>
              {user && <AlertBell />}
              {user ? (
                <div className="flex items-center gap-1 rounded-lg border border-surface-line px-3 py-1.5">
                  <span className="hidden max-w-[140px] truncate text-meta text-ink-soft md:inline">{user.email}</span>
                  <Button variant="ghost" size="xs" onClick={signOut}>
                    <LogIn className="h-3.5 w-3.5" aria-hidden />
                    退出
                  </Button>
                </div>
              ) : (
                <motion.button
                  onClick={() => setAuthOpen(true)}
                  whileTap={{ scale: 0.96 }}
                  className={buttonVariants({ variant: "primary", size: "md" })}
                >
                  <LogIn className="h-3.5 w-3.5" aria-hidden />
                  登录
                </motion.button>
              )}
            </div>
          </div>
        </div>

        {/* 一级导航：下划线式。与二级导航的实心胶囊**刻意区分** ——
            两条长得一样的带子叠在一起时，用户分不清哪条是"换页"、哪条是"换区块"。 */}
        <nav aria-label="主要功能" className="hidden border-t border-surface-line-soft sm:block">
          <div className={`${PAGE_WRAP} flex h-11 items-stretch gap-0.5`}>
            {NAV.map((t) => {
              const Icon = t.icon;
              const active = tab === t.key;
              return (
                <button
                  key={t.key}
                  onClick={() => changeTab(t.key)}
                  aria-current={active ? "page" : undefined}
                  className={`relative flex items-center gap-1.5 px-3 text-body font-medium transition-colors ${
                    active ? "text-ink-strong" : "text-ink-muted hover:text-ink"
                  }`}
                >
                  <Icon className="h-4 w-4" strokeWidth={2.2} aria-hidden />
                  {t.label}
                  <span className="hidden text-meta font-normal text-ink-muted lg:inline">{t.desc}</span>
                  {active && (
                    <motion.span
                      layoutId="top-tab-underline"
                      className="absolute inset-x-2 bottom-0 h-[2px] rounded-full bg-brand-light"
                      transition={{ type: "spring", stiffness: 420, damping: 34 }}
                    />
                  )}
                </button>
              );
            })}
          </div>
        </nav>
      </header>

      <AuthModal open={authOpen} onClose={() => setAuthOpen(false)} />
      <FeatureMapModal
        open={mapOpen}
        onClose={() => setMapOpen(false)}
        onGo={gotoFeature}
        focusDomain={mapFocus}
      />

      <main className={`${PAGE_WRAP} pb-24 pt-5 sm:pb-20`}>
        <ErrorBoundary>
          {/* 今日作战：默认首屏，默认子页按时段自动切换 */}
          {mountedTabs.has("today") && (
            <div className={isTabVisible("today")}>
              <TodayPanel onPick={openAnalysis} onOpenMap={openMap} jump={jump?.tab === "today" ? jump : null} />
            </div>
          )}

          {/* 选机会：推荐 / 扫描 / 形态 */}
          {mountedTabs.has("opportunity") && (
            <div className={isTabVisible("opportunity")}>
              <OpportunityPanel onPick={openAnalysis} jump={jump?.tab === "opportunity" ? jump : null} />
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
                jump={jump?.tab === "holdings" ? jump : null}
              />
            </div>
          )}

          {/* 研究：证据台账 / 胜率 / 回测 —— 与「选机会」分开，回答的是另一个问题 */}
          {mountedTabs.has("research") && (
            <div className={isTabVisible("research")}>
              <ResearchPanel jump={jump?.tab === "research" ? jump : null} />
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
        className="fixed inset-x-0 bottom-0 z-40 border-t border-surface-line bg-surface-panel/95 backdrop-blur sm:hidden"
      >
        <div className="grid grid-cols-4">
          {NAV.map((t) => {
            const Icon = t.icon;
            const active = tab === t.key;
            return (
              <motion.button
                key={t.key}
                onClick={() => changeTab(t.key)}
                aria-current={active ? "page" : undefined}
                whileTap={{ scale: 0.92 }}
                className={`flex flex-col items-center gap-0.5 py-2.5 text-meta font-medium transition-colors ${
                  active ? "text-brand-light" : "text-ink-muted"
                }`}
              >
                <Icon className={`h-5 w-5 ${active ? "fill-brand/10" : ""}`} strokeWidth={active ? 2.4 : 2} />
                {t.label}
              </motion.button>
            );
          })}
        </div>
      </nav>

      <footer className={`${PAGE_WRAP} hidden pb-8 text-center text-meta text-ink-faint sm:block`}>
        数据来源：akshare（腾讯/新浪）· 分析模型：DeepSeek · 仅供研究学习，不构成投资建议
      </footer>
    </div>
  );
}
