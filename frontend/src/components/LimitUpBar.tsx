import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Activity, ChevronDown, RefreshCw } from "lucide-react";
import { fetchLimitUpRelay, fetchLimitUpSnapshot } from "../api/client";
import { breakRateTone, sentimentTone, upTone } from "../lib/tone";
import { DIVIDER, SUB, SUB_QUIET, TEXT } from "../lib/ui";
import type { LimitUpLadderGroup, LimitUpRelayResult, LimitUpSnapshot, LimitUpStock } from "../types";
import { CaliberLine } from "./CaliberNote";
import { ladderGaps } from "./limitUpLogic";

/**
 * 连板梯队常驻条（全局可见，不占一级导航）。
 *
 * ## 它是什么
 * 涨停家数 / 连板家数 / 炸板率 / 最高板 / 主线板块 —— 一屏看出当日情绪温度；
 * 展开后是连板梯队、板块聚集度，以及 N 连板 → 次日晋级率的历史回溯。
 *
 * ## 它不是什么（这一节比上面重要）
 * **这不是买点列表。** 连板接力目前只有「能否继续封板」这个**中间指标**上的正向线索，
 * 缺少收益口径（涨停池拿不到次日成交价，连板股常以一字板开盘，晋级了也买不到），
 * 证据等级停在后端的「初步」，`evidence.actionable` 恒为 false。因此本组件：
 *
 *   1. 不出现任何动作话术（买点 / 加仓 / 建议）；
 *   2. 位置标签（启动/加速/中继/高位/分歧）只给中性或琥珀色，**不占红绿**
 *      —— 红绿是方向语义，用在这里会被读成「该动手了」；
 *   3. 所有百分比都自带样本量与口径（`CaliberLine`），不与「胜率」并列。
 *
 * ## 数据源
 * 东财 `push2ex` 涨停板池，与 `spot_service` 的全市场快照（`push2`）是不同域名/端点，
 * 所以**不接** `spotGuard` 那套冷却闸门，也不该被行情源风控影响。
 */

const POLL_INTERVAL = 60_000; // 与后端 60s 内存缓存同拍，不必更密

/**
 * 位置标签配色。
 *
 * 全部走中性 / 琥珀：位置越靠后风险越高，但它既不预示上涨（不用红）
 * 也不预示下跌（不用绿）—— 高位之后可能继续加速，也可能直接退潮。
 */
const POSITION_CHIP: Record<string, string> = {
  启动: "bg-slate-800/70 text-ink-soft",
  加速: "bg-slate-700/70 text-ink-soft",
  中继: "bg-slate-700/70 text-ink",
  高位: "bg-amber-500/10 text-amber-300",
  分歧: "bg-amber-500/10 text-amber-300",
};

function positionChip(tag: string): string {
  return POSITION_CHIP[tag] ?? "bg-slate-800/70 text-ink-muted";
}

