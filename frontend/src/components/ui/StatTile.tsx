import type { ReactNode } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "../../lib/cn";

/**
 * 统计格变体表 · CVA
 *
 * ## 为什么加 size
 * 此前只有一种尺寸，在两种场景里都不合适：持仓卡片顶部需要一档更大的数字，
 * 而面板内的密集读数区又需要更小。两个调用点各自 `className` 覆盖字号的结果，
 * 是全站出现了三套不一样的统计格。
 *
 * ## valueClass 为什么不并进变体表
 * 数字颜色是**数据语义**（走 `pnlTone` / `pctTone` / `scoreTone` 算出来的），
 * 不是展示样式 —— 同一个统计格里放涨跌幅是红、放胜率是蓝，
 * 取决于传进来的那个数。所以它必须留在运行时传入，但合并走 `cn()`，
 * 保证语义色一定覆盖默认色。
 */
export const statTileVariants = cva("rounded-lg bg-surface-inset text-center", {
  variants: {
    size: {
      /** 密集读数区（面板内、表格上方） */
      sm: "px-2.5 py-1.5",
      /** 默认：卡片内统计格 */
      md: "px-3 py-2",
      /** 大：页面级合计（持仓市值、总盈亏） */
      lg: "px-4 py-2.5",
    },
  },
  defaultVariants: { size: "md" },
});

const STAT_VALUE_SIZE = {
  sm: "text-body font-bold",
  md: "text-num font-bold",
  lg: "text-h1 font-bold",
} as const;

export type StatTileSize = NonNullable<VariantProps<typeof statTileVariants>["size"]>;

interface Props {
  /** 数值本身（已格式化好的文案，如 "1,234" / "+2.31%"） */
  value: ReactNode;
  /** 这个数字是什么 */
  label: string;
  /**
   * 数字的颜色类。需要按语义上色时传 tone 函数的返回值，如
   * `valueClass={pnlTone(totalPnl)}` / `valueClass={pctTone(hitRate)}`。
   * 不传则用默认色 text-ink。
   */
  valueClass?: string;
  size?: StatTileSize;
  className?: string;
}

/**
 * 统计格：一个数字 + 一行标签的等宽单元。
 *
 * 此前这套结构在 4 个文件里逐字重复了 17 次
 * （PortfolioPanel / PredictionCard / SimPanel / WinratePanel），
 * 底色、内边距、字号、字重全靠复制 —— 改一次要动 17 处。
 */
export default function StatTile({ value, label, valueClass, size = "md", className }: Props) {
  return (
    <div className={cn(statTileVariants({ size }), className)}>
      <div className={cn(STAT_VALUE_SIZE[size], valueClass ?? "text-ink")}>{value}</div>
      <div className="text-meta text-ink-muted">{label}</div>
    </div>
  );
}
