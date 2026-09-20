import {
  ArrowDownRight,
  ArrowUpRight,
  Bell,
  ClipboardCheck,
  Flame,
  RefreshCw,
  Sunrise,
  Target,
} from "lucide-react";
import { CARD, DIVIDER, SUB, TEXT } from "../lib/ui";
import { dirTone, upTone } from "../lib/tone";
import {
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
  const positionText = m?.position_suggestion?.match(/(\d+(?:\.\d+)?)成/)?.[1]
    ? `总仓位最多 ${Number(m.position_suggestion.match(/(\d+(?:\.\d+)?)成/)?.[1]) * 10}%`
    : m?.position_suggestion || "等待数据";
  const mainAction = hasPicks
    ? `今天有 ${picks.length} 只股票值得等买点`
    : "今天先不买，耐心等信号";
  /** 三格关键数之三：今天要不要动持仓 */
  const holdingAction = holdingCount > 0 ? `${holdingCount} 只待处理` : needLogin ? "登录后查看" : "无需操作";
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
          className="flex items-center gap-1 rounded-lg border border-slate-700 px-2.5 py-1 text-xs text-ink-muted transition-colors hover:text-ink"
        >
          <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} aria-hidden />
          刷新
        </button>
      </div>

      {err && (
        <div className="mt-3 rounded-xl border border-red-800/70 bg-red-950/40 px-3 py-2 text-xs text-red-300">{err}</div>
      )}

      {!data ? (
        <div className="mt-4 text-sm text-ink-faint">加载中…</div>
      ) : (
        <>
          {/* ① 主结论：全屏唯一一处 24px，视线第一落点 */}
          <div className={`mt-4 ${TEXT.hero} ${hasPicks ? upTone(300) : "text-amber-300"}`}>{mainAction}</div>
          {m?.trading_advice && (
            <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-ink-muted">{m.trading_advice}</p>
          )}

          {/* ② 三格关键数：方向 / 资金 / 持仓动作 */}
          <div className="mt-4 grid gap-2 sm:grid-cols-3">
            <div className={`${SUB} px-3 py-2.5`}>
              <div className={TEXT.meta}>大盘方向</div>
              <div className={`mt-0.5 text-lg font-semibold ${tone.text}`}>{m?.direction || "等待数据"}</div>
            </div>
            <div className={`${SUB} px-3 py-2.5`}>
              <div className={TEXT.meta}>资金安排</div>
              <div className={`mt-0.5 ${TEXT.num}`}>{positionText}</div>
            </div>
            <div className={`${SUB} px-3 py-2.5`}>
              <div className={TEXT.meta}>持仓动作</div>
              <div className={`mt-0.5 ${TEXT.num}`}>{holdingAction}</div>
            </div>
          </div>

          {/* 时段性提示：只在真的需要动手时出现 */}
          {data.is_tail_urgent && (
            <div className="mt-3 flex items-center gap-2 rounded-xl border border-red-800/50 bg-red-500/10 px-3 py-2 text-xs font-medium text-red-200">
              <Bell className="h-4 w-4 animate-pulse" aria-hidden />
              尾盘窗口（14:45–15:00）：收盘前必须完成挂单，否则今日无法操作
            </div>
          )}
          {phase === "closed" && (
            <div className="mt-3 rounded-xl border border-amber-800/40 bg-amber-500/5 px-3 py-2 text-xs text-amber-200/90">
              今日非交易日，下方为下一交易日关注池，开盘前可据此准备。
            </div>
          )}

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

          <p className={`mt-4 ${DIVIDER} pt-3 text-center text-xs leading-relaxed text-ink-faint`}>
            买点 / 止损 / 手数均为算法推导，仅供参考，不构成投资建议；据此操作风险自担。
          </p>
        </>
      )}
    </section>
  );
}