function StockChip({ t }: { t: LimitUpStock }) {
  // 位置标注缺失时降级成「未知」而不是渲染空白：滚动发布期间前端可能连到旧后端，
  // 一个字段缺失不该让整段梯队失效（与 TacticHit 对 evidence 的兜底同思路）。
  const position = t.position ?? { tag: "未知", reason: "位置标注缺失" };
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-lg bg-slate-800/60 px-2 py-1 text-xs"
      title={`${position.reason}｜封单 ${t.seal_fund_yi} 亿｜流通 ${t.float_mv_yi} 亿｜封单比 ${t.seal_ratio}%`}
    >
      <span className="text-ink">{t.name}</span>
      <span className="text-ink-faint">{t.code}</span>
      <span className="text-ink-muted">首封 {t.seal_time || "--"}</span>
      {t.break_count > 0 && <span className="text-amber-300">开板 {t.break_count} 次</span>}
      <span className={`rounded px-1 text-xs ${positionChip(position.tag)}`}>{position.tag}</span>
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
          <span className="text-xs text-amber-300">
            梯队断层：{gaps.map((g) => `${g}板`).join(" / ")} 空缺
          </span>
        )}
      </div>
      <div className="mt-2 space-y-1.5">
        {ladder.map((g) => (
          <div key={g.key} className="flex items-center gap-2">
            <span className="w-12 shrink-0 text-xs text-ink-muted">{g.label}</span>
            <span className="w-10 shrink-0 text-right text-xs font-semibold text-ink">{g.count}</span>
            <span className="h-2 shrink-0 rounded-full bg-brand/70" style={{ width: `${Math.max((g.count / max) * 100, 3)}%` }} />
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

function SectorSection({ snapshot }: { snapshot: LimitUpSnapshot }) {
  if (snapshot.sectors.length === 0) return null;
  return (
    <div>
      <h3 className={TEXT.label}>板块聚集度（当日涨停家数排序）</h3>
      <div className="mt-2 space-y-1">
        {snapshot.sectors.slice(0, 6).map((s) => (
          <div key={s.sector} className="flex items-center justify-between gap-2 text-xs">
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
      <p className="mt-2 text-xs leading-relaxed text-ink-faint">
        按家数排序而非封单金额 —— 家数更能反映资金是否在这个板块里抱团。
        但下面对照表显示：**聚集度越高，首板晋级率反而越低**，所以它只能当情绪读，不能当买点。
      </p>
    </div>
  );
}

function RelaySection({ relay, loading, error }: { relay: LimitUpRelayResult | null; loading: boolean; error: string | null }) {
  if (loading && !relay) return <p className="text-xs text-ink-faint">正在回溯晋级率…</p>;
  if (error && !relay) return <p className="text-xs text-amber-300">{error}</p>;
  if (!relay) return null;

  const window = relay.data_window.length === 2 ? `${relay.data_window[0]} ~ ${relay.data_window[1]}` : "无";

  return (
    <div>
      <h3 className={TEXT.label}>连板晋级率回溯（N 板 → 次日 N+1 板）</h3>
      <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <div className={SUB_QUIET + " px-3 py-2"}>
          <div className="text-lg font-bold text-ink">{relay.overall_rate}%</div>
          <div className="text-xs text-ink-faint">整体晋级率</div>
        </div>
        <div className={SUB_QUIET + " px-3 py-2"}>
          <div className="text-lg font-bold text-ink">{relay.total_samples}</div>
          <div className="text-xs text-ink-faint">样本数 n</div>
        </div>
        <div className={SUB_QUIET + " px-3 py-2"}>
          <div className="text-lg font-bold text-ink">{relay.sessions}</div>
          <div className="text-xs text-ink-faint">交易日对</div>
        </div>
        <div className={SUB_QUIET + " px-3 py-2"}>
          <div className="text-lg font-bold text-ink-muted">{relay.baseline_rate}%</div>
          <div className="text-xs text-ink-faint">随机水平参照</div>
        </div>
      </div>

      <div className="mt-3 space-y-1">
        {relay.by_boards.map((b) => (
          <div key={b.key} className="flex items-center justify-between gap-2 text-xs">
            <span className="w-14 shrink-0 text-ink-muted">{b.label}</span>
            <span className="text-ink-soft">
              晋级 <span className="text-ink">{b.promoted}</span> / {b.total}（n={b.total}）
            </span>
            <span className="w-14 shrink-0 text-right font-semibold text-ink">{b.rate}%</span>
          </div>
        ))}
      </div>

      <h4 className="mt-3 text-xs font-semibold text-ink-muted">分层：控制连板高度后，再看板块聚集度</h4>
      <div className="mt-1 space-y-1">
        {relay.by_boards_cluster.map((row) => (
          <div key={row.boards} className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
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

      <p className="mt-2 text-xs leading-relaxed text-ink-faint">
        数据窗口 {window}（{relay.effective_days} 个交易日）。
        {relay.empty_dates.length > 0 && ` 更早的 ${relay.empty_dates.length} 天接口返回空池，已识别为「无数据」并排除出样本。`}
        {relay.skipped_dates.length > 0 && ` 另有 ${relay.skipped_dates.length} 天拉取失败被跳过。`}
      </p>
    </div>
  );
}

export default function LimitUpBar() {
  const [snapshot, setSnapshot] = useState<LimitUpSnapshot | null>(null);
  const [snapError, setSnapError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [relay, setRelay] = useState<LimitUpRelayResult | null>(null);
  const [relayLoading, setRelayLoading] = useState(false);
  const [relayError, setRelayError] = useState<string | null>(null);
  const relayRequested = useRef(false);

  const loadSnapshot = useCallback(async () => {
    try {
      setSnapshot(await fetchLimitUpSnapshot());
      setSnapError(null);
    } catch (err) {
      setSnapError(err instanceof Error ? err.message : "获取连板梯队失败");
    }
  }, []);

  const loadRelay = useCallback(async () => {
    setRelayLoading(true);
    try {
      setRelay(await fetchLimitUpRelay());
      setRelayError(null);
    } catch (err) {
      setRelayError(err instanceof Error ? err.message : "获取连板晋级率失败");
    } finally {
      setRelayLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadSnapshot();
    const timer = window.setInterval(() => void loadSnapshot(), POLL_INTERVAL);
    return () => window.clearInterval(timer);
  }, [loadSnapshot]);

  // 晋级率只依赖已收盘交易日，展开时拉一次即可，不做轮询。
  useEffect(() => {
    if (!open || relayRequested.current) return;
    relayRequested.current = true;
    void loadRelay();
  }, [open, loadRelay]);

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
          <Activity className="h-4 w-4 shrink-0 text-ink-muted" aria-hidden />
          <span className="flex flex-1 flex-wrap items-center gap-x-3 gap-y-1 text-xs">
            {snapError && !snapshot ? (
              <span className="text-amber-300">连板梯队暂不可用：{snapError}</span>
            ) : !s ? (
              <span className="text-ink-faint">加载连板梯队…</span>
            ) : s.limit_up_count === 0 ? (
              <span className="text-ink-faint">当前无涨停（未开盘或非交易日）</span>
            ) : (
              <>
                <span className="text-ink-muted">
                  涨停 <span className={`font-semibold ${upTone(400)}`}>{s.limit_up_count}</span> 家
                </span>
                <span className="text-ink-muted">
                  连板 <span className={`font-semibold ${upTone(400)}`}>{s.relay_count}</span> 家
                </span>
                <span className="text-ink-muted">
                  炸板率{" "}
                  <span className={`font-semibold ${breakRateTone(s.break_rate)}`}>{s.break_rate}%</span>
                </span>
                <span className="text-ink-muted">
                  最高 <span className={`font-semibold ${upTone(400)}`}>{s.max_boards}</span> 板
                </span>
                {topSector && (
                  <span className="text-ink-muted">
                    主线 <span className="font-semibold text-ink">{topSector.sector}</span>
                    <span className="text-ink-faint">（{topSector.count} 家）</span>
                  </span>
                )}
                <span
                  className="rounded bg-slate-800/70 px-1.5 py-0.5 text-ink-muted"
                  title="证据等级：只有「能否继续封板」这一个中间指标有正向线索，缺收益口径，因此不构成买点"
                >
                  {snapshot.evidence.badge} · 非买点
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
                          void loadRelay();
                        }}
                        className="inline-flex items-center gap-1 text-ink-muted hover:text-ink"
                        title="刷新连板梯队与晋级率（读后端 60s 缓存，不会穿透到行情源）"
                      >
                        <RefreshCw className="h-3.5 w-3.5" aria-hidden />
                        刷新
                      </button>
                    </div>
                  </div>
                )}

                {snapshot && !snapshot.broken_ok && (
                  <p className="text-xs text-amber-300">
                    炸板池拉取失败，本次炸板率只反映部分信息，请勿据此判断分歧大小。
                  </p>
                )}

                {snapshot && <LadderSection ladder={snapshot.ladder} />}

                {snapshot && <SectorSection snapshot={snapshot} />}

                <RelaySection relay={relay} loading={relayLoading} error={relayError} />

                {snapshot && (
                  <>
                    <div className={DIVIDER} />
                    <div>
                      <h3 className={TEXT.label}>为什么这里不给买点</h3>
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
