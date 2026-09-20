import { ArrowRight, Compass } from "lucide-react";
import { DOMAINS, FEATURES, featuresOf, type Domain } from "../lib/featureMap";

interface Props {
  /** null = 打开整张地图；传域 = 打开并滚到那一组 */
  onOpen: (domain: Domain | null) => void;
}

/**
 * 首页「功能地图」入口条
 *
 * 一行高，常驻在时段条下方。它同时干两件事：
 * 1. **报数**：让用户一眼看到产品有多少东西（4 个域 / N 项），
 *    而不是面对一屏"今天先不买"以为这个工具就这么点功能；
 * 2. **入口**：域按钮直接把地图开到对应分组，不用先打开再往下找。
 *
 * 刻意做成一行而不是一整块网格：首屏上方多出 200px 导航，会把当天最该看的
 * 结论挤出屏幕 —— 这条的定位是"索引"，不是"内容"。
 */
export default function FeatureMapBar({ onOpen }: Props) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl border border-slate-800 bg-slate-900 px-4 py-2.5">
      <span className="flex items-center gap-2 text-xs font-medium text-ink-muted">
        <Compass className="h-3.5 w-3.5 text-brand-light" aria-hidden />
        功能地图
        <span className="text-ink-faint">{FEATURES.length} 项</span>
      </span>

      <span className="flex flex-wrap items-center gap-1">
        {DOMAINS.map((d) => (
          <button
            key={d.key}
            type="button"
            onClick={() => onOpen(d.key)}
            title={d.desc}
            className="rounded-lg bg-slate-800/60 px-2 py-1 text-xs text-ink-soft transition-colors hover:bg-slate-700/70 hover:text-ink"
          >
            {d.label} <span className="text-ink-faint">{featuresOf(d.key).length}</span>
          </button>
        ))}
      </span>

      <button
        type="button"
        onClick={() => onOpen(null)}
        className="ml-auto flex shrink-0 items-center gap-1 text-xs font-medium text-brand-light transition-colors hover:text-white"
      >
        全部功能
        <ArrowRight className="h-3.5 w-3.5" aria-hidden />
      </button>
    </div>
  );
}
