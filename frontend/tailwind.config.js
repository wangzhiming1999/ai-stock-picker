/** @type {import('tailwindcss').Config} */

/**
 * 设计系统 · 单一来源
 *
 * ⚠️ 本文件是**唯一**能定义视觉规范的地方。组件里出现的任何「临时数值」
 * （`text-[13px]` / `rounded-[5px]` / 手写色号）都是本文件的漏网之鱼，
 * 会被 `src/lib/designGuard.test.ts` 拦下。
 *
 * ── 四组 token，对应界面语言的四个维度 ──────────────────────────────
 *   字体 fontFamily      中文优先字体栈（此前**完全没有定义**，中文渲染靠系统默认）
 *   字号 fontSize        8 档语义阶梯，**每档自带行高**（此前全站 0 个 leading-*）
 *   边距 borderRadius / 节奏   圆角 5 档；垂直节奏 3 档（见 lib/ui.ts 的 STACK*）
 *   字色 colors          表面阶梯（surface）+ 文字阶梯（ink）+ 状态色（state）
 *
 * ── 改动前的硬约束 ──────────────────────────────────────────────────
 *   改 `surface` / `ink` / `state` 的任何色值 → 必须重跑 `npm run contrast`。
 *   那套值全部有 WCAG 实测支撑，不是审美选择。
 */

/**
 * `slate-*` 在本项目里**历史上就是**表面阶梯（bg-slate-900 = 主卡、
 * bg-slate-800/70 = 子块、border-slate-800 = 外框），只是当年选的 900/800
 * 两档只差 2~4% 亮度，层级糊成一片。
 *
 * 所以把最深的四档**重定向**到实测过的新阶梯：全站存量标记不改一个字就整体
 * 落到新层级上，避免出现「一半新一半旧」的过渡态（那比不改更难看）。
 * 浅档（100~600）保持 Tailwind 原值 —— 它们是文字色与交互描边，
 * 已由 `ink` / `line-strong` 接管，实测数记在 src/lib/ui.ts。
 */
const SLATE = {
  50: "#f8fafc",
  100: "#f1f5f9",
  200: "#e2e8f0",
  300: "#cbd5e1",
  400: "#94a3b8",
  500: "#64748b",
  600: "#475569",
  // ↓ 以下四档是覆盖值，语义见上方「表面阶梯」
  700: "#2b3a5a", // line
  800: "#141d30", // inset
  900: "#0d1424", // panel
  950: "#05070e", // canvas
};

