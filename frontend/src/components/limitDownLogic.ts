import type { LimitDownBucket, LimitDownRepairResult, LimitDownStats } from "../types";

/**
 * 跌停池的纯逻辑（与渲染分离，便于用 node:test 直接跑）。
 *
 * 抽出来的三件事都属于「不抽出来就容易被写错」的类型：
 *
 * 1. `winRateShortfall` —— 打平胜率与实际胜率的差。读者看到「胜率 4.5%」未必能判断
 *    好坏，但「离打平还差 76.1 个百分点」立刻说明这个方向有多远；
 * 2. `fmtDownUpRatio` —— `null` 是「涨停数没取到」，`0` 是「当天没有跌停」，
 *    两者混同会把数据缺失渲染成情绪平稳；
 * 3. `extremeBuckets` —— 从一堆切片里挑出相对最好/最差的一档，并**强制样本量下限**，
 *    否则 n=3 的档会因为偶然值被当成规律（这正是本项目反复出现的可信度陷阱）。
 */

/**
 * 胜率缺口 = 打平所需胜率 − 实际胜率（百分点）。
 *
 * 返回 null 表示数据不足（空切片只返回 `{ n: 0 }`）—— 调用方应隐藏该行，
 * 而**不是**显示 0（0 会被读成「已经打平」）。
 */
export function winRateShortfall(stats: LimitDownStats | undefined): number | null {
  if (!stats) return null;
  const wr = stats.win_rate_open;
  const be = stats.breakeven_win_rate;
  if (typeof wr !== "number" || typeof be !== "number") return null;
  return Math.round((be - wr) * 10) / 10;
}

/**
 * 涨跌停家数比。
 *
 * `null` / `undefined` → "—"：它表示涨停池没取到，与「比值为 0（当天没有跌停）」
 * 是完全不同的两件事，绝不能都渲染成 0.00。
 */
export function fmtDownUpRatio(v: number | null | undefined): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  return v.toFixed(2);
}

/** 从一组切片里挑出的两个极端档。 */
export interface ExtremeBuckets {
  best: LimitDownBucket | null;
  worst: LimitDownBucket | null;
}

/**
 * 从一组切片里挑出期望收益最高与最低的一档。
 *
 * `minN` 是硬门槛：样本太小的档不参与比较。n=3 的档出现 −2.8% 或 +8% 都只是抽样波动，
 * 把它当成「这类更好做」是典型的读错方向 —— 所以要挑极值就必须同时把门槛摆出来。
 */
export function extremeBuckets(buckets: LimitDownBucket[] | undefined, minN = 5): ExtremeBuckets {
  const usable = (buckets ?? []).filter((b) => b.n >= minN && typeof b.expect_open === "number");
  if (usable.length === 0) return { best: null, worst: null };
  const sorted = [...usable].sort((a, b) => (b.expect_open ?? 0) - (a.expect_open ?? 0));
  return { best: sorted[0], worst: sorted[sorted.length - 1] };
}

/**
 * 尾部风险一句话。
 *
 * 为什么它比期望值更该被看见：期望值决定长期，而「卖不出去」决定**单次会不会爆掉** ——
 * T+1 之下遇到一字跌停，这一档没有任何止损手段。返回 null 表示样本为空。
 */
export function tailSummary(
  tail: LimitDownRepairResult["tail"] | undefined,
  sampleSize: number,
): string | null {
  if (!tail || !sampleSize) return null;
  const base = `次日跌停开盘 ${tail.drop9_n} / ${sampleSize} 次（${tail.drop9_rate}%）`;
  return tail.unsellable_n > 0
    ? `${base}，其中 ${tail.unsellable_n} 次一字封死、挂单也卖不出去`
    : base;
}
