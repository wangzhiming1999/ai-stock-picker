import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown, RefreshCw, TrendingDown } from "lucide-react";
import { fetchLimitDownRepair, fetchLimitDownSnapshot } from "../api/client";
import { downTone, pnlTone, sentimentTone } from "../lib/tone";
import { DIVIDER, SUB, SUB_QUIET, TEXT } from "../lib/ui";
import type {
  LimitDownBucket,
  LimitDownLadderGroup,
  LimitDownRepairResult,
  LimitDownSnapshot,
  LimitDownStock,
} from "../types";
import { CaliberLine } from "./CaliberNote";
import { extremeBuckets, fmtDownUpRatio, tailSummary, winRateShortfall } from "./limitDownLogic";

/**
 * 跌停池常驻条（全局可见，不占一级导航）。
 *
 * 与 `LimitUpBar` 对称：那边读「做多的温度」，这边读「抛压的温度」。
 * 同样刻意不进 NAV —— 它是「读市场」而不是「做一件事」。
 *
 * ## 它是什么
 * 跌停家数 / 连跌家数 / 跌停最集中的板块 —— 一屏看出当日抛压有多重；
 * 展开后是连跌梯队、板块聚集度，以及**跌停次日修复收益的真实读数**。
 *
 * ## 它不是什么（这一节比上面重要）
 * **这不是抄底信号。** 这个策略的收益口径**可回测，而且结论是负的**：
 * 13 个交易日、133 个样本上，D 日跌停价买入 → D+1 集合竞价卖出的期望是
 * **−4.47%/次、胜率 4.5%**，打平需要 80.6% 的胜率。所以后端证据等级是
 * `unsupported` —— 不是「还没跑」，而是「有明确结论且为负」，`actionable` 恒为 false。
 * 本组件据此：
 *
 *   1. 不出现任何动作话术（抄底 / 买入 / 低吸 / 建议）；
 *   2. 位置标签（首跌/换手/封死/连跌/深跌）只给中性或琥珀色，**不占红绿**
 *      —— 红绿是方向语义，用在这里会被读成「该动手了」；
 *   3. 所有收益读数都带样本量与口径（`CaliberLine`），并把**打平胜率与实际胜率的
 *      缺口摆在最显眼处** —— 那是这个方向到底成不成立的关键数字。
 *
 * ## 数据源
 * 东财 `push2ex` 跌停板池（`getTopicDTPool`），与 `spot_service` 的 `push2`
 * 全市场快照是不同域名/端点，所以**不接** `spotGuard` 那套冷却闸门。
 *
 * ⚠️ 修复回测只在展开时拉一次：那条链路要为每只跌停股拉一次日 K，成本远高于快照，
 * 因此**不做轮询**（守卫用 ref，避免重复展开重复请求）。
 */

const POLL_INTERVAL = 60_000; // 与后端 60s 内存缓存同拍，不必更密

/**
 * 位置标签配色，全部走中性 / 琥珀。
 *
 * 跌得越深风险越高，但它既不预示继续跌（不用绿）也不预示反弹（不用红）——
 * 「跌很多」之后既可能修复也可能继续崩，这个组件不替用户判断是哪一种。
 */
const POSITION_CHIP: Record<string, string> = {
  首跌: "bg-slate-800/70 text-ink-soft",
  换手: "bg-slate-700/70 text-ink-soft",
  封死: "bg-amber-500/10 text-amber-300",
  连跌: "bg-amber-500/10 text-amber-300",
  深跌: "bg-amber-500/10 text-amber-300",
};

function positionChip(tag: string): string {
  return POSITION_CHIP[tag] ?? "bg-slate-800/70 text-ink-muted";
}

function StatTile({ value, label, tone }: { value: string | number; label: string; tone?: string }) {
  return (
    <div className={SUB_QUIET + " px-3 py-2"}>
      <div className={`text-lg font-bold ${tone ?? "text-ink"}`}>{value}</div>
      <div className="text-xs text-ink-faint">{label}</div>
    </div>
  );
}

