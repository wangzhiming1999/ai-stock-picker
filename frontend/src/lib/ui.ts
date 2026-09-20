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
export const SECTION = "flex items-center gap-2 text-sm font-semibold text-ink";

/** ③ 分区（次级）：比 SECTION 弱一档，用于卡片内的次级小标题。 */
export const SECTION_SUB = "text-xs font-semibold text-ink-muted";

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
 * 字号档位。全站只保留这几档，禁止再出现 text-[9px] / text-[10px] / text-[11px]。
 * 暗底 + 小字 + 11px 是此前可读性差的主要原因（全站曾有 130 处 <12px）。
 */
export const TEXT = {
  /** 页面级标题（PageHeader 用） */
  h1: "text-xl font-semibold tracking-tight text-ink-strong sm:text-2xl",
  /** 24px 主结论：一屏只有一处 */
  hero: "text-2xl font-bold text-ink-strong",
  /** 18px 关键数字 */
  num: "text-lg font-semibold text-ink-strong",
  /** 16px 区块标题 */
  title: "text-base font-semibold text-ink-strong",
  /** 14px 正文 / 列表主文本 */
  body: "text-sm text-ink-soft",
  /** 12px 标签（在子块内作字段名） */
  label: "text-xs text-ink-muted",
  /** 12px 次要信息 / 注释 */
  meta: "text-xs text-ink-faint",
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

/** 面板标题行。 */
export const PANEL_TITLE = "flex items-center gap-2 text-sm font-semibold text-ink";

/** 面板副标题（说明这个面板回答什么问题）。 */
export const PANEL_DESC = "mt-0.5 text-xs text-ink-faint";

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
    "border border-surface-line-strong text-ink-soft hover:border-slate-400 hover:text-ink-strong",
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
  xs: "px-2.5 py-1 text-xs",
  /** 小：表格操作列、卡片内动作（历史用量最大） */
  sm: "px-3 py-1 text-xs",
  /** 中：表单提交 */
  md: "px-4 py-1.5 text-xs",
  /** 大：面板级主操作 */
  lg: "px-5 py-2 text-sm",
  /** 大 +：弹窗/空状态里的独立 CTA */
  xl: "px-6 py-2.5 text-sm",
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
export const STAT_VALUE = "text-lg font-bold";

/** 统计格的标签行 */
export const STAT_LABEL = "text-xs text-ink-faint";

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
