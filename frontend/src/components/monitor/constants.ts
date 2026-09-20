import type { MonitorAdvice, MonitorInterval } from "../../types";

export const LS_KEY = "ai:monitorCodes";
export const LS_NOTIFY = "ai:monitorNotify";
export const LS_INTERVAL = "ai:monitorInterval";
export const DEFAULT_POLL_MS = 5 * 60 * 1000;
export const MAX_CODES = 20;

/**
 * 提醒 toast 的停留时长。sonner 默认只有 4 秒 —— 盯盘提醒是「现在该买/该卖/该止损」，
 * 属于全站最不能错过的信息，4 秒根本读不完就没了，所以显式延长。
 */
export const ALERT_TOAST_MS = 30_000;
/** 同票同指令的去重窗口：窗口内重复触发只响一次 */
export const ALERT_DEDUPE_MS = 3 * 60 * 1000;
/** 页内提醒记录上限：超出丢弃最旧的，避免长时间盯盘时无限累积 */
export const MAX_ALERTS = 30;

/** 一条盯盘提醒记录（页内留痕，toast 消失后仍可回看） */
export interface MonitorAlertItem {
  id: string;
  code: string;
  name: string;
  label: string;
  body: string;
  tone: MonitorAdvice["tone"];
  at: string;
}

/** 周期档位：日线定方向，分钟线定这一笔 */
export const INTERVALS: { value: MonitorInterval; label: string; hint: string }[] = [
  { value: "1d", label: "日线", hint: "波段：日 K 支撑压力，止损较宽（3% 左右），持仓数天到数周" },
  { value: "15m", label: "15 分", hint: "日内：VWAP + 15 分钟均线，止损 0.5%~1.1%，当日了结" },
  { value: "5m", label: "5 分", hint: "日内：最灵敏，止损 0.3%~0.8%，噪音也最多，适合盯盘时做 T" },
];

function loadInterval(): MonitorInterval {
  try {
    const v = localStorage.getItem(LS_INTERVAL);
    if (v === "1d" || v === "5m" || v === "15m" || v === "30m" || v === "60m") return v;
  } catch {
    /* ignore */
  }
  return "1d";
}

/** 触发类指令：动作从其他状态切换进来时提醒 */
const TRIGGER_ACTIONS = new Set(["buy", "sell", "stop"]);

function loadSaved(): string[] {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    return Array.isArray(arr)
      ? arr.filter((x) => typeof x === "string" && /^\d{6}$/.test(x)).slice(0, MAX_CODES)
      : [];
  } catch {
    return [];
  }
}

function loadNotify(): boolean {
  try {
    const v = localStorage.getItem(LS_NOTIFY);
    if (v === "0") return false;
    if (v === "1") return true;
  } catch {
    /* ignore */
  }
  // 没设置过：浏览器已授权桌面通知就默认开启。
  // 默认关闭会让「切到别的窗口盯盘」这件事完全收不到提醒，而提醒开关正是为它存在的。
  try {
    return "Notification" in window && window.Notification.permission === "granted";
  } catch {
    return false;
  }
}

/** 指令色调 */
const toneClass: Record<string, string> = {
  danger: "border-red-800/70 bg-red-950/50 text-red-300",
  warn: "border-amber-800/60 bg-amber-950/40 text-amber-300",
  good: "border-green-800/60 bg-green-950/40 text-green-300",
  neutral: "border-slate-700 bg-slate-800/70 text-ink-soft",
  info: "border-sky-800/60 bg-sky-950/40 text-sky-300",
};

const toneDot: Record<string, string> = {
  danger: "bg-red-400",
  warn: "bg-amber-400",
  good: "bg-green-400",
  neutral: "bg-slate-500",
  info: "bg-sky-400",
};

function fmtTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "-";
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;
}

function num(v: number | undefined | null, digits = 2): string {
  return v == null || Number.isNaN(v) ? "-" : v.toFixed(digits);
}

export { loadInterval, loadSaved, loadNotify, TRIGGER_ACTIONS, toneClass, toneDot, fmtTime, num };
