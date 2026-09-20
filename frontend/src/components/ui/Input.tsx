import type { InputHTMLAttributes } from "react";
import { INPUT_BASE, INPUT_TONE, type InputTone } from "../../lib/ui";

interface Props extends InputHTMLAttributes<HTMLInputElement> {
  /** 校验状态。默认 default（正常），校验失败传 danger。 */
  tone?: InputTone;
}

/**
 * 全站唯一输入框。
 *
 * 它负责的是**曾经不一致且不合规**的四件事：边框色、文字色、占位符色、校验态。
 * 具体见 lib/ui.ts 的 INPUT_BASE / INPUT_TONE 注释。核心两条：
 *   1. 边框从 slate-700 提到 slate-500 —— slate-700 在暗底上只有 1.4~1.95:1，
 *      输入框的边界根本看不见（WCAG 1.4.11 要求 >= 3:1）。
 *   2. 焦点环由 index.css 的全局 :focus-visible 兜底，这里不再写 outline-none。
 *
 * ⚠️ className 只传**底色、尺寸、宽度**（`bg-slate-950 px-3 py-2 text-sm w-full` 等）。
 *    不要再传 border-* / text-ink* / placeholder:* / focus:* —— 那些由 tone / INPUT_BASE 决定。
 */
export default function Input({ tone = "default", className = "", ...rest }: Props) {
  const cls = `${INPUT_BASE} ${INPUT_TONE[tone]} ${className}`.trim();
  return <input {...rest} className={cls} />;
}
