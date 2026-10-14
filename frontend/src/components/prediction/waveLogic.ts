/**
 * 波浪定位的展示逻辑（纯函数，便于单测）。
 *
 * 与后端 `wave_service` 的分工：
 *   后端只负责「算出浪位」，不给展示口径；
 *   本文件负责「这堆数字该怎么读」—— 哪些要弱化、哪些要报警、哪些整块不显示。
 *
 * ⚠️ 一条必须守住的口径：波浪划分**分级且主观**，界面上永远要带级别
 * （「日线 · C 浪第 3 子浪」），不能只写「第 3 浪」—— 否则用户会把它
 * 和别的周期、别的分析师画出来的浪数混在一起读。
 */
import type { WaveAnalysis, WaveLevel, WaveRule } from "../../types";

/**
 * 置信度低于此值时弱化展示。
 *
 * 为什么需要这条线：铁律通过率不足时后端会把置信度压到 0.30 以下，
 * 那种划分仍然是「最接近的一版」，但**不该被读成结论**。
 * 0.45 落在「全过但结构不完整」(约 0.55~0.7) 与「有铁律没过」(≤0.30) 之间。
 */
export const LOW_CONFIDENCE = 0.45;

/** 整块是否该渲染：两个级别都没定位出浪位时整块隐藏，不留空壳。 */
export function hasWave(analysis: WaveAnalysis | null | undefined): boolean {
  if (!analysis) return false;
  return Boolean(analysis.daily?.position || analysis.weekly?.position);
}

/** 置信度百分数（0~100 整数）。字段缺失或非法一律回 0，不抛异常。 */
export function confidencePct(level: WaveLevel | null | undefined): number {
  const c = level?.confidence;
  return typeof c === "number" && Number.isFinite(c) ? Math.round(c * 100) : 0;
}

/** 当前这一浪是否还没走完（以最后一个摆动点为界）。 */
export function isInProgress(level: WaveLevel | null | undefined): boolean {
  const waves = level?.waves ?? [];
  return Boolean(waves[waves.length - 1]?.provisional);
}

/**
 * 未通过的铁律（含软性规则）。
 *
 * 软性规则也一并回传：界面上要能看出「哪条没通过」，
 * 否则用户无法复核这个划分凭什么成立 —— 那它就变成了黑箱结论。
 * `applicable === false` 的条目（例如第 3 浪还没走完）不算未通过。
 *
 * ⚠️ 展示时必须和 `failedRequiredRules` 分开：软性规则（形态交替、比例贴合）
 * 不过**不影响划分成立**，和「铁律没过」放在一起报会把正常读数渲染成告警。
 */
export function failedRules(level: WaveLevel | null | undefined): WaveRule[] {
  return (level?.rules ?? []).filter((r) => r.applicable !== false && !r.ok);
}

/** 未通过的**必过**铁律 —— 只有这一档才该降置信度、才该告警。 */
export function failedRequiredRules(level: WaveLevel | null | undefined): WaveRule[] {
  return failedRules(level).filter((r) => r?.required);
}

/** 未通过的软性规则（比例偏离、形态未交替）—— 信息性，不告警。 */
export function failedSoftRules(level: WaveLevel | null | undefined): WaveRule[] {
  return failedRules(level).filter((r) => r?.required === false);
}

/** 必过铁律是否全部通过。 */
export function rulesPassed(level: WaveLevel | null | undefined): boolean {
  return failedRequiredRules(level).length === 0;
}

/** 目标位一行文案：`3707.07（5 = 第1浪 × 1）`。 */
export function targetTexts(level: WaveLevel | null | undefined): string[] {
  return (level?.targets ?? []).map((t) => `${t.price}（${t.basis}）`);
}

/** 内层"未走完"标记：只给最后一段打，前面的段都是已确认的摆动点。 */
export function waveChips(level: WaveLevel | null | undefined): { label: string; text: string; hint: string; current: boolean }[] {
  return (level?.waves ?? []).map((w) => ({
    label: w.label,
    text: `${w.label} ${w.pct > 0 ? "+" : ""}${w.pct}%`,
    hint: `${w.from_date} → ${w.to_date}　${w.from_price} → ${w.to_price}　${w.bars} 根`,
    current: w.current,
  }));
}

/**
 * 图上标注点：把每一浪的**终点**作为标注坐标（波浪派的标准画法 ——
 * 标签落在这一浪走完的位置，而不是起点）。
 *
 * 日期与价格都直接用后端回传的值，不做任何换算：图上用的是日线收盘价，
 * 与后端 ZigZag 的输入同源，能直接对齐到 K 线。
 */
export function waveMarks(level: WaveLevel | null | undefined): { date: string; price: number; label: string }[] {
  return (level?.waves ?? [])
    .filter((w) => w?.to_date && Number.isFinite(w?.to_price))
    .map((w) => ({ date: w.to_date, price: w.to_price, label: w.label }));
}

/**
 * 图上标注点必须落在图上 —— 过滤掉不在当前 K 线窗口里的坐标。
 *
 * 波浪定位用的是 180 根 K 线，图上只画 120 根（`fetchIndexHistory(120)`），
 * 周线级别的摆动点更是远在窗口之外。不过滤的话 ECharts 会把它们画到
 * 坐标轴边缘或直接报错。
 */
export function clampMarksToDates(
  marks: { date: string; price: number; label: string }[],
  dates: string[],
): { date: string; price: number; label: string }[] {
  const allowed = new Set(dates);
  return marks.filter((m) => allowed.has(m.date));
}

/**
 * 图上标注点的悬浮说明。
 *
 * 为什么不直接显示标签本身：`c3` 这种简写在图上太短，而悬浮时可以展开成
 * 「C 浪第 3 子浪」—— 这正是用户看波浪标注时最需要的那句话。
 */
export function waveMarkTooltip(label: string): string {
  if (!label) return "";
  if (/^c[1-5]$/.test(label)) return `C 浪第 ${label.slice(1)} 子浪`;
  if (/^[ABC]$/.test(label)) return `${label} 浪`;
  return `第 ${label} 浪`;
}