export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    /* ── 字号阶梯（**覆盖**默认，不是 extend）─────────────────────────
     * 8 档，语义命名。**每档自带行高** —— 这是本次修复的核心。
     *
     * 此前全站 0 处 `leading-*`，行高全靠浏览器默认：中文 12px 的默认行高只有
     * 16px（1.33），而中文方块字的舒适行高需要 1.5~1.7。字一多就糊成一坨灰，
     * 这是「界面看起来一般」最主要的机械原因，不是配色问题。
     *
     * ⚠️ px 值与旧档位**一一对应，刻意不改** ——
     *    改尺寸会让所有卡片高度、表格行高同时变化，是无法逐个回归的改动。
     *    本次提升全部来自行高与语义化，布局零风险。
     *
     *   旧           新            用途
     *   text-xs   →  text-meta     注释 · 口径 · 脚注
     *   text-xs   →  text-label    字段名 · 表头（同尺寸，行高更紧）
     *   text-sm   →  text-body     正文 · 表格主文本   ← 默认档
     *   text-base →  text-head     区块 / 面板标题
     *   text-lg   →  text-num      关键数字 · 卡片主值
     *   text-xl   →  text-h1       页面标题
     *   text-2xl  →  text-hero     一屏一处的主结论
     *   text-[10px] → text-micro   角标 · 单位 · 图例
     *
     * 行高怎么定的：小字给更大比例（12px/18px = 1.5），大字给更小比例
     * （24px/32px = 1.33）。字越大，同样的行高比例看起来越松。
     *
     * ⚠️ 为什么写在这里而不是 `extend` —— 这一条踩过坑：
     *    `extend` 是**合并**，Tailwind 的 xs/sm/base/lg/xl/2xl 会继续存在。
     *    后果有两个，都很隐蔽：
     *      1. 写了旧档位**依然会生效**，只是没人用 —— 于是"迁移完成"没法验证；
     *      2. 守卫的注释里出现 `text-xs` 这类词，会被 content 扫描当成候选项，
     *         产出用不到的死 CSS（实测确实产出了 7 条）。
     *    改成覆盖后，旧档位**不再生成任何 CSS**：写了就是无样式（静默继承父级
     *    字号），而 `designGuard.test.ts` 是唯一的防线 —— 这正是它存在的意义。
     */
    fontSize: {
      micro: ["10px", { lineHeight: "14px", letterSpacing: "0.01em" }],
      meta: ["12px", { lineHeight: "18px" }],
      label: ["12px", { lineHeight: "16px" }],
      body: ["14px", { lineHeight: "22px" }],
      head: ["16px", { lineHeight: "24px", letterSpacing: "-0.005em" }],
      num: ["18px", { lineHeight: "26px", letterSpacing: "-0.01em" }],
      // 汉字在 20px 以上会显得比同尺寸拉丁文更大，所以大字收紧字距
      h1: ["20px", { lineHeight: "28px", letterSpacing: "-0.015em" }],
      hero: ["24px", { lineHeight: "32px", letterSpacing: "-0.02em" }],
      // 单卡片内的超大读数（如个股综合评分）。比 hero 更大，一屏最多一处
      display: ["32px", { lineHeight: "38px", letterSpacing: "-0.02em" }],
    },

    /* ── 圆角（**覆盖**默认）───────────────────────────────────────────
     * 收敛为 4 档 + full。层级与半径绑定（面越大、圆角越大），
     * 此前 6 档混用（rounded / md / lg / xl / 2xl / full）导致
     * 同一屏里出现 4px、6px、8px 三种「小圆角」，肉眼看得出不齐。
     *
     *   徽章 · chip           → rounded-md   6px
     *   按钮 · 输入框 · 小控件 → rounded-lg   8px   ← 默认档
     *   面板内分区            → rounded-xl   12px
     *   页面级面板            → rounded-2xl  16px
     *   胶囊 / 头像           → rounded-full
     *
     * 同上：覆盖而非 extend，`rounded`（裸，4px）与 `rounded-sm`（2px）
     * 从此不再生成 CSS。存量 63 处裸 `rounded` 已全部迁到 `rounded-md` ——
     * 裸值存在一天就会有人继续用。
     */
    borderRadius: {
      none: "0px",
      md: "6px",
      lg: "8px",
      xl: "12px",
      "2xl": "16px",
      full: "9999px",
    },

    extend: {
      /* ── 字体 ────────────────────────────────────────────────────────
       * 此前 fontFamily 未定义 → 吃 Tailwind 默认栈（ui-sans-serif / system-ui），
       * 中文实际落到浏览器默认：Windows 上是宋体或雅黑、macOS 上是苹方，
       * 同一份代码在两台机器上排版宽度不同（中文行折行位置不同 → 卡片高度不同）。
       *
       * 现在显式声明中文优先栈，且**只用系统字体**：
       * 不引 webfont —— 中文字体动辄 3~8MB，行情页首屏加载不起；
       * 且国内网络访问 Google Fonts 不稳定，会拖出 2s 的空白期。
       *
       * 顺序即优先级：拉丁字符先命中 Inter/系统 UI 字体，中文回退到下方三款。
       */
      fontFamily: {
        sans: [
          "Inter",
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "PingFang SC", // macOS / iOS
          "Hiragino Sans GB", // 旧 macOS
          "Microsoft YaHei", // Windows
          "Noto Sans SC", // Android / Linux
          "sans-serif",
        ],
        // 代码 / 股票代码 / 需要严格等宽的场合
        mono: [
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Consolas",
          "Liberation Mono",
          "monospace",
        ],
      },

      /* ── 边距 ────────────────────────────────────────────────────────
       * ⚠️ 刻意**不覆盖** Tailwind 的 spacing 阶梯 —— 那一套同时被
       *    width / height / inset 复用，覆盖它会波及所有布局尺寸。
       *
       * 边距的纪律靠**语义槽位 token** 落地（定义在 lib/ui.ts）：
       *
       *   表格单元格   CELL              px-3 py-2
       *   面板头部     PANEL_HEAD        px-5 py-4
       *   面板内容     PANEL_BODY        p-5
       *   主卡         CARD              p-5
       *   浮层         CARD_MODAL        p-6
       *   垂直节奏     STACK_TIGHT / STACK / STACK_LOOSE     space-y-2 / 4 / 8
       *
       * 实测全站 0 处任意值（没有 `p-[13px]` 这种写法），说明**数值本身是干净的**。
       * 此前的问题不是"数值乱写"，而是**同一个语义槽位在不同页面用了不同档位**
       * （表格单元格有过 px-2 py-2 与 px-3 py-1.5 两套，卡片内边距有过 p-4/p-5/p-6 三种）。
       * 所以收敛的正确做法是把**槽位命名**，而不是把数值统一改小 ——
       * 「所有卡片都是 p-5」这种全局替换会同时改掉弹窗与常驻条，那不是统一，是破坏。
       */

      colors: {
        slate: SLATE,

        /**
         * 语义表面阶梯。**新代码一律用这套名字** —— 语义比色值稳，
         * 将来换肤只动这一个映射，不用全站 grep 色号。
         */
        surface: {
          canvas: SLATE[950],
          panel: SLATE[900],
          inset: SLATE[800],
          raised: "#1b2640",
          line: SLATE[700],
          "line-soft": "#1a2438",
          "line-strong": SLATE[500],
          /** 交互元素 hover 时的描边。比 line-strong 再亮一档，让 hover 有可见反馈。 */
          "line-hover": "#94a3b8",
        },

        /**
         * 主色（结构色 / 填充色）。
         *
         * ⚠️ `brand` #2563eb **只能当填充** —— 按钮底、激活底、图标底、进度条。
         * 不要当暗底上的文字色：实测在 panel / inset / raised 上只有
         * 3.56 / 3.18 / 2.76:1，全低于 AA 正文 4.5:1。
         * 暗底上的品牌色文字用 `brand-light`（7.23:1）；焦点环同理。
         *
         * 必须与红/绿保持距离 —— 红绿已被行情语义独占（见 src/lib/tone.ts）。
         */
        brand: {
          DEFAULT: "#2563eb",
          /** 主按钮 hover 底。 */
          dark: "#1d4ed8",
          /** 暗底上的品牌色**文字** / 焦点环。white on brand = 5.17:1。 */
          light: "#60a5fa",
          /** 需要比 light 更强调的品牌色文字。 */
          soft: "#93c5fd",
        },

        /**
         * 文字色阶梯（暗色主题专用）。
         *
         * 五档全部在**四层表面**上实测 >= 4.5:1，所以任意层级组合都安全 ——
         * 组件不必知道自己被放在了哪一层上。改表面色或改这五个值都要重跑实测。
         *
         *   ink-faint   #7f90a8   canvas 6.19 / panel 5.65 / inset 5.17 / raised 4.62
         *   ink-muted   #94a3b8   7.85 / 7.17 / 6.56 / 5.86   标签、表头
         *   ink-soft    #cbd5e1  13.56 / 12.38 / 11.33 / 10.12  正文
         *   ink         #e2e8f0  16.33 / 14.91 / 13.65 / 12.19  标题
         *   ink-strong  #f8fafc  19.24 / 17.57 / 16.08 / 14.36  页面级标题、大数字
         *
         * ⚠️ **相邻两档必须拉开 >= 12% 相对亮度**（`tools/contrast.mjs` 断言 ⑥）。
         *    这不是审美要求：faint 原本是 #8fa0b8，与 muted(#94a3b8) 只差 **4.4%** ——
         *    「每档对背景都够亮」是满足的，但两档**互相**分辨不出，
         *    于是名义上五档、实际只有四档可用，混用久了就是「整屏发灰」。
         *    压低到 #7f90a8 后与 muted 差 24.1%，同时四层表面仍全部 >= 4.5:1。
         *    （raised 4.62:1 是这条约束的上限所在，不能再往下压。）
         *
         * 反面：不要再用 `text-slate-500` / `text-slate-600` 当文字色 ——
         * 实测只有 3.07 / 1.93:1，暗底上读不清。它们的旧位置已迁到 `ink-faint`。
         *
         * ⚠️ 用色纪律：`ink-faint` 是**最弱**一档，只给「可以完全忽略也不影响判断」
         *    的内容（口径出处、时间戳）。它的历史用量一度超过 `ink-soft`，
         *    结果整屏发灰 —— 正文该用 `ink-soft`，读数该用 `ink`。
         */
        ink: {
          strong: "#f8fafc",
          DEFAULT: "#e2e8f0",
          soft: "#cbd5e1",
          muted: "#94a3b8",
          faint: "#7f90a8",
        },

        /**
         * 状态色（**非行情语义**）。
         *
         * ⚠️ 这个分组与 `lib/tone.ts` 的红绿是两套东西，不要混用：
         *   tone.ts  红/绿 = 价格往哪走、买卖动作     ← 行情语义，不可挪用
         *   state    琥珀/红/蓝 = 这块功能的状态     ← 接口失败、数据缺失、信息提示
         *
         * 历史问题：全站散着 19 种手写状态色（amber-100/200/300/400/500、
         * red-200/300/400、sky-300/400、purple-300…），同一个「数据缺失」提示
         * 在不同页面深浅不一。这里收敛为四个状态 × 四个部位。
         *
         *   状态    用途                          可用部位
         *   warn    数据缺失 / 口径不全 / 风控阈值  text / soft / surface / line
         *   danger  接口失败 / 校验错误 / 破坏性操作 text / soft / surface / line
         *   info    中性说明 / 操作提示 / 链接      text / soft / surface / line
         *   ok      达标 / 已完成 / 校验通过        text / soft / surface / line
         *
         * `text` 用于普通暗底，`soft` 用于带色底的芯片内（底色已抬亮背景，
         * 文字要更亮才压得住）—— 与 tone.ts 的 300/400 双档是同一个道理。
         */
        state: {
          warn: {
            DEFAULT: "#fbbf24", // amber-400
            soft: "#fcd34d", // amber-300
            surface: "rgba(120, 53, 15, 0.18)", // amber-900 低透明底
            line: "rgba(120, 53, 15, 0.45)",
          },
          danger: {
            DEFAULT: "#f87171", // red-400
            soft: "#fca5a5", // red-300
            surface: "rgba(127, 29, 29, 0.30)", // red-900 低透明底
            line: "rgba(153, 27, 27, 0.55)",
          },
          info: {
            DEFAULT: "#7dd3fc", // sky-300
            soft: "#bae6fd", // sky-200
            surface: "rgba(12, 74, 110, 0.25)",
            line: "rgba(3, 105, 161, 0.45)",
          },
          ok: {
            DEFAULT: "#60a5fa", // brand-light
            soft: "#93c5fd", // brand-soft
            surface: "rgba(30, 64, 175, 0.18)",
            line: "rgba(29, 78, 216, 0.40)",
          },
        },
      },
    },
  },
  plugins: [],
};
