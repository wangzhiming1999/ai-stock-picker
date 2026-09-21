import type { LimitUpFocus, LimitUpLadderGroup } from "../types";

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

/** 候选总数（两组相加只用于**计数展示**，两组的率不可比、不可加）。 */
export function focusCount(focus?: LimitUpFocus | null): number {
  if (!focus) return 0;
  return focus.relay.length + focus.first.length;
}

/**
 * 常驻条上的建议徽标文案。
 *
 * 用户反馈「这个可打板，但是没说打板什么」—— 所以 hunt 档在**折叠态就把候选数带出来**，
 * 让人知道展开后有具体标的与价位，而不是又一句结论。非 hunt 档不报数：
 * 那两档不给清单，报个数会让人以为清单被藏起来了。
 */
export function adviceBadgeText(advice: {
  level: string;
  title: string;
  focus?: LimitUpFocus | null;
}): string {
  if (advice.level !== "hunt") return `今日建议：${advice.title}`;
  const n = focusCount(advice.focus);
  return n > 0 ? `今日建议：${advice.title} · 候选 ${n} 只` : `今日建议：${advice.title} · 无可执行标的`;
}