/** 一个收益切片：期望收益 / 胜率 / 打平线。负期望用绿（跌的语义）。 */
function BucketRow({ b }: { b: LimitDownBucket }) {
  if (!b.n) return null;
  const expect = b.expect_open ?? 0;
  return (
    <div className="flex items-center justify-between gap-2 text-xs">
      <span className="w-24 shrink-0 truncate text-ink-muted" title={b.label}>
        {b.label}
      </span>
      <span className="text-ink-soft">
        n={b.n} · 胜率 <span className="text-ink">{b.win_rate_open ?? "—"}%</span>
        <span className="text-ink-faint"> · 打平需 {b.breakeven_win_rate ?? "—"}%</span>
      </span>
      <span className={`w-16 shrink-0 text-right font-semibold ${pnlTone(b.expect_open)}`}>
        {expect > 0 ? "+" : ""}
        {b.expect_open ?? "—"}%
      </span>
    </div>
  );
}

function StockChip({ t }: { t: LimitDownStock }) {
  // 位置标注缺失时降级成「未知」而不是渲染空白：滚动发布期间前端可能连到旧后端，
  // 一个字段缺失不该让整段梯队失效（与 TacticCell / TacticHit 的兜底同思路）。
  const position = t.position ?? { tag: "未知", reason: "位置标注缺失" };
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-lg bg-slate-800/60 px-2 py-1 text-xs"
      title={`${position.reason}｜封单 ${t.seal_fund_yi} 亿｜流通 ${t.float_mv_yi} 亿｜封单比 ${t.seal_ratio}%`}
    >
      <span className="text-ink">{t.name}</span>
      <span className="text-ink-faint">{t.code}</span>
      {t.down_days > 1 && <span className={downTone(400)}>{t.down_days} 连跌</span>}
      <span className="text-ink-muted">换手 {t.turnover}%</span>
      <span className={`rounded px-1 text-xs ${positionChip(position.tag)}`}>{position.tag}</span>
    </span>
  );
}

