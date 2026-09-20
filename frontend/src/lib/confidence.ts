/**
 * confidence 的显示口径（唯一来源）。
 *
 * 背景：推荐 payload 里的 `confidence` 是同一个 0-10 尺度，但承载两种语义 ——
 * LLM 自评把握（`source='llm'`）与规则加权策略分（`source='rule'` / `'watch'`）。
 * 历史上前端一律显示「置信」，等于把「模型主观有多笃定」和「规则算了多少分」
 * 混成同一件事，用户没法知道这个数代表什么、能不能当依据。
 *
 * 后端由 `confidence_source` 显式给出语义；老快照没有该字段时如实说「来源未知」，
 * 不要猜成某一支 —— 猜错等于伪造口径。
 */

export type ConfidenceSource = "llm_self_report" | "rule_score";

/** 数字该叫什么。未知来源不猜，直接说「置信」并靠 hint 说明来源缺失。 */
export function confidenceLabel(source?: string | null): string {
  if (source === "llm_self_report") return "AI 自评";
  if (source === "rule_score") return "策略分";
  return "置信";
}

/** 这个数意味着什么。用于 title / 辅助说明。 */
export function confidenceHint(source?: string | null): string {
  if (source === "llm_self_report") {
    return "LLM 对自己推荐理由的把握（0-10），是主观自评，不是胜率预估";
  }
  if (source === "rule_score") {
    return "规则加权分（0-10，动量 0.7 + 趋势 0.3，封顶 10），确定性计算，不是胜率预估";
  }
  return "来源未知（该条为历史数据，生成时未记录口径）";
}

/** 是否需要提示口径缺失（老数据）—— UI 可据此弱化显示。 */
export function confidenceUnknownSource(source?: string | null): boolean {
  return source !== "llm_self_report" && source !== "rule_score";
}
