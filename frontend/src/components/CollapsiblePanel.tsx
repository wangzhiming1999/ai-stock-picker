import { useEffect, type ReactNode } from "react";
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
      const t = setTimeout(() => window.dispatchEvent(new Event("resize")), 60);
      return () => clearTimeout(t);
    }
    return undefined;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/60">
      <div className="flex items-start justify-between gap-2 px-5 py-4">
        <button onClick={toggle} className="flex min-w-0 flex-1 items-start gap-2 text-left">
          <svg
            className={`mt-0.5 h-4 w-4 shrink-0 text-slate-500 transition-transform ${open ? "" : "-rotate-90"}`}
            viewBox="0 0 20 20"
            fill="currentColor"
          >
            <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.06l3.71-3.83a.75.75 0 111.08 1.04l-4.25 4.39a.75.75 0 01-1.08 0L5.21 8.27a.75.75 0 01.02-1.06z" clipRule="evenodd" />
          </svg>
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-slate-200">{title}</h3>
            {subtitle && <p className="mt-0.5 text-[11px] text-slate-500">{subtitle}</p>}
          </div>
        </button>
        <div className="flex shrink-0 items-center gap-2">{action}</div>
      </div>
      {open && <div className="px-5 pb-5">{children}</div>}
    </section>
  );
}
