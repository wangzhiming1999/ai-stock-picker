import type { ComponentType, SVGProps } from "react";
import { Lightbulb, Wallet, Zap } from "lucide-react";

/**
 * 一级导航 · 按「我今天要做什么」切分，而不是按「功能类型」切分。
 *
 * 历史包袱：曾经是 发现好股 / 选股扫描 / 深度分析 / 我的 四个平级 tab，
 * 内部再各塞 5~6 个平级卡片，导致最重要的盘中监控台埋在最深处、
 * 「深度分析」作为流程终点却占着一级入口。
 *
 * 现在：
 *   today       — 一天三个决策点（早盘方向 / 盘中盯盘 / 尾盘动作）
 *   opportunity — 票从哪来（推荐 / 扫描 / 验证）
 *   holdings    — 我手里有什么（持仓 / 模拟盘 / 自选 / 预警 / 历史）
 *
 * 「深度分析」不再占一级入口，改为全局抽屉（AnalysisDrawer）。
 */
export type Tab = "today" | "opportunity" | "holdings";

type IconComp = ComponentType<SVGProps<SVGSVGElement>>;

export interface NavItem {
  key: Tab;
  label: string;
  icon: IconComp;
  desc: string;
}

export const NAV: NavItem[] = [
  { key: "today", label: "今日作战", icon: Zap, desc: "早盘方向 · 盘中盯盘 · 尾盘动作" },
  { key: "opportunity", label: "选机会", icon: Lightbulb, desc: "AI 推荐 · 策略扫描 · 回测验证" },
  { key: "holdings", label: "持仓", icon: Wallet, desc: "持仓 · 模拟盘 · 自选 · 预警" },
];

export const DEFAULT_TAB: Tab = "today";

export function isTab(v: string | null): v is Tab {
  return v === "today" || v === "opportunity" || v === "holdings";
}
