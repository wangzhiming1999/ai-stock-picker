import {
  ArrowDownRight,
  ArrowUpRight,
  Bell,
  ClipboardCheck,
  Flame,
  ListChecks,
  RefreshCw,
  Sunrise,
  Target,
} from "lucide-react";
import { CARD, DIVIDER, SUB, TEXT } from "../lib/ui";
import DecisionBadge from "./ui/DecisionBadge";
import { dirTone, upTone } from "../lib/tone";
import {
  ActionListPanel,
  LimitUpBlock,
  MorningStocksBlock,
  PreMarketBlock,
  ReviewBlock,
  Section,
  TailHoldingsBlock,
  TacticsBlock,
  useBriefing,
} from "./briefing";

interface Props {
  onPick: (codes: string[]) => void;
  onSettled?: () => void;
}

export default function DailyBriefing({ onPick, onSettled }: Props) {
  const { data, loading, err, load } = useBriefing(onSettled);

  const m = data?.market;
  const tone = dirTone(m?.direction ?? "");
  const phase = data?.phase ?? "morning";
  const picks = data?.morning.stocks ?? [];
  const hasPicks = picks.length > 0;
  const holdingCount = data?.tail.holdings.length ?? 0;
  const needLogin = Boolean(data?.tail.need_login);
  /**
   * 仓位上限：读后端**结构化** position_plan，不再用正则从 position_suggestion
   * 文案里抠「N成」—— LLM 换一种说法（「半仓」「控制在 50% 以内」）就抠不到，
   * 会静默退化成展示原文。
   */
  const plan = m?.position_plan;
  const positionText = plan?.position_cap_label ?? m?.position_suggestion ?? "等待数据";
  /** 主结论直接给动作。「今天先不买，耐心等信号」读起来像安慰，「不参与」才是决策。 */
  const mainAction = hasPicks
    ? `今天买入 ${picks.length} 只（到价才成交）`
    : "今天不参与（空仓等待）";
  /**
   * 三格关键数之三：今天要不要动持仓。
   * 此前这里是纯计数（「N 只待处理」）—— 没看任何信号就下结论，是个假决策。
   * 现在读 B 的结构化汇总：卖出/减仓/持有各有几只，按风险优先排序。
   */
  const holdingSummary = data?.tail.decisions_summary;
  const holdingAction = holdingSummary?.summary
    ? holdingSummary.summary
    : holdingCount > 0
      ? `${holdingCount} 只待处理`
      : needLogin
        ? "登录后查看"
        : "持有不动";
  const reviewReady = Boolean(data?.review && (data.review.summary || data.review.alerts_today));
  const tacticsReady = Boolean(
    data?.tactics && (data.tactics.holdings.length > 0 || data.tactics.morning.length > 0)
  );

  return (
    <section className={CARD}>
      {/* 卡片头：不套容器，靠字号与留白成层 */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Target className="h-4 w-4 text-brand-light" aria-hidden />
          <h1 className={TEXT.title}>今天怎么做</h1>
          {data && <span className={TEXT.meta}>· {data.target_date ?? "下一个交易日"}</span>}
        </div>
        <button
          onClick={() => void load()}
          disabled={loading}
          className="flex items-center gap-1 rounded-lg border border-surface-line px-2.5 py-1 text-meta text-ink-muted transition-colors hover:text-ink"
        >
          <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} aria-hidden />
          刷新
        </button>
      </div>

      {err && (
        <div className="mt-3 rounded-xl border border-state-danger-line bg-state-danger-surface px-3 py-2 text-meta text-state-danger-soft">{err}</div>
      )}

      {!data ? (
        <div className="mt-4 text-body text-ink-soft">加载中…</div>
      ) : (
        <>
          {/* ① 主结论：全屏唯一一处 24px，视线第一落点 */}
          <div className={`mt-4 ${TEXT.hero} ${hasPicks ? upTone(300) : "text-amber-300"}`}>{mainAction}</div>
          {m?.trading_advice && (
            <p className="mt-1 text-meta leading-relaxed text-ink-muted">{m.trading_advice}</p>
          )}

          {/* ② 三格关键数：方向 / 资金 / 持仓动作 */}
          <div className="mt-4 grid gap-2 sm:grid-cols-3">
            <div className={`${SUB} px-3 py-2.5`}>
              <div className={TEXT.meta}>大盘方向</div>
              <div className={`mt-0.5 text-num font-semibold ${tone.text}`}>{m?.direction || "等待数据"}</div>
            </div>
            <div className={`${SUB} px-3 py-2.5`}>
              <div className={TEXT.meta}>资金安排</div>
              <div className={`mt-0.5 ${TEXT.num}`}>{positionText}</div>
              {plan && <DecisionBadge decision={plan.action} className="mt-1" />}
            </div>
            <div className={`${SUB} px-3 py-2.5`}>
              <div className={TEXT.meta}>持仓动作</div>
              <div className={`mt-0.5 ${TEXT.num}`}>{holdingAction}</div>
            </div>
          </div>

          {/* ③ 结构化仓位决策：理由 + 加仓触发 + 降仓失效 + 板块名单。
              此前这里只有一句被截断的 trading_advice，用户读完不知道
              「到什么条件该加、什么信号出现要降」。 */}
          {plan && (
            <div className="mt-3 space-y-1.5">
              <div className={DIVIDER} />
              <p className={`${TEXT.label} pt-1.5`}>仓位决策 · 可复核</p>
              <p className="text-meta leading-relaxed text-ink-soft">{plan.reason}</p>
              <div className="grid gap-2 sm:grid-cols-2">
                <div className="rounded-lg bg-state-warn-surface/60 px-2.5 py-2">
                  <div className="text-label font-medium text-state-warn-soft">加仓触发</div>
                  <p className="mt-0.5 text-meta leading-relaxed text-ink-soft">{plan.trigger || "—"}</p>
                </div>
                <div className="rounded-lg bg-state-danger-surface/60 px-2.5 py-2">
                  <div className="text-label font-medium text-state-danger-soft">降仓失效</div>
                  <p className="mt-0.5 text-meta leading-relaxed text-ink-soft">{plan.invalidation || "—"}</p>
                </div>
              </div>
              {(plan.sectors_long.length > 0 || plan.sectors_avoid.length > 0) && (
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-meta">
                  {plan.sectors_long.length > 0 && (
                    <span className="text-ink-soft">
                      资金进场：<b className="text-brand-light">{plan.sectors_long.join("、")}</b>
                    </span>
                  )}
                  {plan.sectors_avoid.length > 0 && (
                    <span className="text-ink-soft">
                      资金撤离：<b className="text-amber-300">{plan.sectors_avoid.join("、")}</b>
                    </span>
                  )}
                </div>
              )}
              <p className="text-micro leading-relaxed text-ink-faint">
                {plan.disclaimer}
                分位与四态为当日横截面口径，换日即换基准、不可跨日比较。
              </p>
            </div>
          )}

          {/* 时段性提示：只在真的需要动手时出现 */}
          {data.is_tail_urgent && (
            <div className="mt-3 flex items-center gap-2 rounded-xl border border-state-danger-line bg-red-500/10 px-3 py-2 text-meta font-medium text-state-danger-soft">
              <Bell className="h-4 w-4 animate-pulse" aria-hidden />
              尾盘窗口（14:45–15:00）：收盘前必须完成挂单，否则今日无法操作
            </div>
          )}
          {phase === "closed" && (
            <div className="mt-3 rounded-xl border border-state-warn-line bg-amber-500/5 px-3 py-2 text-meta text-state-warn-soft">
              今日非交易日，下方为下一交易日关注池，开盘前可据此准备。
            </div>
          )}

          {/* ④ 今日总指令（C）：各链路结论按风险优先排成一张清单。
              ⚠️ 刻意不做加权合成分 —— 各链路高度相关，相加等于放大同一轮行情。 */}
          <Section icon={<ListChecks className="h-4 w-4 text-brand-light" aria-hidden />} title="今日总指令">
            <ActionListPanel data={data.action_list} />
          </Section>

          {/* ③ 分区：尾盘操作（有持仓才出现，避免空段占位） */}
          {phase === "tail" && (holdingCount > 0 || needLogin) && (
            <Section icon={<Bell className="h-4 w-4 text-brand-light" aria-hidden />} title={`尾盘操作（${data.tail.summary ?? "持仓决策"}）`}>
              <TailHoldingsBlock tail={data.tail} />
            </Section>
          )}

          {/* ③ 分区：今天关注这几只（任何时段都作为今日清单） */}
          <Section
            icon={
              phase === "morning" ? (
                <ArrowUpRight className={`h-4 w-4 ${upTone(400)}`} aria-hidden />
              ) : (
                <ArrowDownRight className="h-4 w-4 text-ink-muted" aria-hidden />
              )
            }
            title={hasPicks ? "今天关注这几只" : "为什么今天没有推荐"}
            hint={hasPicks ? <span className={TEXT.meta}>共 {picks.length} 只</span> : undefined}
          >
            <MorningStocksBlock stocks={picks} onPick={onPick} />
          </Section>

          {/* ③ 分区：盘前预读（仅 9:00–9:25） */}
          {data.is_premarket && (
            <Section icon={<Sunrise className="h-4 w-4 text-amber-400" aria-hidden />} title="盘前预读">
              <PreMarketBlock data={data} />
            </Section>
          )}

          {/* ③ 分区：当日复盘 */}
          {reviewReady && data.review && (
            <Section icon={<ClipboardCheck className="h-4 w-4 text-brand-light" aria-hidden />} title="当日复盘">
              <ReviewBlock review={data.review} />
            </Section>
          )}

          {/* ③ 分区：形态命中（附加信息，放最后） */}
          {tacticsReady && data.tactics && (
            <Section icon={<Target className="h-4 w-4 text-sky-400" aria-hidden />} title="形态命中">
              <TacticsBlock tactics={data.tactics} onPick={onPick} />
            </Section>
          )}

          {/* ③ 分区：连板结论（早盘直接回答「今天能不能碰连板」；数据缺失整体隐藏） */}
          {data.limitup && (
            <Section icon={<Flame className="h-4 w-4 text-orange-400" aria-hidden />} title="连板梯队">
              <LimitUpBlock limitup={data.limitup} />
            </Section>
          )}

          <p className={`mt-4 ${DIVIDER} pt-3 text-center text-meta leading-relaxed text-ink-faint`}>
            买点 / 止损 / 手数均为算法推导，仅供参考，不构成投资建议；据此操作风险自担。
          </p>
        </>
      )}
    </section>
  );
}
