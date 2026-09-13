/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        /**
         * 主色（结构色 / 填充色）。
         *
         * ⚠️ 只能用作「填充」——按钮底、激活底、图标底、进度条。
         * 不要用作暗色背景上的文字色：实测 #2563eb 在 slate-900 上仅 3.45:1，
         * 在 slate-800 上仅 2.83:1，低于 WCAG AA 正文 4.5:1。
         * 暗底上的品牌色文字请用 `text-brand-light`（7.02:1）。
         *
         * 必须与 red / green 保持距离 —— 红绿已被行情语义独占（见 src/lib/tone.ts）。
         */
        brand: {
          DEFAULT: "#2563eb",
          dark: "#1d4ed8",
          light: "#60a5fa",
        },
        /**
         * 文字色阶梯（暗色主题专用）。
         *
         * 每一档都经过 WCAG 2.1 实测，在最暗的三种背景
         * （slate-950 页面 / slate-900 主卡 / slate-800 子块）上均 >= 4.5:1，
         * 因此任意层级组合都是安全的。
         *
         *   ink-faint   #8292ab  6.39  ← 提示、meta、脚注（最弱可用档）
         *   ink-muted   #94a3b8  7.87  ← 标签、表头、次要说明
         *   ink-soft    #cbd5e1 13.59  ← 正文
         *   ink         #e2e8f0 16.36  ← 标题、强调正文
         *   ink-strong  #f1f5f9 18.41  ← 页面级标题、大数字
         *
         * 反面：不要再用 `text-slate-500` / `text-slate-600` —— 实测 3.07 / 1.93，
         * 在暗底上不可读。它们的历史位置已全部迁移到 `ink-faint`。
         *
         * 注意：bg-slate-* / border-slate-* 不受此约束，仍用 Tailwind 原生档位。
         */
        ink: {
          strong: "#f1f5f9",
          DEFAULT: "#e2e8f0",
          soft: "#cbd5e1",
          muted: "#94a3b8",
          faint: "#8292ab",
        },
      },
    },
  },
  plugins: [],
};
