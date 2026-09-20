import { motion } from "framer-motion";
import { BarChart3 } from "lucide-react";
import RunningDot from "./RunningDot";
import type { Phase } from "./shared";

interface Props {
  phase: Phase;
  /** 胶囊主标题（由宿主按阶段算好） */
  pillTitle: string;
  /** 胶囊副信息（由宿主按阶段算好） */
  pillMeta: string;
  /** 点开还原面板 */
  onExpand: () => void;
}

/**
 * 收起后的常驻胶囊：实时报进度，点开还原 —— 这是「分析不挡事」的关键。
 * 文案（标题/副信息）由宿主统一计算后传入，这里只负责渲染与动画。
 */
export default function AnalysisPill({ phase, pillTitle, pillMeta, onExpand }: Props) {
  return (
    <motion.button
      type="button"
      initial={{ opacity: 0, y: 12, scale: 0.96 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 12, scale: 0.96 }}
      transition={{ duration: 0.18 }}
      onClick={onExpand}
      aria-label="展开深度分析面板"
      className="fixed bottom-16 right-3 z-50 flex max-w-[86vw] items-center gap-2.5 rounded-full border border-slate-700 bg-slate-900/95 py-2 pl-3 pr-4 text-left shadow-2xl backdrop-blur sm:bottom-6 sm:right-6"
    >
      {phase === "running" ? (
        <RunningDot />
      ) : (
        <BarChart3 className="h-4 w-4 shrink-0 text-brand-light" aria-hidden />
      )}
      <span className="min-w-0">
        <span className="block truncate text-xs font-medium text-ink">{pillTitle}</span>
        <span className="block truncate text-xs text-ink-faint">{pillMeta}</span>
      </span>
    </motion.button>
  );
}
