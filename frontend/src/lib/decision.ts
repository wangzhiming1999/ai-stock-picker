/**
 * 统一决策契约（前端侧）—— 与后端 `app/services/decision.py` 一一对应。
 *
 * 背景：页面上的动作文案此前由各模块自己拼（「持有观察」「建议减仓」「可关注」
 * 「继续跟踪」…），`lib/tone.ts::actionBadge` 只能靠正则去猜中文串的含义。
 * 结果是同一件事有 9 种说法，用户读到的每个词都像「系统也没主意」。
 *
 * 本模块是前端动作词的**唯一来源**：
 * - 组件不得再手写「买入 / 减仓 / 观察」这类中文，一律走 `DECISION_LABEL`；
 * - `skip`（不参与）与买 / 卖并列，是一等公民 —— 它表达的是明确的「现在不做」，
 *   而不是「观察」「留意」这种没有结论的措辞。
 *
 * 色权：动作色只表达「我打算做什么」，不表达价格方向。
 * 买入 / 加仓 = 红，卖出 / 减仓 = 绿（沿用 `CHIP`），持有 / 不参与 = 中性 ——
 * 中性档**不得**用绿：绿在行情语义里是「跌」，会给「建议别动」镀上一层看空的错觉。
 */

import type { Decision } from "../types";

export type { Decision };

/** 全部合法动作 */
export const DECISIONS: readonly Decision[] = ["buy", "add", "hold", "reduce", "sell", "skip"];

/** 用户可见短标签（角标内） */
export const DECISION_LABEL: Record<Decision, string> = {
  buy: "买入",
  add: "加仓",
  hold: "持有不动",
  reduce: "减仓",
  sell: "卖出",
  skip: "不参与",
};

/** 长标签：有空间时用。「不参与」带上原因才叫决策，否则又变成一个模糊词。 */
export const DECISION_LONG_LABEL: Record<Decision, string> = {
  ...DECISION_LABEL,
  skip: "不参与（空仓等待）",
};

/** 处置优先级：风险处置先于开仓。数值小 = 更该立刻看。 */
export const DECISION_ORDER: Record<Decision, number> = {
  sell: 0,
  reduce: 1,
  buy: 2,
  add: 3,
  hold: 4,
  skip: 5,
};

/** 开仓类动作：说不出「什么价才动手」就不算一条决策 */
export const ENTRY_DECISIONS: readonly Decision[] = ["buy", "add"];

/**
 * 动作角标配色（底色 + 文字色）。
 *
 * 色值与 `lib/tone.ts::CHIP` 对齐（买/加 = 红、卖/减 = 绿、持有/不参与 = 中性），
 * 但这里**不 import 它** —— 本模块保持零运行时依赖，才能被 `node --test` 直接加载。
 * 两边一致性由 `decision.test.ts` 断言，改任一边另一边就会失败。
 *
 * 中性档（hold / skip）不得用绿：绿在行情语义里是「跌」，
 * 会给「建议别动」镀上一层看空的错觉（同 `playAdviceTone` 的口径）。
 */
export const DECISION_CHIP: Record<Decision, { bg: string; text: string }> = {
  buy: { bg: "bg-red-500/10", text: "text-red-300" },
  add: { bg: "bg-red-500/10", text: "text-red-300" },
  hold: { bg: "bg-surface-inset/40", text: "text-ink" },
  reduce: { bg: "bg-green-500/10", text: "text-green-300" },
  sell: { bg: "bg-green-500/10", text: "text-green-300" },
  skip: { bg: "bg-surface-inset/40", text: "text-ink" },
};

export function isDecision(value: unknown): value is Decision {
  return typeof value === "string" && (DECISIONS as readonly string[]).includes(value);
}

/** 动作的展示文案。未知动作按「不参与」渲染，不抛异常（宁可不动作）。 */
export function decisionLabel(action: string | null | undefined, opts?: { long?: boolean }): string {
  const d = isDecision(action) ? action : "skip";
  return (opts?.long ? DECISION_LONG_LABEL : DECISION_LABEL)[d];
}

/** 动作是否属于开仓类 */
export function isEntryDecision(action: string | null | undefined): boolean {
  return isDecision(action) && (ENTRY_DECISIONS as readonly string[]).includes(action);
}
