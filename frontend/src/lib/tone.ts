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

/**
 * 文本色强度档位（暗色主题）。
 *
 *   300 = 用在「带色底的芯片」内（底色已经抬亮了背景，文字要更亮才压得住）
 *   400 = 默认（页面底色 / 主卡 / 子块上都达标）
 *
 * ⚠️ 曾经有第三档 500（更暗），本意是「密集小字用更弱的色」。这在暗色主题下是**反向的**：
 * 更弱的色 = 更暗 = 对比度更低，而小字恰恰需要更高对比度。实测 red-500 在 slate-900 上
 * 只有 3.89:1，低于 AA 的 4.5:1。该档已删除 —— 需要「更弱」时请用 300，或改用中性色。
 */
export type ToneLevel = 300 | 400;

const UP_TEXT: Record<ToneLevel, string> = {
  300: "text-red-300",
  400: "text-red-400",
};

const DOWN_TEXT: Record<ToneLevel, string> = {
  300: "text-green-300",
  400: "text-green-400",
};

const NEUTRAL_TEXT: Record<ToneLevel, string> = {
  300: "text-ink-soft",
  400: "text-ink-muted",
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
 *
 * 判定顺序也必须和后端一致：**先判「震荡」**。像「震荡偏强」带倾向词「强」，
 * 若先匹配方向词会被染成上涨红，而后端归一化结果是「震荡」—— 同一份数据
 * 在不同位置呈现相反语义，正是这条规则要拦住的。
 */
export function dirTone(direction: string | null | undefined): DirTone {
  const d = direction ?? "";
  if (/震荡|横盘|盘整|整理|中性|胶着|反复/.test(d)) return { text: "text-amber-300", bg: "bg-amber-500/10" };
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
  return { label: "持有", text: NEUTRAL_TEXT[300], bg: "bg-surface-line-strong/10" };
}

/**
 * 炸板率配色（**风险阈值**类，不是方向类）。
 *
 * 炸板率衡量的是「封板有多不结实」，属于情绪质量 / 风险阈值，所以不占红绿 ——
 * 与「止损=琥珀」同理：它是警戒线，既不预判上涨也不预判下跌。
 * 低炸板率也不上红色：那不是「上涨方向」，只是达标。
 */
export function breakRateTone(rate: number | null | undefined): string {
  if (rate == null || Number.isNaN(rate)) return "text-ink-muted";
  if (rate >= 40) return "text-amber-300"; // 警戒：接力分歧明显加大
  if (rate >= 20) return "text-amber-400"; // 一般
  return "text-brand-light"; // 达标：封板扎实
}

/**
 * 情绪一句话点评配色（后端给出 good / warn / neutral）。
 * 同样属于质量判断而非价格方向，因此走主色 / 琥珀 / 中性，不用红绿。
 */
export function sentimentTone(tone: string | null | undefined): string {
  if (tone === "good") return "text-brand-light";
  if (tone === "warn") return "text-amber-300";
  return "text-ink-muted";
}

/**
 * 操作建议档位配色（avoid / watch / hunt）。
 *
 * ⚠️ 这三档是「环境质量判断」，不是涨跌方向：
 * - avoid（空仓等待）用琥珀警示，不用绿 —— 绿在行情语义里是「跌/看空」，
 *   用绿渲染「建议别动」会让同一屏的下跌数字与建议互相打架；
 * - hunt（可打板）用主色蓝 —— 它是「环境达标」的质量判断，红绿都不能用。
 */
export function playAdviceTone(level: string | null | undefined): string {
  if (level === "hunt") return "text-brand-light";
  if (level === "avoid") return "text-amber-300";
  return "text-ink-muted";
}

/**
 * 质量评分色（0–10 分制）。
 *
 * 质量（信号强度 / 胜率 / 条件通过项）表达的是「好不好」，与「价格往哪走」无关，
 * 所以不占红绿 —— 否则同一张卡里「强度 8」是绿、「今日涨 2%」是红，
 * 读者得为每个数字重新建立一次颜色映射。
 *
 * 高 = 主色浅档（达标）／ 中 = 琥珀（一般）／ 低 = 中性正文色（不达标）
 *
 * ⚠️ 低档用 `ink-soft` 而不是 `ink-faint`：这两处返回的是**读数**（分数、倍率），
 *    压到最弱档就等于把「3.2 分」和「没有数据」画成同一种灰。缺失值走的是
 *    `ink-muted`（见上方各函数的第一行），两者必须能分辨。
 */
export function scoreTone(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "text-ink-muted";
  if (v >= 6) return "text-brand-light";
  if (v >= 4) return "text-amber-400";
  return "text-ink-soft";
}

/** 质量评分底色芯片（0–10 分制）。 */
export function scoreChip(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "bg-surface-inset/40 text-ink-muted";
  if (v >= 6) return "bg-brand/15 text-brand-light";
  if (v >= 4) return "bg-amber-500/15 text-amber-300";
  return "bg-surface-inset/40 text-ink-muted";
}

/**
 * 百分制质量评分色（0–100）。命中率 / 胜率这类以 % 展示的指标走这里，
 * 内部折算到十分制复用 scoreTone，保证 60% 与 6 分同色。
 */
export function pctTone(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "text-ink-muted";
  return scoreTone(v / 10);
}

/** 质量评分的纯底色（用于进度条填充等只需背景色的场景，0–10 分制）。 */
export function scoreBg(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "bg-surface-line-strong";
  if (v >= 6) return "bg-brand";
  if (v >= 4) return "bg-amber-400";
  return "bg-surface-line-strong";
}

/**
 * 风报比配色（不是 0–10 分制，是倍率）。>=2 达标，>=1 一般，其余偏低。
 * 同样属于质量而非方向，所以不用红绿。低档同 scoreTone 用 `ink-soft`（是读数）。
 */
export function rrTone(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "text-ink-muted";
  if (v >= 2) return "text-brand-light";
  if (v >= 1) return "text-amber-400";
  return "text-ink-soft";
}

/**
 * 固定语义芯片色（底色 + 文字），用于买点 / 卖出区 / 止损这类标签块。
 *
 * 这里需要区分两种"颜色语义"，不要混用：
 *   方向色（pnlTone / dirTone）：价格会往哪走
 *   动作色（actionTone / CHIP）：我打算做什么
 *
 * 止损之所以是琥珀而不是红或绿 —— 它是风控阈值，既不预判上涨也不预判下跌，
 * 用红会被读成"又要跌了"，用绿会被读成"好事"，只有琥珀能表达"警戒线"。
 */
export const CHIP = {
  /** 买点 / 买入区：做多的价位锚点 */
  buy: { bg: "bg-red-500/10", text: "text-red-300" },
  /** 卖出区：离场的价位 */
  sell: { bg: "bg-green-500/10", text: "text-green-300" },
  /** 止损等风控阈值 */
  risk: { bg: "bg-amber-500/10", text: "text-amber-300" },
  /** 中性价位：支撑 / 压力 / 现价 */
  neutral: { bg: "bg-surface-inset/40", text: "text-ink" },
} as const;

/**
 * 多空分歧度配色（0-100，口径 = min(多头信心, 空头信心)）。
 *
 * 分歧是「争议大小」的质量信息，不是价格方向，所以不占红绿；
 * 高分歧（两边都笃定）才是警戒，给琥珀；低分歧只是「共识明确」的中性信息，
 * 不给达标色（蓝 = 达标语义，低分歧并不比高分歧"更好"，它俩只是含义不同）。
 */
export function divergenceTone(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "text-ink-muted";
  if (v >= 60) return "text-amber-300";
  if (v >= 30) return "text-amber-400";
  return "text-ink-muted";
}
