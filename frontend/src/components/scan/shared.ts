import type { StrategyDef } from "../../types";

/** 一键找候选的四种目标。原在 ScanPanel 内联，提取为共享常量。 */
export const STRATEGIES: StrategyDef[] = [
  { name: "trend", label: "稳健趋势", desc: "找走势稳定、均线向上的候选" },
  { name: "volume", label: "放量启动", desc: "找成交活跃、刚开始走强的候选" },
  { name: "momentum", label: "强势延续", desc: "找近期较强但不过热的候选" },
  { name: "value", label: "估值观察", desc: "找估值克制、交投正常的候选" },
];

/** 按条件筛选面板的五个筛选项。集中定义，避免散在调用点里各写一遍。 */
export interface ScanFilters {
  minChange: string;
  minAmount: string;
  minPrice: string;
  maxPrice: string;
  limit: string;
}

export type ScanFilterKey = keyof ScanFilters;
