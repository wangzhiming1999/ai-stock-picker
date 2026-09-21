import { useEffect, useRef, type ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown } from "lucide-react";
import { useBlockFocus } from "../../lib/blockFocus";
import { useCollapse } from "../../lib/usePersist";

interface Props {
  /**
   * 区块标识。用途有两个，都是硬依赖：
   *  1. 折叠状态记忆（`ai:collapse:<id>`）；
   *  2. **功能地图的落点**（`FeatureEntry.block` 指向它）。
   * 改名等于改落点 —— `featureMap.test.ts` 会拿它和功能地图里的 block 对账。
   */
  id: string;
  title: string;
  subtitle?: string;
  defaultOpen?: boolean;
  /** 右上角操作区 */
  action?: ReactNode;
  /** 折叠/展开时触发（如图表 resize） */
  onToggle?: (open: boolean) => void;
  children: ReactNode;
}

/**
 * 展开动画的时长（见下方 motion transition）。滚动要等它走完才开始，
 * 否则滚到的是**展开前**那个还很矮的位置。
 */
const EXPAND_MS = 250;
const SCROLL_DELAY_MS = EXPAND_MS;

export default function CollapsiblePanel({ id, title, subtitle, defaultOpen = true, action, onToggle, children }: Props) {
  const { open, toggle, setOpen } = useCollapse(id, defaultOpen);
  const sectionRef = useRef<HTMLElement>(null);

  // 功能地图点到这一块时：先展开（幂等，不是 toggle），再滚到眼前。
  useBlockFocus(id, () => {
    setOpen(true);
    window.setTimeout(
      () => sectionRef.current?.scrollIntoView({ block: "start", behavior: "smooth" }),
      SCROLL_DELAY_MS,
    );
  });

  useEffect(() => {
    onToggle?.(open);
    // 让图表等需要尺寸的组件在展开后重新布局
    if (open) {
      const t = setTimeout(() => window.dispatchEvent(new Event("resize")), 160);
      return () => clearTimeout(t);
    }
    return undefined;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  return (
    /* scroll-mt 抵消吸顶的顶栏 + 二级导航：不设的话滚过来的区块会被那两条带子盖住标题，
       看起来就像「跳过去了但那一块不见了」。56px = 二级导航条高度 + 一点呼吸位。 */
    <section
      ref={sectionRef}
      className="scroll-mt-[calc(var(--header-h)+56px)] rounded-2xl border border-slate-800 bg-slate-900"
    >
      <div className="flex items-start justify-between gap-2 px-5 py-4">
        <button onClick={toggle} className="flex min-w-0 flex-1 items-start gap-2 text-left" aria-expanded={open}>
          <motion.span animate={{ rotate: open ? 0 : -90 }} transition={{ duration: 0.2 }} className="mt-0.5 shrink-0 text-ink-faint">
            <ChevronDown className="h-4 w-4" aria-hidden />
          </motion.span>
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-ink">{title}</h3>
            {subtitle && <p className="mt-0.5 text-xs text-ink-faint">{subtitle}</p>}
          </div>
        </button>
        <div className="flex shrink-0 items-center gap-2">{action}</div>
      </div>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="panel-body"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
            className="overflow-hidden"
          >
            <div className="px-5 pb-5">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}
