/**
 * 设计 token · 容器与排版
 *
 * 全站只用 3 层容器，靠"底色差 + 留白"建立层级，而不是靠"每个东西都套一个框"。
 * 此前同一套卡片有 12+ 种写法、内嵌块用了 7 档几乎同色的灰（亮度差 2~4%，
 * 人眼分辨不出），导致所有块看起来一样重 —— 这是界面"没有落点"的机械原因。
 *
 * 用法：
 *   <div className={CARD}>…</div>
 *   <div className={`${SUB} px-3 py-2 text-center`}>…</div>   // SUB 不带内边距，按需叠加
 *
 * 层级与半径绑定（面越大、圆角越大）：
 *   主卡 rounded-2xl ／ 子块 rounded-xl ／ 芯片·按钮·输入 rounded-lg ／ 胶囊 rounded-full
 *   紧凑档 rounded-md：只给高度 <= 24px 的徽章和分段控件（见下方说明）
 * 不要再手写 `rounded-lg border border-slate-800 bg-slate-900/60 p-5` 这类临时组合。
 *
 * ⚠️ rounded-md(6px) 曾被误判为「体系外、该并入 rounded-lg」。实测方向反了：
 *   它服务的是「止损 3」「买入 2」这类 20px 高的小徽章和登录页 tab 指示条，
 *   8px 圆角套上去接近胶囊形，比例失调，恰恰违反「面越大、圆角越大」。
 *   所以正式收录为紧凑档，而不是清除。
 *
 * ── 文字色规则（无障碍，硬约束）────────────────────────────────────
 * 文字色一律走 tailwind.config.js 的 `ink` 阶梯，**不要再用 text-slate-* 作为文字色**：
 *   ink-strong / ink / ink-soft / ink-muted / ink-faint
 * 每一档都实测过，在 slate-950 / 900 / 800 三种底色上均 >= 4.5:1（WCAG AA）。
 * 历史教训：全站曾有 210 处用 text-slate-500/600 当提示文字，实测只有 3.07 / 1.93:1，
 * 暗底上根本读不清 —— 这是"看着糊"的主因，不是审美问题。
 * bg-slate-* / border-slate-* 不受此约束，仍用 Tailwind 原生档位。
 */

/** ① 主卡：页面级面板。实底 + 细边框，与页面底色拉开亮度差。 */
export const CARD = "rounded-2xl border border-slate-800 bg-slate-900 p-5";

/** ① 主卡（无内边距变体）：内边距由子元素自己控制，例如带 sticky 表头的面板。 */
export const CARD_FLUSH = "rounded-2xl border border-slate-800 bg-slate-900";

/** ① 主卡（浮层）：Modal / 抽屉，额外带投影。 */
export const CARD_MODAL = "rounded-2xl border border-slate-800 bg-slate-900 p-6 shadow-2xl";

/**
 * ② 子块：主卡内部的浅底分区。无边框，只靠底色差区分。
 * 不携带内边距 —— 统计格用 `px-3 py-2`，内容块用 `p-3`。
 */
export const SUB = "rounded-xl bg-slate-800/70";

/** ② 子块（最弱档）：用于「嵌套在子块里」的第三层底色，避免继续加深。 */
export const SUB_QUIET = "rounded-lg bg-slate-800/40";

/** ③ 分区：不套容器。只有标题 + 上方留白，用于切分主卡内部的不同主题。 */
export const SECTION = "flex items-center gap-2 text-sm font-semibold text-ink";

/** ③ 分区（次级）：比 SECTION 弱一档，用于卡片内的次级小标题。 */
export const SECTION_SUB = "text-xs font-semibold text-ink-muted";

/** 分隔线：分区之间的细线，替代"再套一个框"。 */
export const DIVIDER = "border-t border-slate-800/60";

/**
 * 表格单元格内边距（td / th 共用同一节奏）。
 *
 * 此前 td/th 混用 `px-2 py-2` 与 `px-3 py-1.5` 两套节奏，导致不同面板的表格
 * 行高与列距不一致 —— 单看没问题，并排/切换时就会觉得"没对齐"。
 * 现在统一为 12px 水平 + 8px 垂直，落在 4px 网格上。
 */
export const CELL = "px-3 py-2";

/**
 * 字号档位。全站只保留这几档，禁止再出现 text-[9px] / text-[10px] / text-[11px]。
 * 暗底 + 小字 + 11px 是此前可读性差的主要原因（全站曾有 130 处 <12px）。
 */
