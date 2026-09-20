import type { ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown } from "lucide-react";
import { SUB } from "../../lib/ui";

/**
 * 两根温度带共用的「折叠条 + 展开面板」外壳。
 *
 * 涨停 / 跌停两条常驻条结构完全对称：外层一条 border-b 的常驻条，
 * 折叠态显示一行摘要（header 槽），点击展开后用 motion 高度动画露出面板（children 槽）。
 * 把这段外壳抽出来，两条带子的宿主只负责「取数 + 展开状态 + 把内容塞进两个槽」，
 * 不再各自重复写一遍 AnimatePresence / motion.div / ChevronDown 那套。
 *
 * 行为纪律（两条带子共用、不可破坏）：
 *   - open 由宿主用 useState 持有，点击只触发 onToggle，不在壳里改状态；
 *   - aria-expanded 跟随 open，供无障碍与「功能地图」跳转后的视觉一致；
 *   - 展开内容包在 `${SUB} space-y-4 p-4` 里（与重构前一致），槽位不动。
 */
export function TapeShell({
  open,
  onToggle,
  icon,
  header,
  children,
}: {
  open: boolean;
  onToggle: () => void;
  icon: ReactNode;
  header: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="border-b border-slate-800/80 bg-slate-900/60">
      <div className="mx-auto max-w-6xl px-4 sm:px-6">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          className="flex w-full items-center gap-3 py-2 text-left"
        >
          {icon}
          <span className="flex flex-1 flex-wrap items-center gap-x-3 gap-y-1 text-xs">{header}</span>
          <ChevronDown
            className={`h-4 w-4 shrink-0 text-ink-faint transition-transform ${open ? "rotate-180" : ""}`}
            aria-hidden
          />
        </button>

        <AnimatePresence initial={false}>
          {open && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="overflow-hidden"
            >
              <div className={`mb-3 ${SUB} space-y-4 p-4`}>{children}</div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
