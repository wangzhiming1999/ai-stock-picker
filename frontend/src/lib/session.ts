/**
 * A 股交易时段判定 · 单一来源
 *
 * 「今日作战」页靠它决定首屏主视图——用户打开页面时该看到的东西，
 * 应该由「现在几点」决定，而不是让用户自己在一堆卡片里找。
 *
 * 时段边界（A 股）：
 *   09:15 集合竞价开始 / 09:30 连续竞价开始 / 11:30-13:00 午休 / 15:00 收盘
 *   尾盘决策窗口取 14:30-15:00（用户产品定义里「尾盘」= 14:30 后）
 *
 * ⚠️ 只判定「周一~周五」，不接节假日日历。法定假日会被判成交易日，
 * 此时盘中主视图会显示上一交易日数据（监控台自身带 freshness 标记）。
 */

export type SessionKey =
  | "preopen"   // 开盘前（< 09:15）
  | "auction"   // 集合竞价（09:15-09:30）
  | "morning"   // 早盘（09:30-11:30）
  | "lunch"     // 午休（11:30-13:00）
  | "afternoon" // 午后（13:00-14:30）
  | "closing"   // 尾盘决策窗口（14:30-15:00）
  | "closed"    // 收盘后（>= 15:00）
  | "holiday";  // 非交易日（周末）

export interface SessionInfo {
  key: SessionKey;
  /** 展示用中文名 */
  label: string;
  /** 是否处于连续竞价时段（09:30-11:30 / 13:00-15:00） */
  trading: boolean;
  /** 是否处于尾盘决策窗口（14:30-15:00） */
  closingWindow: boolean;
  /** 首屏主视图应该显示什么 */
  mainView: "briefing" | "monitor";
}

const MINUTES = (h: number, m: number) => h * 60 + m;

/** 周一(1) ~ 周五(5) 视为交易日 */
export function isTradingDay(d: Date): boolean {
  const day = d.getDay();
  return day >= 1 && day <= 5;
}

export function sessionOf(d: Date = new Date()): SessionKey {
  if (!isTradingDay(d)) return "holiday";
  const t = MINUTES(d.getHours(), d.getMinutes());
  if (t < MINUTES(9, 15)) return "preopen";
  if (t < MINUTES(9, 30)) return "auction";
  if (t < MINUTES(11, 30)) return "morning";
  if (t < MINUTES(13, 0)) return "lunch";
  if (t < MINUTES(14, 30)) return "afternoon";
  if (t < MINUTES(15, 0)) return "closing";
  return "closed";
}

const LABELS: Record<SessionKey, string> = {
  preopen: "开盘前",
  auction: "集合竞价",
  morning: "早盘",
  lunch: "午间休市",
  afternoon: "午后盘中",
  closing: "尾盘决策",
  closed: "已收盘",
  holiday: "休市",
};

/**
 * 主视图规则：
 *   连续竞价 + 午休 → 盯盘（现在正在发生的事最要紧）
 *   尾盘决策窗口   → 复盘简报（该决定卖还是买了）
 *   开盘前 / 竞价 / 收盘后 → 复盘简报（该决定买什么了）
 */
export function sessionInfo(d: Date = new Date()): SessionInfo {
  const key = sessionOf(d);
  const trading = key === "morning" || key === "afternoon";
  const closingWindow = key === "closing";
  const mainView: SessionInfo["mainView"] =
    key === "morning" || key === "lunch" || key === "afternoon" ? "monitor" : "briefing";
  return { key, label: LABELS[key], trading, closingWindow, mainView };
}
