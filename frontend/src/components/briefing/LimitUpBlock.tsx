import type { Briefing } from "../../types";
import { SUB, SUB_QUIET, TEXT } from "../../lib/ui";
import { CHIP, downTone, upTone } from "../../lib/tone";

/** 连板结论块：环境三档结论 + 资金面最强分组 + 持仓连板盯盘提示。
 *
 * 措辞直接透传后端（play_advice/headline 本身已带「不是买入指令」纪律）；
 * 层级配色只表达强弱方向（hunt 红 / watch 琥珀 / avoid 绿=离场），
 * 不发明新话术。区块在 limitup 为 null（后端获取失败）时整体隐藏。
 */
export function LimitUpBlock({ limitup }: { limitup: NonNullable<Briefing["limitup"]> }) {
  const advice = limitup.play_advice;
  const levelTone = advice
    ? advice.level === "hunt"
      ? upTone(300)
      : advice.level === "watch"
        ? "text-amber-300"
        : downTone(300)
    : "text-ink";
  const relays = limitup.holdings_relay ?? [];

  return (
    <div className="space-y-2">
      {advice && (
        <div className={`${SUB} px-3 py-2.5`}>
          <div className="flex items-center justify-between gap-2">
            <span className={`text-head font-semibold ${levelTone}`}>{advice.title}</span>
            <span className={TEXT.meta}>连板环境</span>
          </div>
          <ul className="mt-1 space-y-0.5">
            {advice.reasons.map((r, i) => (
              <li key={i} className="text-meta leading-relaxed text-ink-soft">
                · {r}
              </li>
            ))}
          </ul>
        </div>
      )}
      {limitup.headline && <p className="text-meta leading-relaxed text-ink-muted">{limitup.headline}</p>}
      {limitup.top_tier && limitup.top_tier.names.length > 0 && (
        <div className={`${SUB_QUIET} px-2 py-1.5`}>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className={`text-meta font-medium ${upTone(300)}`}>{limitup.top_tier.label}</span>
            <span className={TEXT.meta}>
              历史同档晋级读数 {limitup.top_tier.rate}%（n={limitup.top_tier.rate_n}）
            </span>
          </div>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {limitup.top_tier.names.map((n, i) => (
              <span key={i} className={`rounded-md px-1.5 py-0.5 text-meta ${CHIP.neutral.bg} ${CHIP.neutral.text}`}>
                {n}
              </span>
            ))}
          </div>
        </div>
      )}
      {relays.length > 0 && (
        <div className="space-y-1">
          <div className={TEXT.meta}>持仓中的连板股 · 按封板质量从弱到强排（走弱先动谁）</div>
          {relays.map((r) => (
            <div key={r.code} className={`${SUB_QUIET} px-2 py-1.5`}>
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-meta font-medium text-ink-strong">{r.name}</span>
                <span className={TEXT.meta}>
                  {r.boards}板 · {r.tier_label ?? `${r.score}/3 分`}
                </span>
              </div>
              <div className="mt-0.5 text-meta leading-relaxed text-ink-soft">{r.hint}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
