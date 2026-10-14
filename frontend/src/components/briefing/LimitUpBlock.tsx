import type { Briefing } from "../../types";
import { SUB, SUB_QUIET, TEXT } from "../../lib/ui";
import { CHIP, downTone, upTone } from "../../lib/tone";

/** 连板结论块：环境三档结论 + 可成交候选（含价位）+ 资金面最强分组 + 持仓连板盯盘提示。
 *
 * 措辞直接透传后端（play_advice/headline 本身已带「不是买入指令」纪律）；
 * 层级配色只表达强弱方向（hunt 红 / watch 琥珀 / avoid 绿=离场），
 * 不发明新话术。区块在 limitup 为 null（后端获取失败）时整体隐藏。
 *
 * ⚠️ 2026-10-14 改（用户反馈「连板也不知道买什么，根本不明确」）：
 * 首屏原来只给「资金面最强档的票名」，而那一档按得分排序、**不看能不能买到** ——
 * 三因子的「换手低」与可成交门槛「换手 ≥5%」方向相反，榜首常是挂不上单的一字板
 * （实测 tier1 榜首换手 0.76%）。现在首屏直接给：
 *   1. 「可成交候选」+ 打板价 / 次日涨停价（`advice.focus`，价位由档位恒定下发）；
 *   2. 资金面最强档拆成「买得进」与「挂不上单」两列，不再把一字板混在名单里。
 * 清单与推荐解耦：环境不过关时清单照给，但标题写明「非今日推荐」。
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

  const focus = advice?.focus ?? null;
  const actionable = advice?.focus_actionable === true;
  const hasFocus = !!focus && (focus.relay.length > 0 || focus.first.length > 0);

  // 分层摘要的「买得进 / 挂不上单」拆分。旧后端没有 tradable_names（undefined）时不做拆分 ——
  // 缺字段时按空数组处理会把全部票误判成「挂不上单」，那是把一个字段缺失渲染成一个错误结论。
  const tt = limitup.top_tier;
  const ttSplit = !!tt && tt.tradable_names !== undefined;
  const ttBuyable = tt?.tradable_names ?? [];
  const ttBlocked = ttSplit ? tt!.names.filter((n) => !ttBuyable.includes(n)) : [];

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

      {hasFocus && focus && (
        <div className={`${SUB_QUIET} px-2 py-1.5`}>
          <div className="flex flex-wrap items-baseline justify-between gap-1.5">
            <span className="text-meta font-medium text-ink">
              {actionable ? "今日可打板候选" : "可成交候选（非今日推荐）"}
            </span>
            <span className={TEXT.meta}>
              涨停池 {focus.total} 只中 {focus.relay.length + focus.first.length} 只通过可成交性硬筛
            </span>
          </div>
          {(["relay", "first"] as const).map((kind) => {
            const rows = kind === "relay" ? focus.relay.slice(0, 3) : focus.first.slice(0, 2);
            if (rows.length === 0) return null;
            return (
              <div key={kind} className="mt-1">
                <div className={TEXT.meta}>
                  {kind === "relay" ? "连板" : "首板"} · 共 {kind === "relay" ? focus.relay.length : focus.first.length} 只
                </div>
                <div className="mt-0.5 space-y-0.5">
                  {rows.map((r) => (
                    <div key={r.code} className="flex flex-wrap items-baseline gap-x-2 text-meta">
                      <span className="font-medium text-ink-strong">{r.name}</span>
                      <span className="text-ink-muted">
                        {r.boards} 板 · {r.sector}
                      </span>
                      <span className="text-ink-soft">
                        打板 <span className="font-semibold text-ink">{r.expected_price.toFixed(2)}</span>
                        {r.next_limit_price != null && (
                          <>
                            <span className="mx-1 text-ink-faint">·</span>
                            次日涨停{" "}
                            <span className="font-semibold text-ink">{r.next_limit_price.toFixed(2)}</span>
                          </>
                        )}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
          <p className="mt-1 text-meta leading-relaxed text-ink-faint">
            价位是交易所涨跌幅规则算出来的（今日涨停价 / 次日涨停价），不是预测。
            {actionable
              ? "连板与首板读数口径不同，两组不可比、也不相加。"
              : `环境档位是「${advice?.title ?? "非可打板"}」，所以这份名单只说明哪些挂得上单，不是今天的推荐。`}
          </p>
        </div>
      )}

      {limitup.headline && <p className="text-meta leading-relaxed text-ink-muted">{limitup.headline}</p>}

      {tt && tt.names.length > 0 && (
        <div className={`${SUB_QUIET} px-2 py-1.5`}>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className={`text-meta font-medium ${upTone(300)}`}>{tt.label}</span>
            <span className={TEXT.meta}>
              历史同档晋级读数 {tt.rate}%（n={tt.rate_n}）
            </span>
          </div>
          {ttSplit ? (
            <>
              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                <span className={TEXT.meta}>买得进</span>
                {ttBuyable.length > 0 ? (
                  ttBuyable.map((n, i) => (
                    <span key={i} className={`rounded-md px-1.5 py-0.5 text-meta ${CHIP.neutral.bg} ${CHIP.neutral.text}`}>
                      {n}
                    </span>
                  ))
                ) : (
                  <span className="text-meta text-amber-300">该档一只都挂不上单</span>
                )}
              </div>
              {ttBlocked.length > 0 && (
                <div className="mt-0.5 text-meta leading-relaxed text-ink-faint">
                  同档另有 {ttBlocked.length} 只挂不上单：{ttBlocked.join("、")}（换手 &lt;5%，缩量一字 / 秒板）。
                </div>
              )}
            </>
          ) : (
            <div className="mt-1 flex flex-wrap gap-1.5">
              {tt.names.map((n, i) => (
                <span key={i} className={`rounded-md px-1.5 py-0.5 text-meta ${CHIP.neutral.bg} ${CHIP.neutral.text}`}>
                  {n}
                </span>
              ))}
            </div>
          )}
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
