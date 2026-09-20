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
  启动: "bg-slate-800/70 text-ink-soft",
  加速: "bg-slate-700/70 text-ink-soft",
  中继: "bg-slate-700/70 text-ink",
  高位: "bg-amber-500/10 text-amber-300",
  分歧: "bg-amber-500/10 text-amber-300",
};

export function upPositionChip(tag: string): string {
  return UP_POSITION_CHIP[tag] ?? "bg-slate-800/70 text-ink-muted";
}

/**
 * 跌停侧位置标签配色，全部走中性 / 琥珀。
 *
 * 跌得越深风险越高，但它既不预示继续跌（不用绿）也不预示反弹（不用红）——
 * 「跌很多」之后既可能修复也可能继续崩，这个组件不替用户判断是哪一种。
 */
const DOWN_POSITION_CHIP: Record<string, string> = {
  首跌: "bg-slate-800/70 text-ink-soft",
  换手: "bg-slate-700/70 text-ink-soft",
  封死: "bg-amber-500/10 text-amber-300",
  连跌: "bg-amber-500/10 text-amber-300",
  深跌: "bg-amber-500/10 text-amber-300",
};

export function downPositionChip(tag: string): string {
  return DOWN_POSITION_CHIP[tag] ?? "bg-slate-800/70 text-ink-muted";
}

/**
 * 强弱分层芯片配色（tier 1/2/3）：质量判断，不占红绿。
 * 1=主色（达标）/ 2=琥珀（一般）/ 3=中性灰（弱）。
 */
const TIER_CHIP: Record<number, { chip: string; dot: string }> = {
  1: { chip: "bg-brand/15 text-brand-light", dot: "bg-brand" },
  2: { chip: "bg-amber-500/15 text-amber-300", dot: "bg-amber-400" },
  3: { chip: "bg-slate-800/60 text-ink-muted", dot: "bg-slate-500" },
};

export function tierChip(tier: number | undefined): { chip: string; dot: string } {
  return TIER_CHIP[tier ?? 3] ?? TIER_CHIP[3];
}
