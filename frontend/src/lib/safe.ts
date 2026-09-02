/** 兜底工具：避免后端字段缺失/类型异常导致组件崩溃。 */

export function safeArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

export function safeArrayOr<T>(value: unknown, fallback: T[]): T[] {
  return Array.isArray(value) ? (value as T[]) : fallback;
}

export function safeNumber(value: unknown, fallback = 0): number {
  const n = typeof value === "string" ? parseFloat(value) : value;
  return typeof n === "number" && Number.isFinite(n) ? n : fallback;
}

export function safeStr(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

export function safeObj<T extends object>(value: unknown, fallback: T): T {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as T)
    : fallback;
}

/** 安全 toFixed（处理 undefined/非数字） */
export function fmtNum(value: unknown, digits = 2, fallback = "-"): string {
  const n = safeNumber(value, NaN);
  return Number.isFinite(n) ? n.toFixed(digits) : fallback;
}

/** 安全百分比字符串 */
export function fmtPct(value: unknown, fallback = "-"): string {
  const n = safeNumber(value, NaN);
  if (!Number.isFinite(n)) return fallback;
  const sign = n >= 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}%`;
}