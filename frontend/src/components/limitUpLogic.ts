import type { LimitUpLadderGroup } from "../types";

/**
 * 连板梯队的纯逻辑（与渲染分离，便于用 node:test 直接跑）。
 *
 * 抽出来的原因：`ladderGaps` 的边界条件不直观 —— 梯队最高档是「6板+」（6 及以上合并），
 * 所以判断断层时上界取的是**分桶 key** 而不是真实最高板数，
 * 否则「8 板 + 5 板」会被误报成 6、7 板断层。
 */

/**
 * 找出梯队里的断层档位。
 *
 * 只看首板以上、最高分桶以下：`2` 到 `top - 1` 之间计数为 0 的档位即为断层。
 * 首板不计（首板永远应该有）、最高档不计（它本身存在，只是数量可能很少）。
 */
export function ladderGaps(groups: LimitUpLadderGroup[]): number[] {
  if (groups.length === 0) return [];
  const counts = new Map(groups.map((g) => [g.key, g.count]));
  const top = Math.max(...groups.map((g) => g.key), 0);
  const gaps: number[] = [];
  for (let level = 2; level < top; level += 1) {
    if ((counts.get(level) ?? 0) === 0) gaps.push(level);
  }
  return gaps;
}
