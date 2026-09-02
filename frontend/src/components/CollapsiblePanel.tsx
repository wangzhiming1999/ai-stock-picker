import { useEffect, type ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown } from "lucide-react";
import { useCollapse } from "../lib/usePersist";

interface Props {
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

export default function CollapsiblePanel({ id, title, subtitle, defaultOpen = true, action, onToggle, children }: Props) {
  const { open, toggle } = useCollapse(id, defaultOpen);

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
    <section className="rounded-xl border border-slate-800 bg-slate-900/60">
      <div className="flex items-start justify-between gap-2 px-5 py-4">
        <button onClick={toggle} className="flex min-w-0 flex-1 items-start gap-2 text-left" aria-expanded={open}>
          <motion.span animate={{ rotate: open ? 0 : -90 }} transition={{ duration: 0.2 }} className="mt-0.5 shrink-0 text-slate-500">
            <ChevronDown className="h-4 w-4" />
          </motion.span>
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-slate-200">{title}</h3>
            {subtitle && <p className="mt-0.5 text-[11px] text-slate-500">{subtitle}</p>}
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
