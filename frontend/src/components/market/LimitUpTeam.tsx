import { SUB_QUIET, TEXT } from "../../lib/ui";
import { playAdviceTone, upTone } from "../../lib/tone";
import type {
  LimitUpFocus,
  LimitUpFocusRow,
  LimitUpLadderGroup,
  LimitUpPlayAdvice,
  LimitUpRelayResult,
  LimitUpRelayStock,
  LimitUpSnapshot,
  LimitUpStock,
  LimitUpTierSummary,
} from "../../types";
import { adviceBadgeText, ladderGaps } from "../limitUpLogic";
import { tierChip, upPositionChip } from "./constants";

/**
 * 涨停带「连板梯队 / 涨停池列表」一侧的全部展示件。
 *
 * 原 `LimitUpBar.tsx` 里除了「次日溢价读数」（见 `LimitUpPremium.tsx`）以外的
 * 所有内联子组件都搬到了这里 —— 它们共享同一套口径纪律：
 *
 *   1. 不出现任何动作话术（买点 / 加仓 / 建议）；
 *   2. 位置标签只给中性或琥珀色，**不占红绿**；
 *   3. 所有百分比都自带样本量与口径（`CaliberLine`），不与「胜率」并列。
 *
 * 这一节是「连板接力」的**中间指标**视图：只有「能否继续封板」有正向线索，
 * 缺收益口径，因此后端证据等级停在「初步」、`evidence.actionable` 恒为 false。
 * 本组组件据此只做位置描述与情绪描述，不得渲染成买点。
 */

/** 折叠态徽标：档位 + 候选数（见 limitUpLogic.adviceBadgeText 的注释）。 */
function AdviceBadge({ advice }: { advice: LimitUpPlayAdvice }) {
  return (
    <span
      className={`inline-flex items-center gap-1 font-semibold ${playAdviceTone(advice.level)}`}
      title={advice.reasons.join("；")}
    >
      {adviceBadgeText(advice)}
    </span>
  );
}

/**
 * 一只打板候选：**打哪只 + 什么价**（用户反馈的核心缺口）。
 *
 * 价位是交易所规则算出来的事实，不是预测：封板股的今日价就是今日涨停价，
 * 次日涨停价 = 今日价 ×(1+限幅)。两行结构 —— 第一行给结论（票 + 两个价），
 * 第二行给可复核的依据（换手 / 封单比 / 首封 / 溢价读数）。
 */
