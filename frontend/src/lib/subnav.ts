// ⚠️ 本文件**只允许 import type**。
// 它被 node 环境下的守卫测试直接 import（`featureMap.test.ts`），
// 任何运行期导入都会把 React / lucide 拉进测试进程，让守卫变慢且不稳。
// 图标不放在这里 —— 由各个 Panel 自己映射（见各 Panel 里的 SUB_ICON）。
import type { Tab } from "./nav";

/**
 * 二级导航（子页）· 单一来源
 *
 * ## 为什么集中到一处
 * 重构前子页的 key 分散在每个 Panel 文件里各写一遍，和 `featureMap.ts` 的登记
 * 靠**字符串搜索**对账（守卫去 Panel 源码里找 `"monitor"` 这个字面量）。
 * 那能兜住"拼错了"，但兜不住"改了名字忘了改登记"—— 两者只是碰巧同源。
 *
 * 现在改成：子页在这里声明一次，Panel 消费它渲染导航，`FeatureEntry.sub` 用它
 * 的联合类型。于是"登记了一个不存在的子页"**在编译期就不成立**，
 * 守卫也从"对账"升级成"检查每个子页是否真的有功能登记"（见 featureMap.test.ts）。
 *
 * ## 层级上限
 * 全站**最多两级**：一级导航（nav.ts）+ 二级子页（本文件）。
 * 子页内部只允许用「区块」，不允许再出现第三级切换 —— 「找不到」的机械原因
 * 就是点进来之后还要再点一次，而且点完没有回头路。
 *
 * ## desc 怎么写
 * 写「这个子页装了什么」，不写「有什么功能」；不写「值得买」这类话术。
 * 这份 desc 会同时出现在二级导航条上，是用户判断"要不要点进去"的唯一依据。
 */
export interface SubNavDef {
  key: string;
  label: string;
  desc: string;
}

export const SUB_NAV = {
  today: [
    { key: "monitor", label: "盯盘", desc: "实时买卖点 · 挂单价 · 提醒" },
    { key: "market", label: "市场温度", desc: "封板雷达 · 涨跌停梯队 · 风险温度" },
    { key: "briefing", label: "简报", desc: "早盘方向 · 尾盘动作 · 复盘" },
  ],
  opportunity: [
    { key: "decision", label: "精选决策", desc: "每日推荐 · 三维确认 · 结构位 · 板块环境" },
    { key: "scan", label: "扫描中心", desc: "策略筛选 · 时段异动 · K线/筹码/三度结构" },
  ],
  holdings: [
    { key: "position", label: "持仓", desc: "成本 · 浮盈亏 · 预警规则" },
    { key: "sim", label: "模拟盘", desc: "虚拟资金记账 · 一字板会标买不进" },
    { key: "watch", label: "自选", desc: "关注列表 · 可整批加入盯盘" },
    { key: "history", label: "历史", desc: "历次分析批次留档" },
  ],
  research: [
    { key: "verify", label: "验证中心", desc: "证据等级 · 实际胜率 · 组合/形态回测" },
  ],
} as const satisfies Record<Tab, readonly SubNavDef[]>;

/**
 * 全部子页 key 的联合类型。
 *
 * 用映射类型对 Tab 做分发，得到的是**所有子页的并集**（不是交叉）——
 * 这样一个 `FeatureEntry` 可以声明任意一级页下的子页，同时拼错就编译不过。
 */
export type SubKey = { [K in Tab]: (typeof SUB_NAV)[K][number]["key"] }[Tab];

/** 取某一级页的子页列表。Panel 用它渲染二级导航。 */
export function subNavFor(tab: Tab): readonly SubNavDef[] {
  return SUB_NAV[tab];
}

/** 某个 key 是否属于该一级页 —— 用于处理外部跳转传入的 sub。 */
export function isSubOf(tab: Tab, key: string | undefined | null): key is string {
  if (!key) return false;
  return SUB_NAV[tab].some((s) => s.key === key);
}
