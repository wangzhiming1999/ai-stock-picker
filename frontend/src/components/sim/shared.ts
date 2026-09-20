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
