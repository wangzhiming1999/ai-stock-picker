/**
 * 设计 token · 单一来源（视觉 v2，2026-09-20 重构）
 *
 * ## 这一版修的是什么
 * 上一版已经统一了「字色 / 按钮 / 输入框」，但**层级**没统一：全站仍有 7 档
 * 几乎同色的灰，相对亮度差只有 2~4%，人眼分辨不出。结果每个块看起来一样重，
 * 界面没有落点 —— 这不是审美问题，是机械性缺陷。
 *
 * v2 把表面收敛成**四层**，相邻层相对亮度差 37%~70%（`npm run contrast` 守卫生效）：
 *
 *   canvas  #05070e  页面底
 *   panel   #0d1424  主面板      ← 与 canvas 差 69.7%
 *   inset   #141d30  面板内分区  ← 与 panel  差 42.5%
 *   raised  #1b2640  芯片/输入框 ← 与 inset  差 37.6%
 *
 * 用法上多了一条硬规则：**容器要么用 <Panel> 组件、要么用 CARD_*，不要手写
 * `rounded-2xl border border-... bg-... p-5` 这类临时组合。** 手写组合是上一版
 * 「12+ 种卡片写法」的来源，本次重构已把它们全部收编。
 *
 * ## 文字色（无障碍，硬约束）
 * 一律走 tailwind.config.js 的 `ink` 阶梯，**不要再用 `text-slate-*` 当文字色**：
 *   ink-strong / ink / ink-soft / ink-muted / ink-faint
 * 五档在四层表面上全部 >= 4.5:1，所以组件不必知道自己被放在哪一层上。
 * 历史教训：全站曾有 210 处用 text-slate-500/600 当提示文字，实测只有 3.07 / 1.93:1。
 *
 * ## 字号（v3 新增，2026-09-21）
 * 尺寸只认 tailwind.config.js 的 `fontSize` 阶梯（8 档，**每档自带行高**）：
 *   micro 10 / meta 12 / label 12 / body 14 / head 16 / num 18 / h1 20 / hero 24
 * 组件里**禁止**再写裸档位（text-xs / text-sm / text-base / text-lg / text-xl /
 * text-2xl / text-[13px]）—— 它们已不参与构建，写了就是无样式，
 * `designGuard.test.ts` 会报出来。
 *
 * 本次修的是**阶梯塌陷**：迁移前全站 557 处 text-xs、183 处 text-sm，
 * 即八成文字是同一个 12px，而且全站 0 处 `leading-*` —— 中文 12px 的浏览器
 * 默认行高只有 16px（1.33），字一多就糊成一坨灰。这不是配色问题，
 * 是「一屏之内所有字一样大 + 行高过紧」的机械缺陷。
 *
 * ## 字体族
 * 定义在 tailwind.config.js 的 `fontFamily.sans`：中文优先系统字体栈
 * （PingFang SC / Microsoft YaHei / Noto Sans SC），不引 webfont。
 *
 * ## 表面（底色 / 描边）
 * 用 `surface-*` 语义名（surface-panel / surface-inset / surface-line …），
 * 或等价的历史别名 `slate-800` / `slate-900`（已在 tailwind.config.js 重定向到同一套值）。
 *
 * ⚠️ 两处踩过的坑，改这一层之前先读：
 *   1. **Tailwind 扫描陷阱**：tone.ts 靠字面量产 class，动态拼接会被 JIT 静默丢掉。
 *   2. **编辑落盘陷阱**：Vite dev 常驻监听，批量 Edit 偶发「success 但盘上未变」，
 *      批量改完必须 grep 复验。
 */

/* ── 表面阶梯（语义名 → 类名）───────────────────────────────────────
 * 需要拼 `bg-*` / `border-*` 时用这里，不要在组件里写具体色号。
 */
export const SURFACE = {
  /** 页面底 */
  canvas: "bg-surface-canvas",
  /** 主面板底 */
  panel: "bg-surface-panel",
  /** 面板内分区底 */
  inset: "bg-surface-inset",
  /** 芯片 / 输入框 / 分段控件底 */
  raised: "bg-surface-raised",
  /** 装饰性描边（卡片外框） */
  line: "border-surface-line",
  /** 表内分隔线 */
  lineSoft: "border-surface-line-soft",
  /** 交互元素描边（WCAG 1.4.11 要求 >= 3:1） */
  lineStrong: "border-surface-line-strong",
} as const;

/** 页面级栅格。全站只有这一个宽度 —— 宽度不统一是「对不齐」的主要来源。 */
export const PAGE_WRAP = "mx-auto w-full max-w-[1360px] px-4 sm:px-6 lg:px-8";

