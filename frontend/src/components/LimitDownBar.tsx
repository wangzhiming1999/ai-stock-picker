import { useCallback, useEffect, useRef, useState } from "react";
import { RefreshCw, TrendingDown } from "lucide-react";
import { fetchLimitDownRepair, fetchLimitDownSnapshot } from "../api/client";
import { downTone, sentimentTone } from "../lib/tone";
import { DIVIDER, TEXT } from "../lib/ui";
import type { LimitDownRepairResult, LimitDownSnapshot } from "../types";
import { CaliberLine } from "./CaliberNote";
import { TapeShell } from "./market/TapeShell";
import { POLL_INTERVAL } from "./market/constants";
import { LadderSection, SectorSection } from "./market/LimitDownPool";
import { RepairSection } from "./market/LimitDownRepair";
import { fmtDownUpRatio } from "./limitDownLogic";

/**
 * 跌停池常驻条（全局可见，不占一级导航）。
 *
 * 与 `LimitUpBar` 对称：那边读「做多的温度」，这边读「抛压的温度」。
 * 同样刻意不进 NAV —— 它是「读市场」而不是「做一件事」。
 *
 * ## 它不是什么（这一节比上面重要）
 * **这不是抄底信号。** 这个策略的收益口径**可回测，而且结论是负的**：
 * 13 个交易日、133 个样本上，D 日跌停价买入 → D+1 集合竞价卖出的期望是
 * **−4.47%/次、胜率 4.5%**，打平需要 80.6% 的胜率。所以后端证据等级是
 * `unsupported` —— 不是「还没跑」，而是「有明确结论且为负」，`actionable` 恒为 false。
 * 本组件据此：
 *
 *   1. 不出现任何动作话术（抄底 / 买入 / 低吸 / 建议）；
 *   2. 位置标签（首跌/换手/封死/连跌/深跌）只给中性或琥珀色，**不占红绿**；
 *   3. 所有收益读数都带样本量与口径（`CaliberLine`），并把**打平胜率与实际胜率的
 *      缺口摆在最显眼处** —— 那是这个方向到底成不成立的关键数字。
 *
 * ⚠️ 修复回测只在展开时拉一次：那条链路要为每只跌停股拉一次日 K，成本远高于快照，
 * 因此**不做轮询**（守卫用 ref，避免重复展开重复请求）。
 *
 * ## 结构
 * 本文件只保留「取数 + 展开状态 + 组合」；展示子件拆到了 `./market/`：
 *   - `LimitDownPool.tsx`   跌停池列表 / 连续跌停梯队 / 板块聚集度
 *   - `LimitDownRepair.tsx` 修复回测 / 次日竞价卖出读数
 *   - `TapeShell.tsx`       折叠条 + 展开面板外壳（与涨停带共用）
 */

export default function LimitDownBar({
  defaultOpen = false,
  embedded = false,
}: {
  defaultOpen?: boolean;
  embedded?: boolean;
}) {
  const [snapshot, setSnapshot] = useState<LimitDownSnapshot | null>(null);
  const [snapError, setSnapError] = useState<string | null>(null);
  const [open, setOpen] = useState(defaultOpen);
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
    <TapeShell
      open={open}
      onToggle={() => setOpen((v) => !v)}
      embedded={embedded}
      icon={<TrendingDown className="h-4 w-4 shrink-0 text-ink-muted" aria-hidden />}
      header={
        <>
          {snapError && !snapshot ? (
            <span className="text-amber-300">跌停池暂不可用：{snapError}</span>
          ) : !s ? (
            <span className="text-ink-soft">加载跌停池…</span>
          ) : s.limit_down_count === 0 ? (
            <span className="text-ink-soft">当前无跌停（未开盘或非交易日）</span>
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
                  <span className="text-ink-muted">（{topSector.count} 家）</span>
                </span>
              )}
              <span className="text-ink-muted">
                跌停/涨停{" "}
                <span className="font-semibold text-ink">{fmtDownUpRatio(s.down_up_ratio)}</span>
              </span>
              <span
                className="rounded-md bg-surface-inset/70 px-1.5 py-0.5 text-ink-muted"
                title="证据等级：收益口径可回测，结论为负期望（n=133、−4.47%/次），因此不构成买点"
              >
                {snapshot.evidence.badge} · 非抄底信号
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
        <p className="text-meta text-amber-300">
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
