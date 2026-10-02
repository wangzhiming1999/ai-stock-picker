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
 *   2. **指令卡不等于买入信号**：顶部「主交易指令卡」把统计读数转成执行计划
 *      （买/持/卖 + 赢面 + 候选），但仍是 preliminary、非买入指令、不进买卖点位置
 *      （ACTIONABLE_TIERS 仅 verified）。百分比口径说明挂在卡片下方 CaliberLine。
 *
 * 与「连板资金面」块的关系：那边讲能不能继续封板（状态），这边讲明天卖出赚多少（收益），
 * 两个口径不可相互换算、不可相加。
 */
function PlanStep({ idx, label, detail }: { idx: number; label: string; detail: string }) {
  return (
    <div className="flex-1 rounded-lg border border-surface-line/70 bg-surface-inset/40 px-2 py-1.5 text-center">
      <div className="flex items-center justify-center gap-1">
        <span className="flex h-4 w-4 items-center justify-center rounded-full bg-surface-line text-meta font-semibold text-ink-muted">{idx}</span>
        <span className="text-meta font-semibold text-brand-light">{label}</span>
      </div>
      <div className="mt-0.5 text-meta leading-tight text-ink-soft">{detail}</div>
    </div>
  );
}

function TradeInstructionCard({ summary }: { summary?: LimitUpPremiumSummary }) {
  const caliber = summary?.caliber;
  if (!caliber?.plan_horizon) return null;
  const tradableCount = summary?.tradable?.count ?? 0;
  return (
    <div className="rounded-xl border border-brand/30 bg-surface-raised px-3 py-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-meta font-semibold text-brand-light">执行计划模板 · 打板可成交档</span>
        {caliber.registered && (
          <span className="rounded-md bg-surface-line/60 px-1.5 py-0.5 text-meta text-ink-muted">证据：初步（未验证）</span>
        )}
      </div>

      <p className="mt-1.5 text-meta leading-relaxed text-ink-soft">
        这是<span className="font-semibold text-state-warn-soft">历史统计转成的执行计划模板</span>，
        <span className="font-semibold text-state-warn-soft">不是买入指令、不是收益承诺</span>；具体买哪只看下方「可打板」清单。
      </p>

      <div className="mt-2">
        <div className="text-meta text-ink-muted">执行节奏 · 系统定周期（非自选）</div>
        <div className="mt-1 flex items-stretch gap-1">
          <PlanStep idx={1} label="买" detail="涨停价打板" />
          <span className="self-center text-meta text-ink-muted" aria-hidden>→</span>
          <PlanStep idx={2} label="持" detail={caliber.plan_horizon} />
          <span className="self-center text-meta text-ink-muted" aria-hidden>→</span>
          <PlanStep idx={3} label="卖" detail="次日竞价" />
        </div>
      </div>

      <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-meta text-ink-soft">
        <span>
          历史赢面：<span className="text-ink">约 55–61%</span>
        </span>
        <span>
          可打板候选：<span className="text-ink">{tradableCount} 只</span>
          <span className="text-ink-muted">（换手 ≥5%）</span>
        </span>
      </div>

      <p className="mt-1.5 text-meta leading-relaxed text-ink-muted">
        已剔除换手&lt;5% / 炸板≥3 / 尾盘封板。到期按系统制定周期结算赢 / 输，胜率口径见下方 CaliberLine。
      </p>
      {caliber.win_rate && (
        <p className="mt-1 text-meta leading-relaxed text-ink-muted">{caliber.win_rate}</p>
      )}
    </div>
  );
}

function PremiumSection({ summary }: { summary?: LimitUpPremiumSummary }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!summary || summary.total === 0 || summary.buckets.length === 0) return null;
  const maxCount = Math.max(...summary.buckets.map((b) => b.count), 1);

  return (
    <div>
      <h3 className={TEXT.label}>次日溢价读数（涨停价买入 → 次日竞价卖出）</h3>
      <TradeInstructionCard summary={summary} />
      <p className="mt-1.5 rounded-lg bg-surface-inset/50 px-3 py-2 text-meta leading-relaxed text-ink-soft">
        {summary.headline}
      </p>

      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-meta text-ink-muted">
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
              className="flex w-full items-center gap-2 rounded-lg bg-surface-inset/40 px-3 py-1.5 text-left transition-colors hover:bg-surface-inset/70 disabled:cursor-default disabled:opacity-40"
            >
              <span className="w-20 shrink-0 text-meta text-ink-soft">换手 {b.label}</span>
              <span className={`w-16 shrink-0 text-meta font-semibold ${b.expect_pct > 0 ? "text-ink" : "text-amber-300"}`}>
                {signedPct(b.expect_pct)}
              </span>
              <span className="w-12 shrink-0 text-meta text-ink-muted">{b.count} 只</span>
              <span className="h-1.5 w-16 shrink-0 overflow-hidden rounded-full bg-surface-line/60" aria-hidden>
                <span
                  className="block h-full rounded-full bg-surface-line-strong"
                  style={{ width: `${(b.count / maxCount) * 100}%` }}
                />
              </span>
              <span className="flex-1 truncate text-meta text-ink-soft">{b.note}</span>
              {!b.tradable && (
                <span className="shrink-0 rounded-md bg-amber-500/10 px-1.5 py-0.5 text-meta text-amber-300">
                  挂不上单
                </span>
              )}
            </button>
            {open === b.label && b.names.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-1 px-3">
                {b.names.map((n, i) => (
                  <span key={b.codes[i]} className="rounded-md bg-surface-inset/70 px-1.5 py-0.5 text-meta text-ink-soft">
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
