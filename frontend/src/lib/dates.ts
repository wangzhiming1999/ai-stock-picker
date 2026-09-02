/** 日期展示工具（后端返回 "YYYY-MM-DD" 的 ISO 日期）。 */

const WEEK_CN = ["日", "一", "二", "三", "四", "五", "六"];

/** "2026-09-01" → "9月1日"；空值返回 "" */
export function fmtDate(iso?: string): string {
  if (!iso) return "";
  const [, m, d] = iso.split("-").map(Number);
  return `${m}月${d}日`;
}

/** "2026-09-01" → "周二"；空值返回 "" */
export function fmtWeekday(iso?: string): string {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  return `周${WEEK_CN[new Date(y, m - 1, d).getDay()]}`;
}

/** "2026-09-01" → "9月1日（周二）"；空值返回 "" */
export function fmtDayLabel(iso?: string): string {
  if (!iso) return "";
  return `${fmtDate(iso)}（${fmtWeekday(iso)}）`;
}

/** 北京时间（UTC+8）今天，返回 "YYYY-MM-DD" */
export function cnToday(): string {
  const now = new Date();
  const bj = new Date(now.getTime() + now.getTimezoneOffset() * 60_000 + 8 * 3_600_000);
  const y = bj.getFullYear();
  const m = String(bj.getMonth() + 1).padStart(2, "0");
  const d = String(bj.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

/** iso 是否为北京时间今天的日期 */
export function isTodayCN(iso?: string): boolean {
  return !!iso && iso === cnToday();
}
