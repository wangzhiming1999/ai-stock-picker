import type { ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown } from "lucide-react";
import { PAGE_WRAP, SUB } from "../../lib/ui";

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
 *
 * ⚠️ 宽度用 `PAGE_WRAP`，**不要**再写 `max-w-6xl`。
 *    此前这里写的是 `max-w-6xl`（1152px），而页面主体是 `max-w-[1360px]` ——
 *    两者相差 208px，温度带的左边界与页面标题的左边界肉眼可见对不齐，
 *    整页看起来像上下两块拼起来的。这是纯机械缺陷，不是审美判断。
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
    <div className="border-b border-surface-line-soft bg-surface-panel/60">
      <div className={PAGE_WRAP}>
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          className="flex w-full items-center gap-3 py-2.5 text-left"
        >
          {icon}
          <span className="flex flex-1 flex-wrap items-center gap-x-3 gap-y-1 text-meta">{header}</span>
          <ChevronDown
            className={`h-4 w-4 shrink-0 text-ink-muted transition-transform ${open ? "rotate-180" : ""}`}
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
