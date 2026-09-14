import { Suspense, useState } from "react";;
import { motion } from "framer-motion";
import { History, LineChart, Star, Wallet } from "lucide-react";
import PanelSkeleton from "./PanelSkeleton";
import { lazyRetry } from "../lib/lazyRetry";

const WatchlistPanel = lazyRetry(() => import("./WatchlistPanel"));
const SimPanel = lazyRetry(() => import("./SimPanel"));
const PortfolioPanel = lazyRetry(() => import("./PortfolioPanel"));
const HistoryPanel = lazyRetry(() => import("./HistoryPanel"));

type SubTab = "position" | "sim" | "watch" | "history";

const SUB_TABS: { key: SubTab; label: string; icon: typeof Wallet }[] = [
  { key: "position", label: "持仓", icon: Wallet },
  { key: "sim", label: "模拟盘", icon: LineChart },
  { key: "watch", label: "自选", icon: Star },
  { key: "history", label: "历史", icon: History },
];

interface Props {
  authed: boolean;
  onAnalyze: (code: string) => void;
  onRequestAuth: () => void;
  /** 分析批次落库后 +1，用于刷新历史记录 */
  historyRefresh: number;
}

/**
 * 持仓 · 「我手里有什么」
 *
 * 原「我的」是把持仓、模拟盘、自选、历史四块无差别堆在一屏，现在改为子 tab。
 * 登录引导改成整页级别的空状态——未登录时不给 tab，避免用户点了半天发现
 * 每个 tab 都要求登录。
 */
export default function HoldingsPanel({ authed, onAnalyze, onRequestAuth, historyRefresh }: Props) {
  const [sub, setSub] = useState<SubTab>("position");
  const [mounted, setMounted] = useState<Set<SubTab>>(() => new Set(["position"]));

  const changeSub = (k: SubTab) => {
    setSub(k);
    setMounted((prev) => {
      if (prev.has(k)) return prev;
      const next = new Set(prev);
      next.add(k);
      return next;
    });
  };

  if (!authed) {
    return (
      <div className="rounded-2xl border border-slate-800 bg-slate-900 p-8 text-center">
        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.35 }}
          className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl border border-slate-800 bg-slate-900"
        >
          <Wallet className="h-7 w-7 text-brand-light" aria-hidden />
        </motion.div>
        <h2 className="mt-4 text-base font-semibold text-ink">登录后管理你的持仓与历史记录</h2>
        <p className="mt-1 text-sm text-ink-faint">持仓数据、风险等级建议与历史分析将按账号隔离保存</p>
        <button
          onClick={onRequestAuth}
          className="mt-5 rounded-lg bg-brand px-6 py-2 text-sm font-medium text-white hover:bg-brand-dark"
        >
          登录 / 注册
        </button>
      </div>
    );
  }

  const visible = (k: SubTab) => (sub === k ? "" : "hidden");

  return (
    <div className="space-y-4">
      <nav aria-label="持仓子导航" className="grid grid-cols-4 gap-1 rounded-xl border border-slate-800 bg-slate-900 p-1">
        {SUB_TABS.map((t) => {
          const Icon = t.icon;
          const active = sub === t.key;
          return (
            <button
              key={t.key}
              onClick={() => changeSub(t.key)}
              aria-current={active ? "page" : undefined}
              className={`flex items-center justify-center gap-1.5 rounded-lg px-2 py-2 text-sm font-medium transition-colors ${
                active ? "bg-brand text-white" : "text-ink-muted hover:bg-slate-800/70 hover:text-ink"
              }`}
            >
              <Icon className="h-4 w-4" strokeWidth={2.2} />
              {t.label}
            </button>
          );
        })}
      </nav>

      {mounted.has("position") && (
        <div className={visible("position")}>
          <Suspense fallback={<PanelSkeleton label="正在加载持仓" />}>
            <PortfolioPanel />
          </Suspense>
        </div>
      )}

      {mounted.has("sim") && (
        <div className={visible("sim")}>
          <Suspense fallback={<PanelSkeleton label="正在加载模拟盘" />}>
            <SimPanel />
          </Suspense>
        </div>
      )}

      {mounted.has("watch") && (
        <div className={visible("watch")}>
          <Suspense fallback={<PanelSkeleton label="正在加载自选股" />}>
            <WatchlistPanel onAnalyze={onAnalyze} />
          </Suspense>
        </div>
      )}

      {mounted.has("history") && (
        <div className={visible("history")}>
          <Suspense fallback={<PanelSkeleton label="正在加载历史记录" />}>
            <HistoryPanel refreshKey={historyRefresh} />
          </Suspense>
        </div>
      )}
    </div>
  );
}
