import { Suspense, useState } from "react";;
import { Lightbulb, ScanSearch, ShieldCheck } from "lucide-react";
import PanelSkeleton from "./PanelSkeleton";
import RecommendPanel from "./RecommendPanel";
import { lazyRetry } from "../lib/lazyRetry";

const ScanPanel = lazyRetry(() => import("./ScanPanel"));
const VerifyPanel = lazyRetry(() => import("./VerifyPanel"));

type SubTab = "recommend" | "scan" | "verify";

const SUB_TABS: { key: SubTab; label: string; desc: string; icon: typeof Lightbulb }[] = [
  { key: "recommend", label: "推荐", desc: "AI 每日推荐 · 大盘推衍 · 四维排名", icon: Lightbulb },
  { key: "scan", label: "扫描", desc: "策略扫描 · 早盘尾盘异动 · 实战形态", icon: ScanSearch },
  { key: "verify", label: "验证", desc: "胜率 · 策略回测 · 形态回测", icon: ShieldCheck },
];

interface Props {
  onPick: (codes: string[]) => void;
}

/**
 * 选机会 · 二级导航容器
 *
 * 三个子 tab 按「票从哪来 / 怎么筛 / 方法靠不靠谱」排，恰好是一个闭环：
 * 推荐（模型给）→ 扫描（规则筛）→ 验证（回头看方法行不行）。
 *
 * 子 tab 一旦访问就常驻 DOM（隐藏而非卸载），避免来回切换重复拉数据。
 */
export default function OpportunityPanel({ onPick }: Props) {
  const [sub, setSub] = useState<SubTab>("recommend");
  const [mounted, setMounted] = useState<Set<SubTab>>(() => new Set(["recommend"]));

  const changeSub = (k: SubTab) => {
    setSub(k);
    setMounted((prev) => {
      if (prev.has(k)) return prev;
      const next = new Set(prev);
      next.add(k);
      return next;
    });
  };

  const visible = (k: SubTab) => (sub === k ? "" : "hidden");

  return (
    <div className="space-y-4">
      <nav
        aria-label="选机会子导航"
        className="grid grid-cols-3 gap-1 rounded-xl border border-slate-800 bg-slate-900 p-1"
      >
        {SUB_TABS.map((t) => {
          const Icon = t.icon;
          const active = sub === t.key;
          return (
            <button
              key={t.key}
              onClick={() => changeSub(t.key)}
              aria-current={active ? "page" : undefined}
              className={`flex min-w-0 flex-col items-center gap-0.5 rounded-lg px-2 py-2 text-center transition-colors ${
                active ? "bg-brand text-white" : "text-ink-muted hover:bg-slate-800/70 hover:text-ink"
              }`}
            >
              <span className="flex items-center gap-1.5 text-sm font-medium">
                <Icon className="h-4 w-4" strokeWidth={2.2} />
                {t.label}
              </span>
              <span className={`hidden text-xs font-normal sm:block ${active ? "text-white/70" : "text-ink-faint"}`}>
                {t.desc}
              </span>
            </button>
          );
        })}
      </nav>

      {mounted.has("recommend") && (
        <div className={visible("recommend")}>
          <RecommendPanel onPick={onPick} />
        </div>
      )}

      {mounted.has("scan") && (
        <div className={visible("scan")}>
          <Suspense fallback={<PanelSkeleton label="正在加载扫描区" />}>
            <ScanPanel onPick={onPick} />
          </Suspense>
        </div>
      )}

      {mounted.has("verify") && (
        <div className={visible("verify")}>
          <Suspense fallback={<PanelSkeleton label="正在加载验证区" />}>
            <VerifyPanel />
          </Suspense>
        </div>
      )}
    </div>
  );
}