function LadderSection({ ladder }: { ladder: LimitDownLadderGroup[] }) {
  if (ladder.length === 0) return null;
  const max = Math.max(...ladder.map((g) => g.count), 1);
  return (
    <div>
      <h3 className={TEXT.label}>连续跌停梯队（位置描述 · 非买点）</h3>
      <div className="mt-2 space-y-1.5">
        {ladder.map((g) => (
          <div key={g.key} className="flex items-center gap-2">
            <span className="w-16 shrink-0 text-xs text-ink-muted">{g.label}</span>
            <span className="w-10 shrink-0 text-right text-xs font-semibold text-ink">{g.count}</span>
            <span
              className="h-2 shrink-0 rounded-full bg-green-600/70"
              style={{ width: `${Math.max((g.count / max) * 100, 3)}%` }}
            />
          </div>
        ))}
      </div>
      <div className="mt-3 space-y-2">
        {ladder.map((g) => (
          <div key={g.key}>
            <div className="mb-1 text-xs text-ink-faint">
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

function SectorSection({ snapshot }: { snapshot: LimitDownSnapshot }) {
  if (snapshot.sectors.length === 0) return null;
  return (
    <div>
      <h3 className={TEXT.label}>跌停板块聚集度（当日跌停家数排序）</h3>
      <div className="mt-2 space-y-1">
        {snapshot.sectors.slice(0, 6).map((s) => (
          <div key={s.sector} className="flex items-center justify-between gap-2 text-xs">
            <span className="truncate text-ink-soft">{s.sector}</span>
            <span className="shrink-0 text-ink-muted">
              跌停 <span className={downTone(400)}>{s.count}</span> 家 · 连跌{" "}
              <span className={downTone(400)}>{s.chain_count}</span> 家 · 最长{" "}
              <span className="text-ink">{s.max_down_days}</span> 日 · 封单{" "}
              <span className="text-ink">{s.seal_fund_yi}</span> 亿
            </span>
          </div>
        ))}
      </div>
      <p className="mt-2 text-xs leading-relaxed text-ink-faint">
        这里的家数**与涨停侧方向相反**：涨停板块家数多是资金抱团做多，跌停板块家数多是板块级利空。
        回测显示聚集度越高次日反而越差（≥5 家期望 −7.17%），所以它是风险读数，不是机会读数。
      </p>
    </div>
  );
}

/**
 * 修复率回溯区块 —— 本组件的核心，也是唯一能回答「抄底到底行不行」的地方。
 *
 * 排版顺序刻意是「结论 → 依据 → 边界」：先给期望与胜率缺口，再给分桶，
 * 最后给尾部风险和窗口说明。反过来（先铺一堆分桶数字）读者会先形成「有规律可找」
 * 的印象，再去读那个负号就晚了。
 */
function RepairSection({
  repair,
  loading,
  error,
}: {
  repair: LimitDownRepairResult | null;
  loading: boolean;
  error: string | null;
}) {
  if (loading && !repair) {
    return <p className="text-xs text-ink-faint">正在回溯修复收益…（需为每只跌停股拉取日 K，约数秒）</p>;
  }
  if (error && !repair) return <p className="text-xs text-amber-300">{error}</p>;
  if (!repair) return null;

  const o = repair.overall;
  const shortfall = winRateShortfall(o);
  const window = repair.data_window.length === 2 ? `${repair.data_window[0]} ~ ${repair.data_window[1]}` : "无";
  const tail = tailSummary(repair.tail, repair.sample_size);
  const extremes = extremeBuckets(
    [...repair.by_sealed, ...repair.by_cluster, ...repair.by_down_days],
    5,
  );

  return (
    <div>
      <h3 className={TEXT.label}>跌停次日修复收益（实测 · 非机会）</h3>
      <p className="mt-1.5 rounded-lg bg-slate-800/50 px-3 py-2 text-xs leading-relaxed text-ink-soft">
        口径：D 日以跌停价（= 收盘价）买入，<span className="text-ink">D+1 集合竞价卖出</span>。
        {shortfall != null && (
          <>
            {" "}
            实测离打平还差 <span className="font-semibold text-ink">{shortfall}</span> 个百分点的胜率
            —— 这个方向是<span className="font-semibold text-ink">负期望</span>，不是「没筛对条件」。
          </>
        )}
      </p>

      <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <StatTile value={`${o.expect_open ?? "—"}%`} label="期望收益 / 次" tone={pnlTone(o.expect_open)} />
        <StatTile value={`${o.win_rate_open ?? "—"}%`} label="竞价为正的比例" />
        <StatTile value={`${o.breakeven_win_rate ?? "—"}%`} label="打平所需胜率" tone="text-amber-300" />
        <StatTile value={o.n} label={`样本 n（${repair.effective_days} 个交易日）`} />
      </div>

      <div className="mt-3 space-y-1 text-xs">
        <div className="flex items-center justify-between gap-2">
          <span className="text-ink-muted">对照组：持有到 D+1 收盘才卖</span>
          <span className="text-ink-soft">
            期望{" "}
            <span className={`font-semibold ${pnlTone(o.expect_close)}`}>{o.expect_close ?? "—"}%</span>
            <span className="text-ink-faint"> · 胜率 {o.win_rate_close ?? "—"}%</span>
          </span>
        </div>
        <div className="flex items-center justify-between gap-2">
          <span className="text-ink-muted">次日盘中最高价（反抽弹性）</span>
          <span className="text-ink-soft">
            平均 <span className={`font-semibold ${pnlTone(o.avg_high)}`}>{o.avg_high ?? "—"}%</span>
            <span className="text-ink-faint"> · 盘中曾转正 {o.high_positive_rate ?? "—"}%</span>
          </span>
        </div>
      </div>

      <h4 className="mt-3 text-xs font-semibold text-ink-muted">按 D 日封板状态</h4>
      <div className="mt-1 space-y-1">
        {repair.by_sealed.map((b) => (
          <BucketRow key={b.key} b={b} />
        ))}
      </div>

      <h4 className="mt-3 text-xs font-semibold text-ink-muted">按同一板块当天跌停家数</h4>
      <div className="mt-1 space-y-1">
        {repair.by_cluster.map((b) => (
          <BucketRow key={b.key} b={b} />
        ))}
      </div>

      <h4 className="mt-3 text-xs font-semibold text-ink-muted">按连续跌停天数</h4>
      <div className="mt-1 space-y-1">
        {repair.by_down_days.map((b) => (
          <BucketRow key={b.key} b={b} />
        ))}
      </div>

      {extremes.best && (
        <p className="mt-2 text-xs leading-relaxed text-ink-faint">
          n≥5 的切片里表现最好的一档是「{extremes.best.label}」（期望{" "}
          {extremes.best.expect_open ?? "—"}%、n={extremes.best.n}），最差是「
          {extremes.worst?.label ?? "—"}」（{extremes.worst?.expect_open ?? "—"}%）——
          <span className="text-ink-soft">两档都是负的</span>，所以这不是「换一类就好了」的问题。
        </p>
      )}

      {tail && (
        <p className="mt-2 rounded-lg bg-amber-500/10 px-3 py-2 text-xs leading-relaxed text-amber-300">
          {tail} —— T+1 之下这一档没有任何止损手段，是这条路径最需要防范的地方。
        </p>
      )}

      <p className="mt-2 text-xs leading-relaxed text-ink-faint">
        数据窗口 {window}（{repair.effective_days} 个交易日）。
        {repair.truncated &&
          ` 候选 ${repair.candidate_size} 个超出样本上限，只统计了最近的 ${repair.sample_size} 个。`}
        {repair.out_of_window_dates.length > 0 &&
          ` 更早的 ${repair.out_of_window_dates.length} 天接口不提供数据（已排除）。`}
        {repair.zero_down_dates.length > 0 &&
          ` 另有 ${repair.zero_down_dates.length} 天全市场无跌停 —— 那不是数据缺失。`}
        {repair.skipped_dates.length > 0 && ` 还有 ${repair.skipped_dates.length} 天拉取失败被跳过。`}
        窗口只有约 15 个交易日，量级不可外推。
      </p>
    </div>
  );
}

export default function LimitDownBar() {
  const [snapshot, setSnapshot] = useState<LimitDownSnapshot | null>(null);
  const [snapError, setSnapError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [repair, setRepair] = useState<LimitDownRepairResult | null>(null);
  const [repairLoading, setRepairLoading] = useState(false);
  const [repairError, setRepairError] = useState<string | null>(null);
  const repairRequested = useRef(false);

  const loadSnapshot = useCallback(async () => {
    try {
      setSnapshot(await fetchLimitDownSnapshot());
      setSnapError(null);
    } catch (err) {
      setSnapError(err instanceof Error ? err.message : "获取跌停池失败");
    }
  }, []);

  const loadRepair = useCallback(async () => {
    setRepairLoading(true);
    try {
      setRepair(await fetchLimitDownRepair());
      setRepairError(null);
    } catch (err) {
      setRepairError(err instanceof Error ? err.message : "获取修复回测失败");
    } finally {
      setRepairLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadSnapshot();
    const timer = window.setInterval(() => void loadSnapshot(), POLL_INTERVAL);
    return () => window.clearInterval(timer);
  }, [loadSnapshot]);

  // 修复回测只依赖已收盘交易日，且成本高（逐只拉日 K）：展开时拉一次即可，不做轮询。
  useEffect(() => {
    if (!open || repairRequested.current) return;
    repairRequested.current = true;
    void loadRepair();
  }, [open, loadRepair]);

  const s = snapshot?.sentiment;
  const topSector = snapshot?.sectors[0];

  return (
    <div className="border-b border-slate-800/80 bg-slate-900/60">
      <div className="mx-auto max-w-6xl px-4 sm:px-6">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="flex w-full items-center gap-3 py-2 text-left"
        >
          <TrendingDown className="h-4 w-4 shrink-0 text-ink-muted" aria-hidden />
          <span className="flex flex-1 flex-wrap items-center gap-x-3 gap-y-1 text-xs">
            {snapError && !snapshot ? (
              <span className="text-amber-300">跌停池暂不可用：{snapError}</span>
            ) : !s ? (
              <span className="text-ink-faint">加载跌停池…</span>
            ) : s.limit_down_count === 0 ? (
              <span className="text-ink-faint">当前无跌停（未开盘或非交易日）</span>
            ) : (
              <>
                <span className="text-ink-muted">
                  跌停 <span className={`font-semibold ${downTone(400)}`}>{s.limit_down_count}</span> 家
                </span>
                <span className="text-ink-muted">
                  连跌 <span className={`font-semibold ${downTone(400)}`}>{s.chain_count}</span> 家
                </span>
                {s.max_down_days > 0 && (
                  <span className="text-ink-muted">
                    最长 <span className={`font-semibold ${downTone(400)}`}>{s.max_down_days}</span> 连跌
                  </span>
                )}
                {topSector && (
                  <span className="text-ink-muted">
                    最集中 <span className="font-semibold text-ink">{topSector.sector}</span>
                    <span className="text-ink-faint">（{topSector.count} 家）</span>
                  </span>
                )}
                <span className="text-ink-muted">
                  跌停/涨停{" "}
                  <span className="font-semibold text-ink">{fmtDownUpRatio(s.down_up_ratio)}</span>
                </span>
                <span
                  className="rounded bg-slate-800/70 px-1.5 py-0.5 text-ink-muted"
                  title="证据等级：收益口径可回测，结论为负期望（n=133、−4.47%/次），因此不构成买点"
                >
                  {snapshot.evidence.badge} · 非抄底信号
                </span>
              </>
            )}
          </span>
          <ChevronDown
            className={`h-4 w-4 shrink-0 text-ink-faint transition-transform ${open ? "rotate-180" : ""}`}
            aria-hidden
          />
        </button>

        <AnimatePresence initial={false}>
          {open && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="overflow-hidden"
            >
              <div className={`mb-3 ${SUB} space-y-4 p-4`}>
                {snapshot && s && (
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className={`text-sm ${sentimentTone(snapshot.sentiment_note.tone)}`}>
                      {snapshot.sentiment_note.text}
                    </p>
                    <div className="flex items-center gap-2 text-xs text-ink-faint">
                      <span>
                        {snapshot.trade_date} · {snapshot.session}
                      </span>
                      <button
                        type="button"
                        onClick={() => {
                          void loadSnapshot();
                          void loadRepair();
                        }}
                        className="inline-flex items-center gap-1 text-ink-muted hover:text-ink"
                        title="刷新跌停池与修复回测（读后端 60s 缓存，不会穿透到行情源）"
                      >
                        <RefreshCw className="h-3.5 w-3.5" aria-hidden />
                        刷新
                      </button>
                    </div>
                  </div>
                )}

                {snapshot && !snapshot.limit_up_ok && (
                  <p className="text-xs text-amber-300">
                    涨停池拉取失败，跌停/涨停家数比显示为「—」而不是 0 —— 数据缺失不等于抛压为零。
                  </p>
                )}

                <RepairSection repair={repair} loading={repairLoading} error={repairError} />

                {snapshot && <LadderSection ladder={snapshot.ladder} />}

                {snapshot && <SectorSection snapshot={snapshot} />}

                {snapshot && (
                  <>
                    <div className={DIVIDER} />
                    <div>
                      <h3 className={TEXT.label}>为什么这里不给抄底信号</h3>
                      <p className="mt-1 text-xs leading-relaxed text-ink-soft">
                        <span className="text-ink">{snapshot.evidence.label}</span>
                        {" · "}
                        {snapshot.evidence.summary}
                      </p>
                      <p className="mt-1 text-xs text-ink-faint">依据：{snapshot.evidence.provenance}</p>
                    </div>
                    <CaliberLine caliber={snapshot.caliber} />
                  </>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
