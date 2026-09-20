interface Props {
  label: string;
}

/** 面板级加载骨架：用于 lazy 组件的 Suspense fallback */
export default function PanelSkeleton({ label }: Props) {
  return (
    <div aria-busy="true" aria-label={label} className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
      <div className="h-4 w-32 animate-pulse rounded bg-slate-800" />
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div className="h-24 animate-pulse rounded-lg bg-slate-800/70" />
        <div className="h-24 animate-pulse rounded-lg bg-slate-800/70" />
      </div>
      <span className="sr-only">{label}</span>
    </div>
  );
}
