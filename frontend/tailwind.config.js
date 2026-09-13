/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        /**
         * 主色（结构色）：按钮底、激活态、链接、图标、评分强调。
         * 必须与 red / green 保持距离 —— 红绿已被行情语义独占（见 src/lib/tone.ts），
         * 主色若用红会同时表示「品牌 / 涨 / 风险」，红色将失去信息量。
         */
        brand: {
          DEFAULT: "#2563eb",
          dark: "#1d4ed8",
          light: "#60a5fa",
        },
      },
    },
  },
  plugins: [],
};
