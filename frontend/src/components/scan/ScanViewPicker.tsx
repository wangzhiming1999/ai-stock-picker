import type { ScanView } from "../scanPanelLogic";

interface Props {
  scanView: ScanView;
  /** quick 在首次进入会自动跑默认策略，期间禁用该入口防重复触发 */
  strategyRunning: boolean;
  onSelect: (view: ScanView) => void;
}

const VIEWS: Array<[ScanView, string, string]> = [
  ["quick", "找今日候选", "新手建议从这里开始"],
  ["timing", "看早盘/尾盘", "只在对应时段使用"],
  ["advanced", "自己设条件", "适合熟悉指标的用户"],
];

/**
 * 扫描目标选择器 · 扫描子页内的第一层
 *
 * ⚠️ 这是「区块级」切换，不是第三级导航 —— 它只在扫描子页内出现，
 * 切换成本低（三个入口一屏可见）。**不要再往里加"看实战形态"这类入口**：
 * 形态原本在这里，被藏了两层，2026-09-20 已提升为并列子页。
 */
export default function ScanViewPicker({ scanView, strategyRunning, onSelect }: Props) {
  return (
    <section className="rounded-xl border border-surface-line bg-surface-panel p-5">
      <h3 className="text-sm font-semibold text-ink">你今天想找什么？</h3>
      <p className="mt-1 text-xs text-ink-faint">
        先选一个目标。扫描结果只是候选池，进入深度分析确认后再决定是否操作。
      </p>
      <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-3">
        {VIEWS.map(([value, label, desc]) => (
          <button
            key={value}
            onClick={() => onSelect(value)}
            disabled={value === "quick" && strategyRunning}
            aria-busy={value === "quick" && strategyRunning}
            aria-pressed={scanView === value}
            className={`cursor-pointer rounded-lg border p-3 text-left transition disabled:cursor-wait ${
              scanView === value
                ? "border-brand bg-brand/10"
                : "border-surface-line-strong hover:border-slate-400"
            }`}
          >
            <div className="text-sm font-semibold text-ink-strong">{label}</div>
            <div className="mt-0.5 text-xs text-ink-faint">
              {value === "quick" && strategyRunning ? "正在筛选今日候选…" : desc}
            </div>
          </button>
        ))}
      </div>
    </section>
  );
}