/* ── 容器 ────────────────────────────────────────────────────────────
 * 三层容器，靠「底色差 + 留白」建立层级，而不是「每个东西都套一个框」。
 * 层级与半径绑定（面越大、圆角越大）：
 *   主卡 rounded-2xl ／ 子块 rounded-xl ／ 芯片·按钮·输入 rounded-lg ／ 紧凑徽章 rounded-md
 */

/** ① 主卡：页面级面板。实底 + 细边框，与页面底色拉开亮度差。 */
export const CARD = "rounded-2xl border border-surface-line bg-surface-panel p-5";

/** ① 主卡（无内边距变体）：内边距由子元素控制，例如带 sticky 表头的面板。 */
export const CARD_FLUSH = "rounded-2xl border border-surface-line bg-surface-panel";

/** ① 主卡（浮层）：Modal / 抽屉，额外带投影。 */
export const CARD_MODAL = "rounded-2xl border border-surface-line bg-surface-panel p-6 shadow-2xl";

/** ② 子块：主卡内部的浅底分区。无边框，只靠底色差区分，不携带内边距。 */
export const SUB = "rounded-xl bg-surface-inset";

/** ② 子块（嵌套档）：嵌在子块里的第三层，比 inset 再抬一档，避免"继续加深看不出"。 */
export const SUB_QUIET = "rounded-lg bg-surface-raised/60";

/** ③ 分区：不套容器，只有标题 + 上方留白，用于切分主卡内部的不同主题。 */
export const SECTION = "flex items-center gap-2 text-body font-semibold text-ink";

/** ③ 分区（次级）：比 SECTION 弱一档，用于卡片内的次级小标题。 */
export const SECTION_SUB = "text-label font-semibold text-ink-muted";

/** 分隔线：分区之间的细线，替代"再套一个框"。 */
export const DIVIDER = "border-t border-surface-line-soft";

/**
 * 表格单元格内边距（td / th 共用同一节奏）。
 *
 * 此前 td/th 混用 `px-2 py-2` 与 `px-3 py-1.5` 两套节奏，导致不同面板的表格
 * 行高与列距不一致 —— 单看没问题，并排/切换时就会觉得"没对齐"。
 * 统一为 12px 水平 + 8px 垂直，落在 4px 网格上。
 */
export const CELL = "px-3 py-2";

/**
 * 排版档位（字号 + 字重 + 字色 的**语义组合**）。
 *
 * 尺寸本身定义在 tailwind.config.js 的 `fontSize` 阶梯里（8 档，每档自带行高），
 * 这里只负责「这个位置该用哪一档、配什么字重和颜色」。
 * 分开的理由：尺寸是全站唯一事实，组合方式却是有限的几种固定搭配。
 *
 * ⚠️ 组件里不要再手写 `className="text-meta text-ink-faint"` 这类组合，
 *    直接用这里的一档 —— 否则「同一个位置两种写法」会重新长出来，
 *    `designGuard.test.ts` 会拦。
 *
 * 字色用色纪律（这是「整屏发灰」的解药）：
 *   ink-strong  标题 / 大数字          一屏只有少数几处
 *   ink         面板标题 / 读数
 *   ink-soft    正文                    ← 默认档，用得最多
 *   ink-muted   字段名 / 表头
 *   ink-faint   注释 / 口径 / 时间戳     **可以完全忽略也不影响判断**的内容才用
 *
 * ── 四类内容的分界（2026-09-21 按这条线把 375 处 ink-faint 重新分流）────
 *   免责 / 合规声明            → faint   （页脚免责就是这个层级，不该和读数抢注意力）
 *   口径 / 方法 / 证据 / 样本说明 → faint
 *   空态 / 加载态               → soft    （此刻它是屏幕上唯一的内容，必须可读）
 *   正文 / 列表项 / 读数 / 空态   → soft
 *   字段名 / 表头 / 统计标签 / 股票代码 / 名次 / 单位 / 状态 → muted
 *   控件（按钮 / 图标按钮）      → muted   （静止态压在 faint 上等于找不到可点）
 *
 * 分流之前：faint 375 处 > soft 141 处 —— 正文、读数、字段名全挤在最弱一档，
 * 这就是「整屏发灰」的机械原因。分流之后 faint 69 / muted 437 / soft 253。
 *
 * ⚠️ 分流只解决了「用错档」，没解决「两档看着一样」：
 *    `ink-muted`(#94a3b8) 与 `ink-faint`(#8fa0b8) 的相对亮度当时只差 **4.4%** ——
 *    每档对背景都够亮，但两档**互相**分辨不出，五档名义存在、实际只有四档可用。
 *    「标签」和「口径」这两层的区分因此形同虚设，混用久了还是发灰。
 *
 *    已修：`ink-faint` 压到 `#7f90a8`（对四层表面仍全部 >= 4.5:1，
 *    与 `muted` 拉开 24.1%）。**注意 4.62:1 就是这条约束的上限** ——
 *    再往下压就会在 `raised` 上跌破 AA，所以 `faint` 不可能更暗了。
 *    判据已进 `tools/contrast.mjs` 断言 ⑥（相邻两档 >= 12%），
 *    改任一档色值都会立刻被拦下。
 */
