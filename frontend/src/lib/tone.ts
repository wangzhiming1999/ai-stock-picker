/**
 * 全站色调解算 · 单一来源
 *
 * 配色约定（A 股惯例）：
 *   红 = 上涨 / 看多 / 买入 / 加仓
 *   绿 = 下跌 / 看空 / 卖出 / 减仓
 *   琥珀 = 方向不明（震荡）
 *
 * 涨跌数值、大盘方向、买卖动作的颜色一律走这里，组件内不要再手写三元判断 ——
 * 否则同一份数据会在不同页面呈现相反颜色（历史 bug，详见 memory/2026-09-13）。
 *
 * 不适用：质量类评分（信号强度、胜率、条件通过项）不属于「方向」语义，
 * 不要复用 pnlTone / dirTone。
 */

/** 文本色强度档位：普通暗底用 400，浅色块内用 300，密集小字用 500 */
export type ToneLevel = 300 | 400 | 500;

const UP_TEXT: Record<ToneLevel, string> = {
  300: "text-red-300",
  400: "text-red-400",
  500: "text-red-500",
};

const DOWN_TEXT: Record<ToneLevel, string> = {
  300: "text-green-300",
  400: "text-green-400",
  500: "text-green-500",
};

const NEUTRAL_TEXT: Record<ToneLevel, string> = {
  300: "text-slate-300",
  400: "text-slate-400",
  500: "text-slate-500",
};

/** 数值涨跌配色（红涨绿跌）。null / NaN 返回中性色。 */
export function pnlTone(v: number | null | undefined, level: ToneLevel = 400): string {
  if (v == null || Number.isNaN(v)) return NEUTRAL_TEXT[level];
  return v >= 0 ? UP_TEXT[level] : DOWN_TEXT[level];
}

/** 固定方向色（不依据数值）：用于「上涨家数 / 下跌家数」这类只表达方向的展示。 */
export function upTone(level: ToneLevel = 400): string {
  return UP_TEXT[level];
}

export function downTone(level: ToneLevel = 400): string {
  return DOWN_TEXT[level];
}

export interface DirTone {
  /** 文字色 */
  text: string;
  /** 同色系淡底，用于整块区域背景 */
  bg: string;
}

/**
 * 大盘 / 指数方向配色。
 * 关键词与后端 `market_prediction.normalize_direction()` 严格对齐，
 * 避免 raw 文案（如「建议空仓」）与归一化结果（震荡）配色不一致。
 */
export function dirTone(direction: string | null | undefined): DirTone {
  const d = direction ?? "";
  if (/涨|偏多|强|看多/.test(d)) return { text: UP_TEXT[400], bg: "bg-red-500/10" };
  if (/跌|偏空|弱|看空/.test(d)) return { text: DOWN_TEXT[400], bg: "bg-green-500/10" };
  return { text: "text-amber-300", bg: "bg-amber-500/10" };
}

/** 买卖动作配色。加仓 / 买入 = 红，减仓 / 卖出 = 绿，其余中性。兼容 buy / sell 英文标记。 */
export function actionTone(action: string | null | undefined, level: ToneLevel = 400): string {
  const a = action ?? "";
  if (/加仓|买入|建仓|buy/i.test(a)) return UP_TEXT[level];
  if (/减仓|卖出|清仓|sell/i.test(a)) return DOWN_TEXT[level];
  return NEUTRAL_TEXT[level];
}

export interface ActionBadge extends DirTone {
  /** 展示文案 */
  label: string;
}

/** 买卖动作徽章（文案 + 文字色 + 底色）。 */
export function actionBadge(action: string | null | undefined): ActionBadge {
  const a = action ?? "";
  if (/减仓|卖出|清仓|sell/i.test(a)) return { label: "减仓", text: DOWN_TEXT[300], bg: "bg-green-500/10" };
  if (/加仓|买入|建仓|buy/i.test(a)) return { label: "可加仓", text: UP_TEXT[300], bg: "bg-red-500/10" };
  return { label: "持有", text: NEUTRAL_TEXT[300], bg: "bg-slate-500/10" };
}
