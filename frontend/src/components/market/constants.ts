/**
 * 两根温度带（涨停 / 跌停）共用的常量与颜色映射。
 *
 * 抽出来的原因：涨停侧与跌停侧的宿主组件各自都写了一遍 `POLL_INTERVAL`、
 * 位置标签配色、`tierChip` 分层配色 —— 内容相同、名字也相同，只是各在自己的文件里。
 * 收编到这一处后，两条带子共用一套定义，改一处即全站生效。
 *
 * ⚠️ 颜色纪律（本项目不可动的红线）：
 *   - 位置标签（启动/加速/高位、首跌/封死/连跌…）一律走**中性 / 琥珀**，
 *     不占红绿 —— 红绿是方向语义，用在这里会被读成「该动手了」；
 *   - `tierChip` 是**强弱质量判断**（1=达标 / 2=一般 / 3=弱），同样不占红绿；
 *   - 文字色一律走 `ink-*`，不要在这里手写 `text-slate-*`。
 */

/** 与后端 60s 内存缓存同拍，不必更密。 */
export const POLL_INTERVAL = 60_000;

/**
 * 涨停侧位置标签配色。
 *
 * 全部走中性 / 琥珀：位置越靠后风险越高，但它既不预示上涨（不用红）
 * 也不预示下跌（不用绿）—— 高位之后可能继续加速，也可能直接退潮。
 */
const UP_POSITION_CHIP: Record<string, string> = {
  启动: "bg-surface-inset/70 text-ink-soft",
  加速: "bg-surface-line/70 text-ink-soft",
  中继: "bg-surface-line/70 text-ink",
  高位: "bg-amber-500/10 text-amber-300",
  分歧: "bg-amber-500/10 text-amber-300",
};

export function upPositionChip(tag: string): string {
  return UP_POSITION_CHIP[tag] ?? "bg-surface-inset/70 text-ink-muted";
}

/**
 * 跌停侧位置标签配色，全部走中性 / 琥珀。
 *
 * 跌得越深风险越高，但它既不预示继续跌（不用绿）也不预示反弹（不用红）——
 * 「跌很多」之后既可能修复也可能继续崩，这个组件不替用户判断是哪一种。
 */
const DOWN_POSITION_CHIP: Record<string, string> = {
  首跌: "bg-surface-inset/70 text-ink-soft",
  换手: "bg-surface-line/70 text-ink-soft",
  封死: "bg-amber-500/10 text-amber-300",
  连跌: "bg-amber-500/10 text-amber-300",
  深跌: "bg-amber-500/10 text-amber-300",
};

export function downPositionChip(tag: string): string {
  return DOWN_POSITION_CHIP[tag] ?? "bg-surface-inset/70 text-ink-muted";
}

/**
 * 强弱分层芯片配色（tier 1/2/3）：质量判断，不占红绿。
 * 1=主色（达标）/ 2=琥珀（一般）/ 3=中性灰（弱）。
 */
const TIER_CHIP: Record<number, { chip: string; dot: string }> = {
  1: { chip: "bg-brand/15 text-brand-light", dot: "bg-brand" },
  2: { chip: "bg-amber-500/15 text-amber-300", dot: "bg-amber-400" },
  3: { chip: "bg-surface-inset/60 text-ink-muted", dot: "bg-surface-line-strong" },
};

export function tierChip(tier: number | undefined): { chip: string; dot: string } {
  return TIER_CHIP[tier ?? 3] ?? TIER_CHIP[3];
}

/**
 * 可执行性硬筛未通过原因的**短标签**（徽章用）。
 *
 * 后端 `_FOCUS_REJECT_LABELS` 给的是完整口径说明（如「换手 <5%（缩量一字/秒板，挂不上单）」），
 * 塞进一行徽章会挤掉票名。这里只做**截短**，不改写语义 —— 完整文案走 title 悬浮提示。
 *
 * 存在的理由：资金面三因子之一是「换手低」，可成交门槛是「换手 ≥5%」，两者方向相反。
 * 不给这一列，用户会以为「资金面最强」这一档就是可以买的。
 */
const REJECT_CHIP_TEXT: Record<string, string> = {
  untradable: "挂不上单",
  high_break: "炸板多",
  late_seal: "尾盘封板",
};

export function rejectChipText(reason: string | null | undefined): string {
  if (!reason) return "未入选";
  return REJECT_CHIP_TEXT[reason] ?? "未入选";
}

/** 未通过硬筛的徽章配色：与 tier 同纪律，走琥珀，不占红绿（它不是方向判断）。 */
export const REJECT_CHIP = "bg-amber-500/15 text-amber-300";