export const TEXT = {
  /** 页面级标题（PageHeader 用）20px */
  h1: "text-h1 font-semibold text-ink-strong",
  /** 主结论：一屏只有一处 24px */
  hero: "text-hero font-bold text-ink-strong",
  /** 关键数字 / 卡片主值 18px */
  num: "text-num font-semibold text-ink-strong",
  /** 区块标题 · 面板标题 16px */
  head: "text-head font-semibold text-ink",
  /** 卡内小标题 14px */
  title: "text-body font-semibold text-ink",
  /** 正文 / 列表主文本 / 表格 14px */
  body: "text-body text-ink-soft",
  /** 字段名 / 表头 12px（行高更紧，配 medium 与正文区分） */
  label: "text-label font-medium text-ink-muted",
  /** 注释 / 口径 / 脚注 12px */
  meta: "text-meta text-ink-faint",
  /** 角标 / 单位 / 图例 10px */
  micro: "text-micro text-ink-faint",
} as const;

/* ── 面板骨架 ────────────────────────────────────────────────────────
 * 配合 <Panel> 组件使用；直接用常量是为了让「同一层级的面板长得一样」
 * 变成机械保证，而不是靠每个作者记得住。
 */

/** 面板头部：图标 + 标题 + 副标题 + 右侧操作区，与内容之间一条弱分隔线。 */
export const PANEL_HEAD =
  "flex items-start justify-between gap-3 border-b border-surface-line-soft px-5 py-4";

/** 面板内容区。 */
export const PANEL_BODY = "p-5";

/** 面板标题行。16px —— 面板标题必须比面板内的正文大一档，否则「一块一块」看不出边界。 */
export const PANEL_TITLE = "flex items-center gap-2 text-head font-semibold text-ink";

/** 面板副标题（说明这个面板回答什么问题）。→ muted：它是字段位，不是正文 */
export const PANEL_DESC = "mt-1 text-meta text-ink-muted";

/** 面板头部右侧的操作区。 */
export const PANEL_ACTIONS = "flex shrink-0 items-center gap-2";

/* ── 交互原语 ────────────────────────────────────────────────────────
 * 此前 94 个 <button>、13 个 <input> 的类名**没有任何两个是相同的**，
 * 每种态（焦点/禁用/按压）都在各处手写或干脆没写 —— 这是界面不一致的机械原因。
 * 下面这套是唯一来源，组件（components/ui/Button.tsx 等）消费它。
 *
 * 用 Button / Input 组件，不要直接拼这些常量；常量导出只是为了在组件内部复用。
 */

/**
 * 按钮结构层：布局 + 圆角 + 过渡。与颜色无关。
 *
 * 不用在这里写 focus-visible / disabled / active —— 三者都由 index.css 全局兜底，
 * 见该文件的「键盘焦点环」「禁用态统一」「按压反馈」三段。
 */
export const BTN_BASE =
  "inline-flex select-none items-center justify-center gap-1.5 whitespace-nowrap rounded-lg font-medium transition-colors";

/**
 * 按钮颜色变体。
 *
 * 注意 `outline` 的边框用 `surface-line-strong`（= slate-500，#64748b）而不是
 * `surface-line`：描边按钮的边框**就是**它唯一的形态标识，按 WCAG 1.4.11 需 >= 3:1。
 * 实测 line-strong 在 canvas/panel/inset/raised 上为 4.23 / 3.86 / 3.54 / 3.16；
 * 而 surface-line 只有 1.78 ~ 1.49 —— 等于看不见按钮边界。
 * （卡片那种纯装饰边框不受此约束，仍用 surface-line。）
 *
 * ⚠️ `warn` 用 amber-700 而不是 amber-600：实测 white on amber-600 只有 3.19:1，
 * 不达 AA；amber-700 是 5.02:1。这是本次重构修掉的一处真实可达性缺陷。
 */
