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
 * 不要再手写 `rounded-lg border border-slate-800 bg-slate-900/60 p-5` 这类临时组合。
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
