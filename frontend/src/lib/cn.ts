import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * 类名合并 · 组件层唯一的拼接入口
 *
 * ## 它解决的两个真实缺陷
 *
 * 1. **同类冲突不可预期**。Tailwind 里 `border-line` 和 `border-line-strong`
 *    是两个不同的 class，同时出现时**谁生效取决于 CSS 输出顺序**，不是后者覆盖前者。
 *    `lib/ui.ts` 的注释里已经踩过一次：「把正常/校验失败做成状态而不是在同一条
 *    className 里写三元，是为了避免两个 border-* 同时出现在一个元素上」。
 *    但那只约束了 Input 内部 —— 调用方传 `className="border-red-500"` 依然会撞。
 *    `twMerge` 按「后者胜」的语义裁决同类冲突，把不可预期变成可预期。
 *
 * 2. **调用方覆盖变体**。组件给了 `variant="outline"`，调用点想微调边框色时
 *    过去只能靠 CSS 顺序碰运气；现在 `cn(base, variants, className)` 保证
 *    `className` 一定赢 —— 这是 shadcn 那套 API 能成立的前提。
 *
 * ## 用法（固定顺序，不要调换）
 * ```ts
 * cn(BASE, variants({ variant, size }), className)
 * ```
 * 顺序即优先级：基础 < 变体 < 调用方覆盖。
 *
 * ## 不要拿它做什么
 * - 不要用它拼动态类名分段（如 `cn("text-" + color)`）—— Tailwind JIT 扫不到
 *   字面量会静默丢类，`twMerge` 也救不了。变体一律走 CVA 的 `variants` 映射。
 * - 不要在业务组件里直接 `cn("rounded-2xl border border-slate-800 bg-slate-900")`
 *   拼卡片 —— 那是 `lib/ui.ts` 明令禁止的手写组合，走 `<Panel>` / `CARD_*`。
 *   这个函数是给**组件内部**用的，不是给调用点绕过组件的。
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}