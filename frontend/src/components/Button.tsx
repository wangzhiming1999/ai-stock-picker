import type { ButtonHTMLAttributes, ReactNode } from "react";
import {
  BTN_BASE,
  BTN_SIZE,
  BTN_VARIANT,
  type ButtonSize,
  type ButtonVariant,
} from "../lib/ui";

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** 颜色语义。默认 primary（主操作）。 */
  variant?: ButtonVariant;
  /** 尺寸档。默认 sm（表格操作列、卡片内动作）。 */
  size?: ButtonSize;
  children: ReactNode;
}

/**
 * 全站唯一按钮。
 *
 * 三种交互态都不在这里写，而是由 index.css 全局兜底，避免 94 个调用点各写各的：
 *   焦点  → 全局 :focus-visible 给 2px 环（brand-light，实测 5.75:1，达标）
 *   禁用  → 全局 button:disabled 统一 opacity .5 + cursor:not-allowed
 *   按压  → 全局 button:not(:disabled):active 位移 0.5px
 *
 * ⚠️ className 只用来传**布局**类（mt-4 / w-full / flex-1 / ml-auto 等）。
 *    不要再传颜色（bg-* / text-*）、圆角（rounded-*）或尺寸（px-/py-/text-xs）——
 *    那些由 variant / size 决定，两者同时出现时由 Tailwind 的 CSS 输出顺序裁决，
 *    结果不可预期。
 */
export default function Button({
  variant = "primary",
  size = "sm",
  className = "",
  children,
  ...rest
}: Props) {
  const cls = `${BTN_BASE} ${BTN_VARIANT[variant]} ${BTN_SIZE[size]} ${className}`.trim();
  return (
    <button {...rest} className={cls}>
      {children}
    </button>
  );
}
