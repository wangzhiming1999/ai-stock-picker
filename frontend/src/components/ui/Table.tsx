import type { ReactNode, ThHTMLAttributes } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "../../lib/cn";
import { CELL } from "../../lib/ui";

/**
 * 表格外壳 · 唯一写法
 *
 * ## 它解决的四个重复缺陷
 * 全站 17 张表此前各自手写外层容器，于是出现了四类不一致：
 *
 * 1. **表头底色**。有的写 `bg-surface-panel`（与卡片同色，滚动时表头"消失"），
 *    有的写 `bg-surface-inset`（与行hover同色，分不出表头）。统一用 `raised` ——
 *    它比卡面高一层，滚动时表头是明确浮在上面的。
 * 2. **滚动高度**。`max-h-64/80/96`、`[520px]`、`28rem`、无限制，五套写法。
 *    这是变体，不是巧合，收进 `maxHeight` 档位（xs/sm/md/lg/none）。
 * 3. **圆角与描边**。有的 `rounded-xl border`，有的裸 `overflow-auto` ——
 *    裸的那种在卡片里会看起来像内容"溢出"了。
 * 4. **minWidth**。每张表传自己的数字，导致同一页里两张表的横向滚动触发点不同。
 *
 * 用 `<Table>` 之后这些都在一处定义。需要非常规布局时用 `className` 覆盖宽度，
 * 不要复制这段结构。
 *
 * ## 2026-09-21：11 张存量手写表全部收编
 * `designGuard.test.ts` 里原本有一份 `TABLE_MIGRATION_PENDING` 豁免清单。
 * 本次把这 11 张（形态候选 / 导入预览 / 盯盘 / 历史预测 / 四维榜 / 推荐 /
 * 形态扫描 / 竞价 / 尾盘 / 扫描结果 / 策略）全部迁到本组件，
 * 清单随之清空 —— 守卫从此**零豁免**：任何新写的手写表格都会被立刻拦下。
 */

const shellVariants = cva("overflow-auto rounded-xl border border-surface-line", {
  variants: {
    maxHeight: {
      /** 卡片内的预览列表：只露 5~7 行，剩下的靠滚动（历史记录、推荐预览） */
      xs: "max-h-[300px]",
      /** 短表：板块、抱团这类 10~20 行 */
      sm: "max-h-[420px]",
      /** 默认：榜单主表 */
      md: "max-h-[560px]",
      /** 长表：扫描结果这类可能上百行 */
      lg: "max-h-[720px]",
      /** 不限制（配合内层分页、或由父级 flex 控制高度时用） */
      none: "",
    },
  },
  defaultVariants: { maxHeight: "md" },
});

export type TableMaxHeight = NonNullable<VariantProps<typeof shellVariants>["maxHeight"]>;

/**
 * 表头单元格。**所有 th 必须用它**，不要手写 className ——
 * 表头的对齐方式（左 / 右 / 中）是列语义，写在这里才能保证同一张表内一致。
 */
export function Th({
  align = "left",
  className,
  children,
  ...rest
}: ThHTMLAttributes<HTMLTableCellElement> & { align?: "left" | "right" | "center" }) {
  const ALIGN = { left: "text-left", right: "text-right", center: "text-center" } as const;
  return (
    <th scope="col" {...rest} className={cn(CELL, ALIGN[align], "text-meta font-medium", className)}>
      {children}
    </th>
  );
}

interface Props {
  /** 表头行（用 <tr> + <Th> 组装）。空表时传 null。 */
  head?: ReactNode;
  /** 表格主体的 <tr> 序列 */
  children: ReactNode;
  /**
   * 表格相对于容器的最小宽度，触发横向滚动。
   *
   * ⚠️ **可省略，且省略 ≠ 用默认值**：只有列多到会挤坏的表才需要给。
   * 窄表（3~5 列）给了反而凭空多出一条横向滚动条 ——
   * 所以这里刻意不留默认值，避免"抄一份忘了改"就多出一根滚动条。
   * 同一页里出现多张宽表时，给同一个值（横向滚动的触发点必须一致）。
   */
  minWidth?: number;
  maxHeight?: TableMaxHeight;
  /** 空状态。给了且没有数据时，渲染它而不是空表 */
  empty?: ReactNode;
  isEmpty?: boolean;
  className?: string;
  /** 无障碍标签：说明这张表是什么 */
  label: string;
}

/**
 * 表格外壳。
 *
 * 用法：
 * ```tsx
 * <Table label="三维选股榜" minWidth={880} head={<tr><Th>#</Th><Th align="right">现价</Th></tr>}>
 *   {items.map(it => <tr key={it.code}>...</tr>)}
 * </Table>
 * ```
 *
 * ⚠️ 表头必须用 `<Th>` 而不是 `<th className="...">`：那一层负责 `sticky top-0`
 *    与底色，手写的 <th> 会丢掉吸顶，长表滚动时列名就看不见了。
 */
export default function Table({
  head,
  children,
  minWidth,
  maxHeight,
  empty,
  isEmpty,
  className,
  label,
}: Props) {
  if (isEmpty && empty) {
    return <>{empty}</>;
  }
  return (
    <div className={cn(shellVariants({ maxHeight }), className)}>
      <table
        className="w-full text-body"
        style={minWidth ? { minWidth } : undefined}
        aria-label={label}
      >
        {head && (
          <thead className="sticky top-0 z-10 bg-surface-raised text-ink-muted backdrop-blur">{head}</thead>
        )}
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}