export const TEXT = {
  /** 24px 主结论：一屏只有一处 */
  hero: "text-2xl font-bold text-white",
  /** 18px 关键数字 */
  num: "text-lg font-semibold text-white",
  /** 16px 区块标题 */
  title: "text-base font-semibold text-white",
  /** 14px 正文 / 列表主文本 */
  body: "text-sm text-ink-soft",
  /** 12px 标签（在子块内作字段名） */
  label: "text-xs text-ink-muted",
  /** 12px 次要信息 / 注释 */
  meta: "text-xs text-ink-faint",
} as const;

/* ── 交互原语 ────────────────────────────────────────────────────────
 * 此前 94 个 <button>、13 个 <input> 的类名**没有任何两个是相同的**，
 * 每种态（焦点/禁用/按压）都在各处手写或干脆没写 —— 这是界面不一致的机械原因。
 * 下面这套是唯一来源，组件（components/Button.tsx 等）消费它。
 *
 * 用 Button 组件，不要直接拼这些常量；常量导出只是为了在组件内部复用。
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
 * 注意 `outline` 的边框用 slate-500 而不是 slate-700：
 * 描边按钮的边框**就是**它唯一的形态标识，按 WCAG 1.4.11 需 >= 3:1。
 * 实测 slate-700 在 slate-900/800 上只有 1.72 / 1.41，slate-500 是 3.75 / 3.07。
 * （卡片那种纯装饰边框不受此约束，仍可用 slate-800。）
 */
export const BTN_VARIANT = {
  /** 主操作：提交、开始、确认 */
  primary: "bg-brand text-white hover:bg-brand-dark",
  /** 中性实底：次要动作但有分量 */
  neutral: "bg-slate-800 text-ink hover:bg-slate-700",
  /** 描边：并列的次要动作（hover 有底色反馈） */
  outline: "border border-slate-500 text-ink-soft hover:border-slate-400 hover:text-white",
  /** 描边（安静）：更弱的次要动作，hover 只提亮文字不加底 */
  outlineQuiet: "border border-slate-500 text-ink-muted hover:text-ink",
  /** 纯文字：最低优先级的动作（展开、切换、链接式） */
  ghost: "text-ink-muted hover:text-ink",
  /** 危险：卖出、清仓、删除 */
  danger: "bg-red-600 text-white hover:bg-red-500",
  /** 警戒：需要留意但非破坏性 */
  warn: "bg-amber-600 text-white hover:bg-amber-500",
  /** 信息：分析、推衍一类的中性重动作 */
  info: "bg-indigo-600 text-white hover:bg-indigo-500",
} as const;

export type ButtonVariant = keyof typeof BTN_VARIANT;

/**
 * 按钮尺寸。
 *
 * ⚠️ 这五档是从历史代码里**实际存在的组合**归纳出来的，不是重新设计的阶梯：
 * 迁移时按「最接近的档」归并，少数按钮会有 <= 4px 的宽高差。
 * 若要进一步收敛成 3 档（相邻档差 2px、人眼难辨），需单独确认。
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
  "rounded-lg border text-ink-strong placeholder:text-ink-faint transition-colors";

/**
 * 输入框状态色。
 *
 * `default` 的边框用 slate-500 而不是 slate-700：输入框的边框是**它唯一的边界标识**，
 * 按 WCAG 1.4.11 需要 >= 3:1。实测 slate-700 在 slate-950/900/800 三种底色上
 * 只有 1.95 / 1.72 / 1.41 —— 等于看不见输入框在哪；slate-500 是 4.24 / 3.75 / 3.07。
 *
 * 把「正常 / 校验失败」做成状态而不是在同一条 className 里写三元，
 * 是为了避免 border-slate-* 与 border-red-* 同时出现在一个元素上 ——
 * 那样谁生效取决于 Tailwind 的 CSS 输出顺序，不可预期。
 */
export const INPUT_TONE = {
  default: "border-slate-500 focus:border-brand-light",
  danger: "border-red-700 text-red-300 focus:border-red-500",
} as const;

export type InputTone = keyof typeof INPUT_TONE;

/**
 * 统计格：数字 + 标签的等宽单元。
 * 此前 `rounded-lg bg-slate-800/70 px-3 py-2 text-center` 逐字重复 17 次、
 * 散在 4 个文件里。用 <StatTile value label /> 代替。
 */
export const STAT = "rounded-lg bg-slate-800/70 px-3 py-2 text-center";

/** 统计格的数字行。基线不含颜色 —— 颜色由 StatTile 的 valueClass 决定，默认 text-ink。 */
export const STAT_VALUE = "text-lg font-bold";

/** 统计格的标签行 */
export const STAT_LABEL = "text-xs text-ink-faint";