function FocusRow({ r }: { r: LimitUpFocusRow }) {
  return (
    <div className={`${SUB_QUIET} px-3 py-2`}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <span className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <span className="text-body font-semibold text-ink">{r.name}</span>
          <span className="text-meta text-ink-muted">{r.code}</span>
          <span className="text-meta text-ink-muted">
            {r.boards} 板 · {r.sector}
          </span>
          {r.tier_label && (
            <span className={`text-meta ${r.tier === 1 ? "text-brand-light" : "text-ink-soft"}`}>{r.tier_label}</span>
          )}
        </span>
        <span className="text-meta text-ink-muted" title={r.expected_price_note}>
          打板价 <span className="font-semibold text-ink">{r.expected_price.toFixed(2)}</span>
          {r.next_limit_price != null && (
            <>
              <span className="mx-1 text-ink-faint">·</span>
              次日涨停价 <span className="font-semibold text-ink">{r.next_limit_price.toFixed(2)}</span>
              <span className={`ml-1 ${upTone(400)}`}>
                较今收 +{r.limit_pct}%
                {r.limit_pct === 20 ? "（创业板/科创板）" : r.limit_pct === 30 ? "（北交所）" : ""}
              </span>
            </>
          )}
        </span>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-meta text-ink-soft">
        <span>换手 {r.turnover}%</span>
        <span>封单/流通 {r.seal_ratio}%</span>
        <span>首封 {r.seal_time || "--"}</span>
        {r.break_count > 0 && <span className="text-amber-300">开板 {r.break_count} 次</span>}
        {r.seal_fund_yi != null && <span>封单 {r.seal_fund_yi} 亿</span>}
        {r.expect_pct != null && r.expect_pct > 0 && (
          <span>
            溢价读数 <span className="text-ink-soft">{r.expect_pct > 0 ? "+" : ""}{r.expect_pct}%</span>
          </span>
        )}
        {r.rate != null && (
          <span>
            明日晋级读数 <span className="text-ink-soft">{r.rate}%</span>
            <span className="text-ink-faint">（n={r.rate_n}）</span>
          </span>
        )}
      </div>
      {r.basis.length > 0 && (
        <ul className="mt-1 space-y-0.5">
          {r.basis.map((b) => (
            <li key={b} className="flex gap-1.5 text-meta leading-relaxed text-ink-soft">
              <span>✓</span>
              {b}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function FocusGroup({ title, rows, desc }: { title: string; rows: LimitUpFocusRow[]; desc: string }) {
  if (rows.length === 0) return null;
  return (
    <div>
      <div className="mb-1.5 flex flex-wrap items-baseline gap-x-2">
        <span className="text-meta font-semibold text-ink-muted">{title}</span>
        <span className="text-meta text-ink-muted">
          {rows.length} 只 · {desc}
        </span>
      </div>
      <div className="space-y-1.5">
        {rows.map((r) => (
          <FocusRow key={r.code} r={r} />
        ))}
      </div>
    </div>
  );
}

/**
 * 打板候选清单：回答「可打板，到底打什么、什么价」。
 *
 * 三条纪律（与整个涨停带一致，别在这里松口）：
 *   1. 只在**环境过关**（level=hunt）时出现。说「别动手」的同时给名单，是自相矛盾 ——
 *      后端就不下发 focus，这里也只做「有就渲染」。
 *   2. 连板与首板**分开列**：连板有明日晋级读数（n=164 连板样本），首板没有 ——
 *      两套读数口径不可比，合成一个名次等于造一个没有样本量的排名。
 *   3. 价位不是预测：「打板价」就是今日涨停价，「次日涨停价」是交易所规则算出来的。
 */
function FocusSection({ advice }: { advice: LimitUpPlayAdvice }) {
  const focus: LimitUpFocus | null | undefined = advice.focus;
  if (!focus) return null;
  const empty = focus.relay.length === 0 && focus.first.length === 0;

  return (
    <div className={`${SUB_QUIET} px-3 py-2.5`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-body font-semibold text-ink">打板候选（可执行性筛选 · 非买入指令）</h3>
        <span className="text-meta text-ink-muted">
          涨停池 {focus.total} 只
          {focus.cut > 0 && ` · ${focus.cut} 只达标但未进前列`}
        </span>
      </div>
      <p className="mt-1 text-meta leading-relaxed text-ink-soft">{focus.note}</p>

      {empty ? (
        <p className="mt-2 text-meta leading-relaxed text-ink-faint">
          没有可执行标的不是「今天不能打板」，而是这批涨停股在**可成交性**上不成立：
          缩量一字/秒板挂不上单，尾盘封板是唯一负期望档。这类日子里环境读数再好看也没有落点。
        </p>
      ) : (
        <div className="mt-2 space-y-3">
          <FocusGroup
            title="连板候选（有明日晋级读数）"
            rows={focus.relay}
            desc="晋级读数来自 n=164 连板样本，13 个交易日窗口，只作相对强弱"
          />
          <FocusGroup
            title="首板候选（无连板口径，只引溢价与封板时间档）"
            rows={focus.first}
            desc="首板没有对应的晋级样本，因此不借连板的数字"
          />
        </div>
      )}

      {Object.entries(focus.rejected).length > 0 && (
        <div className="mt-2 flex flex-wrap gap-x-3 gap-y-0.5 text-meta text-ink-muted">
          {Object.entries(focus.rejected).map(([key, n]) => (
            <span key={key}>
              剔除 {focus.rejected_labels[key] ?? key} <span className="text-ink-soft">{n}</span> 只
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/** 展开区顶部的建议详情：档位 + 判定理由 + 打板候选 + 执行剧本。 */
function AdviceSection({ advice }: { advice: LimitUpPlayAdvice }) {
  return (
    <>
      <div className={`${SUB_QUIET} px-3 py-2.5`}>
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className={`text-body font-semibold ${playAdviceTone(advice.level)}`}>
            {adviceBadgeText(advice)}
          </h3>
          <span className="text-meta text-ink-soft">主线 {advice.mainline}</span>
        </div>
        <ul className="mt-1.5 space-y-1">
          {advice.reasons.map((r) => (
            <li key={r} className="flex gap-1.5 text-meta leading-relaxed text-ink-soft">
              <span className="text-ink-faint">·</span>
              {r}
            </li>
          ))}
        </ul>
        <p className="mt-1.5 text-meta leading-relaxed text-ink-faint">
          判定依据是已回测的口径（炸板率当日横截面、板块聚集度对晋级率的影响、梯队断层结构）。
          连板接力整体仍是初步证据等级，所以这里的档位说的是**环境**；环境过关时下面才给候选与价位。
        </p>
      </div>

      <FocusSection advice={advice} />

      {!advice.focus && advice.focus_note && (
        <div className={`${SUB_QUIET} px-3 py-2.5`}>
          <h3 className="text-body font-semibold text-ink-muted">这次为什么没有候选清单</h3>
          <p className="mt-1 text-meta leading-relaxed text-ink-soft">{advice.focus_note}</p>
        </div>
      )}

      {advice.playbook && advice.playbook.length > 0 && (
        <div className={`${SUB_QUIET} px-3 py-2.5`}>
          <h3 className="text-body font-semibold text-ink">怎么执行（按顺序看）</h3>
          <ol className="mt-1.5 space-y-1">
            {advice.playbook.map((step, i) => (
              <li key={step} className="flex gap-2 text-meta leading-relaxed text-ink-soft">
                <span className="shrink-0 font-semibold text-ink-muted">{i + 1}.</span>
                {step}
              </li>
            ))}
          </ol>
        </div>
      )}
    </>
  );
}

/**
 * 单只连板股的资金面行：分层徽章 + 人话解释 + 得分/晋级读数。
 *
 * 可读性设计（用户反馈「看不懂哪个可以买」的解法）：
 * 把抽象的「3/3 分」前置翻译成「资金面最强」徽章 + 一句解释，
 * 数字（分 / %）退居次行——先给结论再看依据，而不是反过来。
 * 徽章仍是强弱描述而非买卖指令。
 */
function RelayStockRow({ r }: { r: LimitUpRelayStock }) {
  const tc = tierChip(r.tier);
  return (
    <div className={`${SUB_QUIET} px-3 py-2`}>
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <span className="flex flex-wrap items-center gap-2">
          <span className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-meta font-semibold ${tc.chip}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${tc.dot}`} aria-hidden />
            {r.tier_label ?? "未分层"}
          </span>
          <span className="text-body font-semibold text-ink">{r.name}</span>
          <span className="text-meta text-ink-muted">{r.code}</span>
          <span className="text-meta text-ink-muted">{r.boards} 板 · {r.sector}</span>
        </span>
        <span className="text-meta text-ink-muted">
          明日晋级读数 <span className="font-semibold text-ink">{r.rate}%</span>
          <span className="text-ink-faint">（回测 n={r.rate_n}）</span>
        </span>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-meta">
        <span className="text-ink-muted" title={r.tier_note}>
          {r.tier_note ?? `${r.score}/${r.max_score} 分`}
        </span>
        {r.factors.map((f) => (
          <span key={f.name} className={f.hit ? "text-brand-light" : "text-amber-300"} title={f.rule}>
            {f.hit ? "✓" : "✗"} {f.name}
            {f.name === "炸板次数" ? ` ${f.value} 次` : ` ${f.value}%`}
          </span>
        ))}
        <span className="text-ink-soft">封单 {r.seal_fund_yi} 亿 · 首封 {r.seal_time || "--"}</span>
      </div>
    </div>
  );
}

/**
 * 连板资金面区块：连板股抽离列表，每只按三因子打分并给明日晋级概率读数。
 *
 * 可读性分层（回答「哪个可以买」而不越证据闸门）：
 *   - 顶部一句 headline（后端 relay_tier_summary）：直接说今日哪些股资金面最强，
 *     同时点明「相对强弱分组 ≠ 买入指令」；
 *   - 列表按 tier 分组渲染，组标题带该档的历史晋级读数；
 *   - 单只行内「资金面最强」徽章前置，数字退居次行。
 * 措辞纪律不变：全文无动作词，position 是描述、读数带样本量。
 */
function RelayStocksSection({ stocks, summary }: { stocks: LimitUpRelayStock[]; summary?: LimitUpTierSummary }) {
  if (stocks.length === 0) return null;

  // 有分层字段（tier_label）才走分组视图；旧后端逐股缺省时退回平铺排序。
  const grouped = stocks.some((r) => r.tier != null);
  const groups = summary?.groups ?? [];
  // 按 tier 升序渲染（最强在前），组内保持后端已排好的顺序。
  const byTier = new Map<number, LimitUpRelayStock[]>();
  if (grouped) {
    for (const r of stocks) {
      const t = r.tier ?? 3;
      if (!byTier.has(t)) byTier.set(t, []);
      byTier.get(t)!.push(r);
    }
  }

  return (
    <div>
      <h3 className={TEXT.label}>连板资金面持续性（相对强弱分组 · 非买点）</h3>
      {summary && (
        <p className="mt-1.5 rounded-lg bg-surface-inset/50 px-3 py-2 text-meta leading-relaxed text-ink-soft">
          {summary.headline}
        </p>
      )}
      <div className="mt-2 space-y-3">
        {grouped
          ? [...byTier.entries()]
              .sort(([a], [b]) => a - b)
              .map(([tier, members]) => {
                const g = groups.find((x) => x.tier === tier);
                const tc = tierChip(tier);
                return (
                  <div key={tier}>
                    <div className="mb-1.5 flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                      <span className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-meta font-semibold ${tc.chip}`}>
                        <span className={`h-1.5 w-1.5 rounded-full ${tc.dot}`} aria-hidden />
                        {g?.label ?? members[0].tier_label ?? `第 ${tier} 梯队`}
                      </span>
                      <span className="text-meta text-ink-muted">
                        {members.length} 只 · 明日晋级读数 {g?.rate ?? members[0].rate}%（n={g?.rate_n ?? members[0].rate_n}）
                      </span>
                      {g?.desc && <span className="text-meta text-ink-muted">· {g.desc}</span>}
                    </div>
                    <div className="space-y-1.5">
                      {members.map((r) => (
                        <RelayStockRow key={r.code} r={r} />
                      ))}
                    </div>
                  </div>
                );
              })
          : stocks.map((r) => <RelayStockRow key={r.code} r={r} />)}
      </div>
      <p className="mt-2 text-meta leading-relaxed text-ink-faint">
        概率读数 = 回测窗口内同得分档连板股的次日晋级率（08-28~09-16，共 164 个连板样本）。
        三因子在控制连板高度后区分度仍在（2 板：低分 17.4% vs 高分 41.8%）。
        但窗口只有 ~13 个交易日，且晋级率 ≠ 收益率（一字板开盘买不进），只作相对强弱参考，不构成买点。
      </p>
    </div>
  );
}

function StockChip({ t }: { t: LimitUpStock }) {
  // 位置标注缺失时降级成「未知」而不是渲染空白：滚动发布期间前端可能连到旧后端，
  // 一个字段缺失不该让整段梯队失效（与 TacticHit 对 evidence 的兜底同思路）。
  const position = t.position ?? { tag: "未知", reason: "位置标注缺失" };
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-lg bg-surface-inset/60 px-2 py-1 text-meta"
      title={`${position.reason}｜封单 ${t.seal_fund_yi} 亿｜流通 ${t.float_mv_yi} 亿｜封单比 ${t.seal_ratio}%`}
    >
      <span className="text-ink">{t.name}</span>
      <span className="text-ink-muted">{t.code}</span>
      <span className="text-ink-muted">首封 {t.seal_time || "--"}</span>
      {t.break_count > 0 && <span className="text-amber-300">开板 {t.break_count} 次</span>}
      <span className={`rounded-md px-1 text-meta ${upPositionChip(position.tag)}`}>{position.tag}</span>
    </span>
  );
}

function LadderSection({ ladder }: { ladder: LimitUpLadderGroup[] }) {
  if (ladder.length === 0) return null;
  const max = Math.max(...ladder.map((g) => g.count), 1);
  const gaps = ladderGaps(ladder);
  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className={TEXT.label}>连板梯队（位置描述 · 非买点）</h3>
        {gaps.length > 0 && (
          <span className="text-meta text-amber-300">
            梯队断层：{gaps.map((g) => `${g}板`).join(" / ")} 空缺
          </span>
        )}
      </div>
      <div className="mt-2 space-y-1.5">
        {ladder.map((g) => (
          <div key={g.key} className="flex items-center gap-2">
            <span className="w-12 shrink-0 text-meta text-ink-muted">{g.label}</span>
            <span className="w-10 shrink-0 text-right text-meta font-semibold text-ink">{g.count}</span>
            <span className="h-2 shrink-0 rounded-full bg-brand/70" style={{ width: `${Math.max((g.count / max) * 100, 3)}%` }} />
          </div>
        ))}
      </div>
      <div className="mt-3 space-y-2">
        {ladder.map((g) => (
          <div key={g.key}>
            <div className="mb-1 text-meta text-ink-muted">
              {g.label} · {g.count} 只
            </div>
            <div className="flex flex-wrap gap-1.5">
              {g.items.map((t) => (
                <StockChip key={t.code} t={t} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function SectorSection({ snapshot }: { snapshot: LimitUpSnapshot }) {
  if (snapshot.sectors.length === 0) return null;
  return (
    <div>
      <h3 className={TEXT.label}>板块聚集度（当日涨停家数排序）</h3>
      <div className="mt-2 space-y-1">
        {snapshot.sectors.slice(0, 6).map((s) => (
          <div key={s.sector} className="flex items-center justify-between gap-2 text-meta">
            <span className="truncate text-ink-soft">{s.sector}</span>
            <span className="shrink-0 text-ink-muted">
              涨停 <span className="text-ink">{s.count}</span> 家 · 连板{" "}
              <span className="text-ink">{s.relay_count}</span> 家 · 最高{" "}
              <span className="text-ink">{s.max_boards}</span> 板 · 封单{" "}
              <span className="text-ink">{s.seal_fund_yi}</span> 亿
            </span>
          </div>
        ))}
      </div>
      <p className="mt-2 text-meta leading-relaxed text-ink-faint">
        按家数排序而非封单金额 —— 家数更能反映资金是否在这个板块里抱团。
        但下面对照表显示：**聚集度越高，首板晋级率反而越低**，所以它只能当情绪读，不能当买点。
      </p>
    </div>
  );
}

function RelaySection({ relay, loading, error }: { relay: LimitUpRelayResult | null; loading: boolean; error: string | null }) {
  if (loading && !relay) return <p className="text-meta text-ink-soft">正在回溯晋级率…</p>;
  if (error && !relay) return <p className="text-meta text-amber-300">{error}</p>;
  if (!relay) return null;

  const window = relay.data_window.length === 2 ? `${relay.data_window[0]} ~ ${relay.data_window[1]}` : "无";

  return (
    <div>
      <h3 className={TEXT.label}>连板晋级率回溯（N 板 → 次日 N+1 板）</h3>
      <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <div className={SUB_QUIET + " px-3 py-2"}>
          <div className="text-num font-bold text-ink">{relay.overall_rate}%</div>
          <div className="text-meta text-ink-muted">整体晋级率</div>
        </div>
        <div className={SUB_QUIET + " px-3 py-2"}>
          <div className="text-num font-bold text-ink">{relay.total_samples}</div>
          <div className="text-meta text-ink-faint">样本数 n</div>
        </div>
        <div className={SUB_QUIET + " px-3 py-2"}>
          <div className="text-num font-bold text-ink">{relay.sessions}</div>
          <div className="text-meta text-ink-muted">交易日对</div>
        </div>
        <div className={SUB_QUIET + " px-3 py-2"}>
          <div className="text-num font-bold text-ink-muted">{relay.baseline_rate}%</div>
          <div className="text-meta text-ink-muted">随机水平参照</div>
        </div>
      </div>

      <div className="mt-3 space-y-1">
        {relay.by_boards.map((b) => (
          <div key={b.key} className="flex items-center justify-between gap-2 text-meta">
            <span className="w-14 shrink-0 text-ink-muted">{b.label}</span>
            <span className="text-ink-soft">
              晋级 <span className="text-ink">{b.promoted}</span> / {b.total}（n={b.total}）
            </span>
            <span className="w-14 shrink-0 text-right font-semibold text-ink">{b.rate}%</span>
          </div>
        ))}
      </div>

      <h4 className="mt-3 text-meta font-semibold text-ink-muted">分层：控制连板高度后，再看板块聚集度</h4>
      <div className="mt-1 space-y-1">
        {relay.by_boards_cluster.map((row) => (
          <div key={row.boards} className="flex flex-wrap items-center gap-x-3 gap-y-1 text-meta">
            <span className="w-14 shrink-0 text-ink-muted">{row.label}</span>
            {row.clusters.map((c) => (
              <span key={c.cluster} className="text-ink-soft">
                {c.cluster} <span className="font-semibold text-ink">{c.rate}%</span>
                <span className="text-ink-faint">(n={c.total})</span>
              </span>
            ))}
          </div>
        ))}
      </div>

      <p className="mt-2 text-meta leading-relaxed text-ink-faint">
        数据窗口 {window}（{relay.effective_days} 个交易日）。
        {relay.empty_dates.length > 0 && ` 更早的 ${relay.empty_dates.length} 天接口返回空池，已识别为「无数据」并排除出样本。`}
        {relay.skipped_dates.length > 0 && ` 另有 ${relay.skipped_dates.length} 天拉取失败被跳过。`}
      </p>
    </div>
  );
}

export { AdviceBadge, AdviceSection, LadderSection, RelaySection, RelayStockRow, RelayStocksSection, SectorSection, StockChip };
