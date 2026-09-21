import { AnimatePresence, motion } from "framer-motion";
import { Compass, X } from "lucide-react";
import { FEATURES, type Domain, type FeatureEntry } from "../lib/featureMap";
import FeatureDirectory from "./FeatureDirectory";
import { CARD_FLUSH } from "../lib/ui";

interface Props {
  open: boolean;
  onClose: () => void;
  onGo: (f: FeatureEntry) => void;
  focusDomain?: Domain | null;
}

/**
 * 功能地图浮层 · 从任何页面都能打开
 *
 * 为什么是浮层而不是第四个一级 tab：一级导航的三项是**任务**（今天做什么、
 * 票从哪来、我手里有什么），而这是一张**索引**。把索引塞进任务导航会让
 * 「今日作战」和其他两项不再同级 —— 导航会重新变成"按功能类型切分"的老样子，
 * 那正是这个项目花过一次重构才摆脱的结构。
 */
export default function FeatureMapModal({ open, onClose, onGo, focusDomain }: Props) {
  if (!open) return null;

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 backdrop-blur-sm sm:p-6"
          onClick={onClose}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18 }}
        >
          <motion.div
            className={`${CARD_FLUSH} w-full max-w-2xl shadow-2xl`}
            onClick={(e) => e.stopPropagation()}
            initial={{ opacity: 0, scale: 0.96, y: -12 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97, y: -8 }}
            transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
          >
            <div className="flex items-start justify-between gap-3 border-b border-surface-line px-5 py-4">
              <div className="min-w-0">
                <h2 className="flex items-center gap-2 text-head font-bold text-white">
                  <Compass className="h-4 w-4 text-brand-light" aria-hidden />
                  功能地图
                </h2>
                <p className="mt-0.5 text-meta text-ink-soft">
                  共 {FEATURES.length} 项 · 点任意一项直接跳过去，不用先在三个 tab 里翻
                </p>
              </div>
              <button
                type="button"
                onClick={onClose}
                aria-label="关闭"
                className="shrink-0 rounded-lg p-1 text-ink-muted transition-colors hover:text-ink-soft"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="max-h-[70vh] overflow-y-auto px-5 py-4">
              <FeatureDirectory onGo={onGo} focusDomain={focusDomain} />

              <p className="mt-4 border-t border-surface-line-soft pt-3 text-meta leading-relaxed text-ink-soft">
                深度分析不在这张表里 —— 它在任意列表勾选股票，或直接用顶部搜索框输入代码打开，
                所以没有单独的入口可以点。
              </p>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
