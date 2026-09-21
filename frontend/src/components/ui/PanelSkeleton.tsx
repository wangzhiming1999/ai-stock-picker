import { CARD } from "../../lib/ui";

interface Props {
  label: string;
}

/**
 * 面板级加载骨架：用于 lazy 组件的 Suspense fallback
 *
 * ⚠️ 这里曾是**最后一个**手写主卡类名的地方（`rounded-2xl border border-surface-line
 * bg-surface-panel p-5`），与 `CARD` 恰好等价，但那是巧合 —— 改 `CARD` 时这里不会跟着变。
 * 骨架是为了"让加载态看起来和真实内容一样大"，所以它**必须**和真卡片逐字同形，
 * 不能差一个圆角或一层底色，否则内容到位时会跳一下。
 * 现在直接复用 `CARD`，同形是机制保证的。
 *
 * 动画内层用 `surface-inset` 而不是色号：骨架的灰必须是表面阶梯里的一层，
 * 这样在四种表面上都不会出现"体系外的灰"。
 */
export default function PanelSkeleton({ label }: Props) {
  return (
    <div aria-busy="true" aria-label={label} className={CARD}>
      <div className="h-4 w-32 animate-pulse rounded-md bg-surface-inset" />
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div className="h-24 animate-pulse rounded-lg bg-surface-inset/70" />
        <div className="h-24 animate-pulse rounded-lg bg-surface-inset/70" />
      </div>
      <span className="sr-only">{label}</span>
    </div>
  );
}