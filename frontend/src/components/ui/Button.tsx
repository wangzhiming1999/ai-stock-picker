import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "../../lib/cn";

/**
 * 按钮变体表 · CVA
 *
 * ## 为什么从「字符串常量 + 手拼」改成 CVA
 * 上一版把类名放在 `lib/ui.ts` 的 `BTN_BASE / BTN_VARIANT / BTN_SIZE` 里导出，
 * 由本组件拼成一条 className。规范本身没问题，缺陷在于**约束只存在于注释里**：
 * 调用点想加个边框色，直接往 `className` 里塞 `border-red-500` 就行，
 * 与 `variant` 的 `border-*` 撞车后谁生效取决于 Tailwind 的 CSS 输出顺序。
 *
 * 现在改成 CVA 表达「变体 × 尺寸 = 类名」这张二维表，并用 `cn()` 做合并 ——
 * `className` 一定覆盖变体，而不是碰运气。同时 `buttonVariants` 被导出，
 * 于是「有哪些可用变体」是**可以在编译期和测试里检查的**，
 * 不再是只能靠读注释记住。
 *
 * ## 颜色值一个字都没动
 * 全部沿用 `lib/ui.ts` 的实测结论（含为何 `warn` 用 amber-700 而非 amber-600 的原因）。
 * 本次改造只换**组织方式**，不换**外观** —— 这一点是刻意的：
 * 那些对比度数字是跑 `npm run contrast` 实测出来的，换顺序可以，换值不行。
 *
 * ## 交互三态仍由 index.css 全局兜底（不要在这里重写）
 *   焦点 → 全局 :focus-visible 给 2px 环
 *   禁用 → 全局 button:disabled 统一 opacity .5 + cursor:not-allowed
 *   按压 → 全局 button:not(:disabled):active 位移 0.5px
 */

/** 结构层：布局 + 圆角 + 过渡。与颜色、尺寸无关。 */
const BTN_BASE =
  "inline-flex select-none items-center justify-center gap-1.5 whitespace-nowrap rounded-lg font-medium transition-colors";

/**
 * 变体 × 尺寸 二维表。
 *
 * ⚠️ 加新变体前先问：这个语义真的需要新色吗？红绿已被行情方向独占
 *    （见 `lib/tone.ts`），质量 / 证据类一律走主色 · 琥珀 · 中性灰。
 */
export const buttonVariants = cva(BTN_BASE, {
  variants: {
    variant: {
      /** 主操作：提交、开始、确认 */
      primary: "bg-brand text-white hover:bg-brand-dark",
      /** 中性实底：次要动作但有分量 */
      neutral: "bg-surface-raised text-ink hover:bg-surface-line",
      /**
       * 描边：并列的次要动作。
       * 边框用 `surface-line-strong`（#64748b）而不是 `surface-line` ——
       * 描边按钮的边框**就是**它唯一的形态标识，按 WCAG 1.4.11 需 >= 3:1。
       * 实测 line-strong 在四层上为 4.23 / 3.86 / 3.54 / 3.16；
       * 而 surface-line 只有 1.78 ~ 1.49，等于看不见按钮边界。
       */
      outline:
        "border border-surface-line-strong text-ink-soft hover:border-surface-line-hover hover:text-ink-strong",
      /** 描边（安静）：更弱的次要动作，hover 只提亮文字不加底 */
      outlineQuiet: "border border-surface-line-strong text-ink-muted hover:text-ink",
      /** 纯文字：最低优先级的动作（展开、切换、链接式） */
      ghost: "text-ink-muted hover:text-ink",
      /** 危险：卖出、清仓、删除 */
      danger: "bg-red-600 text-white hover:bg-red-500",
      /** 警戒：需要留意但非破坏性。amber-700 而非 600 —— white on 600 只有 3.19:1，不达 AA */
      warn: "bg-amber-700 text-white hover:bg-amber-600",
      /** 信息：分析、推衍一类的中性重动作 */
      info: "bg-indigo-600 text-white hover:bg-indigo-500",
    },
    /**
     * 尺寸五档。这些是从历史代码里实际存在的组合归纳出来的，不是新设计的阶梯；
     * 迁移时按「最接近的档」归并，少数按钮有 <= 4px 的宽高差。
     */
    size: {
      /** 极小：标签行内的小动作 */
      xs: "px-2.5 py-1 text-meta",
      /** 小：表格操作列、卡片内动作（历史用量最大） */
      sm: "px-3 py-1 text-meta",
      /** 中：表单提交 */
      md: "px-4 py-1.5 text-meta",
      /** 大：面板级主操作 */
      lg: "px-5 py-2 text-body",
      /** 大 +：弹窗/空状态里的独立 CTA */
      xl: "px-6 py-2.5 text-body",
    },
  },
  defaultVariants: {
    variant: "primary",
    size: "sm",
  },
});

export type ButtonVariant = NonNullable<VariantProps<typeof buttonVariants>["variant"]>;
export type ButtonSize = NonNullable<VariantProps<typeof buttonVariants>["size"]>;

interface Props extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  children: ReactNode;
}

/**
 * 全站唯一按钮。
 *
 * ⚠️ className 只用来传**布局**类（mt-4 / w-full / flex-1 / ml-auto 等）。
 *    颜色（bg-* / text-*）、圆角（rounded-*）、尺寸（px-/py-/text-meta）由
 *    variant / size 决定 —— 传了也不会「两个都生效」，`cn()` 会让 className 赢，
 *    但那意味着你绕过了变体表，下次改主题时这一处不会被改到。
 */
export default function Button({ variant, size, className, children, ...rest }: Props) {
  return (
    <button {...rest} className={cn(buttonVariants({ variant, size }), className)}>
      {children}
    </button>
  );
}