export const BTN_VARIANT = {
  /** 主操作：提交、开始、确认 */
  primary: "bg-brand text-white hover:bg-brand-dark",
  /** 中性实底：次要动作但有分量 */
  neutral: "bg-surface-raised text-ink hover:bg-surface-line",
  /** 描边：并列的次要动作（hover 有底色反馈） */
  outline:
    "border border-surface-line-strong text-ink-soft hover:border-surface-line-hover hover:text-ink-strong",
  /** 描边（安静）：更弱的次要动作，hover 只提亮文字不加底 */
  outlineQuiet: "border border-surface-line-strong text-ink-muted hover:text-ink",
  /** 纯文字：最低优先级的动作（展开、切换、链接式） */
  ghost: "text-ink-muted hover:text-ink",
  /** 危险：卖出、清仓、删除 */
  danger: "bg-red-600 text-white hover:bg-red-500",
  /** 警戒：需要留意但非破坏性 */
  warn: "bg-amber-700 text-white hover:bg-amber-600",
  /** 信息：分析、推衍一类的中性重动作 */
  info: "bg-indigo-600 text-white hover:bg-indigo-500",
} as const;

export type ButtonVariant = keyof typeof BTN_VARIANT;

/**
 * 按钮尺寸。
 *
 * ⚠️ 这五档是从历史代码里**实际存在的组合**归纳出来的，不是重新设计的阶梯：
 * 迁移时按「最接近的档」归并，少数按钮会有 <= 4px 的宽高差。
 */
export const BTN_SIZE = {
  /** 极小：标签行内的小动作 */
  xs: "px-2.5 py-1 text-label",
  /** 小：表格操作列、卡片内动作（历史用量最大） */
  sm: "px-3 py-1 text-label",
  /** 中：表单提交 */
  md: "px-4 py-1.5 text-label",
  /** 大：面板级主操作 */
  lg: "px-5 py-2 text-body",
  /** 大 +：弹窗/空状态里的独立 CTA */
  xl: "px-6 py-2.5 text-body",
} as const;

export type ButtonSize = keyof typeof BTN_SIZE;

/**
 * 输入框固定部分：圆角 + 文字色 + 占位符 + 过渡。
 *
 * 不含边框色 —— 边框色是**状态**，由 INPUT_TONE 决定。
 * 不含底色与尺寸：各调用点的底色（页面 / 卡内）和尺寸本就不同，
 * 由调用方通过 className 给，避免同族类互相覆盖时结果不可预期。
 */
export const INPUT_BASE =
  "rounded-lg border bg-surface-raised text-ink-strong placeholder:text-ink-faint transition-colors";

/**
 * 输入框状态色。
 *
 * `default` 用 `surface-line-strong`（#64748b）：输入框的边框是**它唯一的边界
 * 标识**，按 WCAG 1.4.11 需 >= 3:1。实测在 canvas/panel/inset/raised 上是
 * 4.23 / 3.86 / 3.54 / 3.16 —— 都达标。
 * 反面：slate-700（现 surface-line）只有 1.78 ~ 1.49，等于看不见框在哪。
 *
 * 把「正常 / 校验失败」做成状态而不是在同一条 className 里写三元，
 * 是为了避免两个 border-* 同时出现在一个元素上 —— 那样谁生效取决于
 * Tailwind 的 CSS 输出顺序，不可预期。
 */
export const INPUT_TONE = {
  default: "border-surface-line-strong focus:border-brand-light",
  danger: "border-red-700 text-red-300 focus:border-red-500",
} as const;

export type InputTone = keyof typeof INPUT_TONE;

/**
 * 统计格：数字 + 标签的等宽单元。
 * 此前 `rounded-lg bg-slate-800/70 px-3 py-2 text-center` 逐字重复 17 次、
 * 散在 4 个文件里。用 <StatTile value label /> 代替。
 */
export const STAT = "rounded-lg bg-surface-inset px-3 py-2 text-center";

/** 统计格的数字行。基线不含颜色 —— 颜色由 StatTile 的 valueClass 决定。 */
export const STAT_VALUE = "text-num font-bold";

/** 统计格的标签行。→ muted：标签与读数是两档，否则数字看不出是数 */
export const STAT_LABEL = "text-label text-ink-muted";

/* ── 节奏 ────────────────────────────────────────────────────────────
 * 垂直间距只有三档，用 `space-y-*` 的语义别名表达"这组东西有多强的关系"。
 * 历史问题：同一页里 space-y-3/4/5/6/8 混用，视觉上分不出分组边界。
 */

/** 同一组内的条目（列表、表格行） */
export const STACK_TIGHT = "space-y-2";
/** 同一页里并列的区块（面板与面板之间） */
export const STACK = "space-y-4";
/** 跨主题的大分组 */
export const STACK_LOOSE = "space-y-8";
