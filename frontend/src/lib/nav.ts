import type { ComponentType, SVGProps } from "react";
import { Lightbulb, Microscope, Wallet, Zap } from "lucide-react";

/**
 * 一级导航 · 按「我今天要做什么」切分，而不是按「功能类型」切分。
 *
 * ## 四个入口对应一天里的四类动作
 *   today       今天该干什么   —— 盯盘 / 简报
 *   opportunity 今天买什么     —— 推荐 / 决策 / 扫描 / 形态
 *   holdings    我手里有什么   —— 持仓 / 模拟盘 / 自选 / 历史
 *   research    这些方法靠不靠谱 —— 证据台账 / 胜率 / 回测
 *
 * ## 为什么把「研究」独立出来（2026-09-20 重构）
 * 此前「验证」是「选机会」下的第三个子页，和「推荐」「扫描」并列。语义上不对：
 * 推荐和扫描回答「今天买什么」，验证回答「这套方法本身行不行」——后者是**回头看**，
 * 不属于"选机会"这个动作。混在一起的结果是：用户找「回测」「胜率」时会先去翻选股页，
 * 翻不到就以为没有。独立成一级后，「方法可信度」这件事有了自己的入口。
 *
 * ## 历史包袱（别再走回去）
 * 曾经是 发现好股 / 选股扫描 / 深度分析 / 我的 四个平级 tab，内部再各塞 5~6 个
 * 平级卡片，导致最重要的盘中监控台埋在最深处、「深度分析」作为流程终点却占着一级入口。
 * 后来收敛成 3 项；现在 4 项，但**每个都需要**——不是又回到了"按功能类型切"。
 *
 * 「深度分析」不占一级入口，是全局抽屉（AnalysisDrawer）。
 * 涨跌停两条温度带也不进 NAV —— 它们是"读市场"而非"做一件事"。
 */
export type Tab = "today" | "opportunity" | "holdings" | "research";

type IconComp = ComponentType<SVGProps<SVGSVGElement>>;

export interface NavItem {
  key: Tab;
  label: string;
  icon: IconComp;
  desc: string;
}

export const NAV: NavItem[] = [
  { key: "today", label: "今日作战", icon: Zap, desc: "盯盘 · 简报" },
  { key: "opportunity", label: "选机会", icon: Lightbulb, desc: "推荐 · 决策 · 扫描 · 形态 · 涨跌停" },
  { key: "holdings", label: "持仓", icon: Wallet, desc: "持仓 · 模拟盘 · 自选 · 历史" },
  { key: "research", label: "研究", icon: Microscope, desc: "证据台账 · 胜率 · 回测" },
];

export const DEFAULT_TAB: Tab = "today";

export function isTab(v: string | null): v is Tab {
  return v === "today" || v === "opportunity" || v === "holdings" || v === "research";
}
