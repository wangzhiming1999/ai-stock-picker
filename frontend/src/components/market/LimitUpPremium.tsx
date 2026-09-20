import { useState } from "react";
import { TEXT } from "../../lib/ui";
import type { LimitUpPremiumSummary } from "../../types";
import { CaliberLine } from "../CaliberNote";
import { signedPct } from "./format";

/**
 * 涨停带「次日溢价读数」区块（口径 limitup_premium）。
 *
 * 这是项目里**唯一收益为正**的方向（涨停池 n=758 与日 K n=4953 两口径互证），
 * 但证据等级仍是「初步」—— 可成交性只是代理口径（池快照没有量比字段）。
 * 因此这一块有两条硬约束：
 *
 *   1. **期望与可成交性必须同时展示**：收益大头恰恰落在买不进的档
 *      （换手 <5% 期望最高，但缩量一字/秒板根本挂不上单）。
 *      只展示期望会诱导去追买不到的一字板；
 *   2. **不出现动作话术**，百分比一律挂在口径行之下 —— 与连板晋级率同一套纪律。
 *
 * 与「连板资金面」块的关系：那边讲能不能继续封板（状态），这边讲明天卖出赚多少（收益），
 * 两个口径不可相互换算、不可相加。
 */
function PremiumSection({ summary }: { summary?: LimitUpPremiumSummary }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!summary || summary.total === 0 || summary.buckets.length === 0) return null;
  const maxCount = Math.max(...summary.buckets.map((b) => b.count), 1);

  return (
    <div>
      <h3 className={TEXT.label}>次日溢价读数（涨停价买入 → 次日竞价卖出 · 非买入指令）</h3>
      <p className="mt-1.5 rounded-lg bg-slate-800/50 px-3 py-2 text-xs leading-relaxed text-ink-soft">
        {summary.headline}
      </p>

      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-faint">
        <span>今日涨停 {summary.total} 只</span>
        {summary.tradable && (
          <span className="text-ink-soft">
            可成交档（换手 ≥5%）{summary.tradable.count} 只 · 同档读数 {signedPct(summary.tradable.expect_low)} ~{" "}
            {signedPct(summary.tradable.expect_high)}
          </span>
        )}
        {summary.unbuyable && <span>缩量一字/秒板 {summary.unbuyable.count} 只（期望更高但挂不上单）</span>}
        {summary.late_seal_count > 0 && (
          <span className="text-amber-300">尾盘封板 {summary.late_seal_count} 只 —— 唯一负期望档</span>
        )}
      </div>

      <div className="mt-2 space-y-1">
        {summary.buckets.map((b) => (
          <div key={b.label}>
            <button
              type="button"
              onClick={() => setOpen(open === b.label ? null : b.label)}
              disabled={b.count === 0}
              className="flex w-full items-center gap-2 rounded-lg bg-slate-800/40 px-3 py-1.5 text-left transition-colors hover:bg-slate-800/70 disabled:cursor-default disabled:opacity-40"
            >
              <span className="w-20 shrink-0 text-xs text-ink-soft">换手 {b.label}</span>
              <span className={`w-16 shrink-0 text-xs font-semibold ${b.expect_pct > 0 ? "text-ink" : "text-amber-300"}`}>
                {signedPct(b.expect_pct)}
              </span>
              <span className="w-12 shrink-0 text-xs text-ink-faint">{b.count} 只</span>
              <span className="h-1.5 w-16 shrink-0 overflow-hidden rounded-full bg-slate-700/60" aria-hidden>
                <span
                  className="block h-full rounded-full bg-slate-500"
                  style={{ width: `${(b.count / maxCount) * 100}%` }}
                />
              </span>
              <span className="flex-1 truncate text-xs text-ink-faint">{b.note}</span>
              {!b.tradable && (
                <span className="shrink-0 rounded bg-amber-500/10 px-1.5 py-0.5 text-xs text-amber-300">
                  挂不上单
                </span>
              )}
            </button>
            {open === b.label && b.names.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-1 px-3">
                {b.names.map((n, i) => (
                  <span key={b.codes[i]} className="rounded bg-slate-800/70 px-1.5 py-0.5 text-xs text-ink-soft">
                    {n}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      <CaliberLine caliber={summary.caliber} />
    </div>
  );
}

export { PremiumSection };
