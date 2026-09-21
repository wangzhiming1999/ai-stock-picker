/** 交易弹窗状态：由宿主持有并下传，控制买/卖弹窗的开合 */
export interface ModalState {
  side: "buy" | "sell";
  code: string;
  price?: number;
}

/** 成交时间格式化：ISO 字符串 -> "YYYY-MM-DD HH:mm"（去 T、截断到分钟） */
export function fmtTradeTime(iso: string | null | undefined): string {
  return (iso || "").slice(0, 16).replace("T", " ");
}

/**
 * 成交价相对**预期价格**的偏离（%）。
 *
 * 预期价格＝建仓时填的计划成交价（打板价 / 回踩位）。正数表示成交比计划**贵**，
 * 负数表示比计划便宜 —— 这是执行偏差的读数，**不参与任何盈亏 / 胜率计算**。
 *
 * 返回 null 的三种情况，调用方一律不渲染：
 *   - `expected_price` 缺失（v13 迁移未执行，或这一笔是卖出）；
 *   - 预期价格为 0 / 非有限值（不能除以它）；
 *   - 成交价本身无效。
 */
export function slippagePct(t: { price: number; expected_price?: number | null }): number | null {
  const exp = t.expected_price;
  if (exp == null || !Number.isFinite(exp) || exp <= 0) return null;
  if (!Number.isFinite(t.price)) return null;
  return ((t.price - exp) / exp) * 100;
}

/** 执行偏差的白话（贵/便宜），与 slippagePct 配对使用。红绿在这里不适用：滑点是成本不是方向。 */
export function slippageLabel(pct: number): string {
  return `成交比预期${pct >= 0 ? "贵" : "便宜"} ${Math.abs(pct).toFixed(2)}%`;
}
