import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, RefreshCw } from "lucide-react";
import { fetchLimitUpRelay, fetchLimitUpSnapshot } from "../api/client";
import { useBus } from "../lib/bus";
import { breakRateTone, sentimentTone, upTone } from "../lib/tone";
import { DIVIDER, TEXT } from "../lib/ui";
import type { LimitUpRelayResult, LimitUpSnapshot } from "../types";
import { CaliberLine } from "./CaliberNote";
import { TapeShell } from "./market/TapeShell";
import { POLL_INTERVAL } from "./market/constants";
import {
  AdviceBadge,
  AdviceSection,
  LadderSection,
  RelaySection,
  RelayStocksSection,
  SectorSection,
} from "./market/LimitUpTeam";
import { PremiumSection } from "./market/LimitUpPremium";

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
 *
 * ## 结构
 * 本文件只保留「取数 + 展开状态 + 组合」：数据拉取、轮询、展开只拉一次的闩、
 * 以及「功能地图」落点事件都在这里；所有展示子件拆到了 `./market/`：
 *   - `LimitUpTeam.tsx`    连板梯队 / 涨停池列表 / 晋级率回溯 / 操作建议
 *   - `LimitUpPremium.tsx` 次日溢价读数（可成交档 / 不可成交档分开报）
 *   - `TapeShell.tsx`      折叠条 + 展开面板外壳（与跌停带共用）
 */

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

  // 功能地图里「涨停梯队 · 次日溢价读数」的落点：展开 + 滚回顶部。
  // 它不在任何 tab 里，任何页面点都应该有反应，所以走全局事件而不是 props。
  useBus("limitup", () => {
    setOpen(true);
    window.scrollTo({ top: 0, behavior: "smooth" });
  });

  const s = snapshot?.sentiment;
  const topSector = snapshot?.sectors[0];

  return (
    <TapeShell
      open={open}
      onToggle={() => setOpen((v) => !v)}
      icon={<Activity className="h-4 w-4 shrink-0 text-ink-muted" aria-hidden />}
      header={
        <>
          {snapError && !snapshot ? (
            <span className="text-amber-300">连板梯队暂不可用：{snapError}</span>
          ) : !s ? (
            <span className="text-ink-soft">加载连板梯队…</span>
          ) : s.limit_up_count === 0 ? (
            <span className="text-ink-soft">当前无涨停（未开盘或非交易日）</span>
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
                  <span className="text-ink-muted">（{topSector.count} 家）</span>
                </span>
              )}
              {snapshot.play_advice && <AdviceBadge advice={snapshot.play_advice} />}
              <span
                className="rounded-md bg-surface-inset/70 px-1.5 py-0.5 text-ink-muted"
                title="证据等级：只有「能否继续封板」这一个中间指标有正向线索，缺收益口径，因此不构成买点"
              >
                {snapshot.evidence.badge} · 非买点
              </span>
            </>
          )}
        </>
      }
    >
      {snapshot && s && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className={`text-body ${sentimentTone(snapshot.sentiment_note.tone)}`}>
            {snapshot.sentiment_note.text}
          </p>
          <div className="flex items-center gap-2 text-meta text-ink-muted">
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
        <p className="text-meta text-amber-300">
          炸板池拉取失败，本次炸板率只反映部分信息，请勿据此判断分歧大小。
        </p>
      )}

      {snapshot?.play_advice && <AdviceSection advice={snapshot.play_advice} />}

      {snapshot?.relay_stocks && (
        <RelayStocksSection stocks={snapshot.relay_stocks} summary={snapshot.relay_tier_summary} />
      )}

      {snapshot?.premium_summary && <PremiumSection summary={snapshot.premium_summary} />}

      {snapshot && <LadderSection ladder={snapshot.ladder} />}

      {snapshot && <SectorSection snapshot={snapshot} />}

      <RelaySection relay={relay} loading={relayLoading} error={relayError} />

      {snapshot && (
        <>
          <div className={DIVIDER} />
          <div>
            <h3 className={TEXT.label}>为什么这里不给买点</h3>
            <p className="mt-1 text-meta leading-relaxed text-ink-soft">
              <span className="text-ink">{snapshot.evidence.label}</span>
              {" · "}
              {snapshot.evidence.summary}
            </p>
            <p className="mt-1 text-meta text-ink-faint">依据：{snapshot.evidence.provenance}</p>
          </div>
          <CaliberLine caliber={snapshot.caliber} />
        </>
      )}
    </TapeShell>
  );
}
