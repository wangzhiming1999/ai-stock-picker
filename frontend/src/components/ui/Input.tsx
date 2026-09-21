import type { InputHTMLAttributes } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "../../lib/cn";

/**
 * 输入框变体表 · CVA
 *
 * 它负责的是**曾经不一致且不合规**的四件事：边框色、文字色、占位符色、校验态。
 * 核心两条（都来自 `lib/ui.ts` 的实测结论，值未改动）：
 *   1. 边框从 slate-700 提到 slate-500 —— slate-700 在暗底上只有 1.4~1.95:1，
 *      输入框的边界根本看不见（WCAG 1.4.11 要求 >= 3:1）。
 *   2. 焦点环由 index.css 的全局 :focus-visible 兜底，这里不再写 outline-none。
 *
 * ## 为什么 tone 用 CVA 的 variants 而不是三元表达式
 * 原注释已经指出过：「把正常 / 校验失败做成状态而不是在同一条 className 里写三元，
 * 是为了避免两个 border-* 同时出现在一个元素上」。CVA + `cn()` 把这条纪律
 * 从「作者记得住」变成「机制上做不到」—— 变体是互斥的键，一次只会取一个值。
 *
 * ## 尺寸也收进变体表
 * 此前尺寸散在调用点（`py-2.5 pl-9 pr-8` 这类）。`sm` 是历史用量的主力档，
 * `md` 给面板级搜索框。高度改用 `h-*` 而非 padding 撑，这样带左侧图标的
 * 搜索框只需给 `pl-*`，不会因为 padding 求和导致两个输入框差 2px。
 */
export const inputVariants = cva(
  "rounded-lg border bg-surface-raised text-ink-strong placeholder:text-ink-faint transition-colors",
  {
    variants: {
      tone: {
        /** 正常态。边框用 line-strong：它是输入框唯一的边界标识 */
        default: "border-surface-line-strong focus:border-brand-light",
        /** 校验失败 */
        danger: "border-state-danger-line text-state-danger-soft focus:border-red-500",
      },
      /**
       * ⚠️ 键名是 `fieldSize` 而**不是** `size` —— 原生 `<input>` 已有 `size`
       * 属性（数字，字符宽度），两者同名会让 `interface Props extends
       * InputHTMLAttributes & VariantProps` 直接编译失败。这是编译器帮我们拦下的，
       * 不要为了「名字好看」改回去。
       */
      fieldSize: {
        /** 表格筛选、行内搜索 */
        sm: "h-9 px-3 text-body",
        /** 面板内主搜索（历史用量最大） */
        md: "h-10 px-3 text-body",
        /** 全局顶栏搜索 */
        lg: "h-11 px-4 text-body",
      },
    },
    defaultVariants: {
      tone: "default",
      fieldSize: "md",
    },
  },
);

export type InputTone = NonNullable<VariantProps<typeof inputVariants>["tone"]>;
export type InputSize = NonNullable<VariantProps<typeof inputVariants>["fieldSize"]>;

interface Props
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "size">,
    VariantProps<typeof inputVariants> {}

/**
 * 全站唯一输入框。
 *
 * ⚠️ className 只传**宽度与布局**（`w-full` / `flex-1` / `pl-9` 给图标留位）。
 *    底色、边框、文字色、占位符、焦点态由 tone 决定；尺寸走 fieldSize，
 *    不要再用 `py-2.5` 这类 padding 覆盖 —— 会和 `h-*` 打架。
 */
export default function Input({ tone, fieldSize, className, ...rest }: Props) {
  return <input {...rest} className={cn(inputVariants({ tone, fieldSize }), className)} />;
}
