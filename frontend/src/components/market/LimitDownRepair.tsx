import { SUB_QUIET, TEXT } from "../../lib/ui";
import { pnlTone } from "../../lib/tone";
import type { LimitDownBucket, LimitDownRepairResult } from "../../types";
import { extremeBuckets, tailSummary, winRateShortfall } from "../limitDownLogic";

/**
 * 跌停带「修复回测 / 次日竞价卖出读数」区块。
 *
 * 这是跌停带的核心，也是唯一能回答「抄底到底行不行」的地方。
 * 排版顺序刻意是「结论 → 依据 → 边界」：先给期望与胜率缺口，再给分桶，
 * 最后给尾部风险和窗口说明。反过来（先铺一堆分桶数字）读者会先形成「有规律可找」
 * 的印象，再去读那个负号就晚了。
 *
 * 纪律：本区块是**负期望**的观测，不进导航、不出现动作词；收益读数走绿（跌=绿），
 * 质量/证据类指标（打平胜率、缺口）走琥珀/中性、不占红绿。
 */

function StatTile({ value, label, tone }: { value: string | number; label: string; tone?: string }) {
  return (
    <div className={SUB_QUIET + " px-3 py-2"}>
      <div className={`text-num font-bold ${tone ?? "text-ink"}`}>{value}</div>
      <div className="text-meta text-ink-muted">{label}</div>
    </div>
  );
}

/** 一个收益切片：期望收益 / 胜率 / 打平线。负期望用绿（跌的语义）。 */
function BucketRow({ b }: { b: LimitDownBucket }) {
  if (!b.n) return null;
  const expect = b.expect_open ?? 0;
  return (
    <div className="flex items-center justify-between gap-2 text-meta">
      <span className="w-24 shrink-0 truncate text-ink-muted" title={b.label}>
        {b.label}
      </span>
      <span className="text-ink-soft">
        n={b.n} · 胜率 <span className="text-ink">{b.win_rate_open ?? "—"}%</span>
        <span className="text-ink-soft"> · 打平需 {b.breakeven_win_rate ?? "—"}%</span>
      </span>
      <span className={`w-16 shrink-0 text-right font-semibold ${pnlTone(b.expect_open)}`}>
        {expect > 0 ? "+" : ""}
        {b.expect_open ?? "—"}%
      </span>
    </div>
  );
}

/**
 * 修复率回溯区块 —— 本组件的核心，也是唯一能回答「抄底到底行不行」的地方。
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
    return <p className="text-meta text-ink-soft">正在回溯修复收益…（需为每只跌停股拉取日 K，约数秒）</p>;
  }
  if (error && !repair) return <p className="text-meta text-amber-300">{error}</p>;
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
      <p className="mt-1.5 rounded-lg bg-surface-inset/50 px-3 py-2 text-meta leading-relaxed text-ink-soft">
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

      <div className="mt-3 space-y-1 text-meta">
        <div className="flex items-center justify-between gap-2">
          <span className="text-ink-muted">对照组：持有到 D+1 收盘才卖</span>
          <span className="text-ink-soft">
            期望{" "}
            <span className={`font-semibold ${pnlTone(o.expect_close)}`}>{o.expect_close ?? "—"}%</span>
            <span className="text-ink-soft"> · 胜率 {o.win_rate_close ?? "—"}%</span>
          </span>
        </div>
        <div className="flex items-center justify-between gap-2">
          <span className="text-ink-muted">次日盘中最高价（反抽弹性）</span>
          <span className="text-ink-soft">
            平均 <span className={`font-semibold ${pnlTone(o.avg_high)}`}>{o.avg_high ?? "—"}%</span>
            <span className="text-ink-soft"> · 盘中曾转正 {o.high_positive_rate ?? "—"}%</span>
          </span>
        </div>
      </div>

      <h4 className="mt-3 text-meta font-semibold text-ink-muted">按 D 日封板状态</h4>
      <div className="mt-1 space-y-1">
        {repair.by_sealed.map((b) => (
          <BucketRow key={b.key} b={b} />
        ))}
      </div>

      <h4 className="mt-3 text-meta font-semibold text-ink-muted">按同一板块当天跌停家数</h4>
      <div className="mt-1 space-y-1">
        {repair.by_cluster.map((b) => (
          <BucketRow key={b.key} b={b} />
        ))}
      </div>

      <h4 className="mt-3 text-meta font-semibold text-ink-muted">按连续跌停天数</h4>
      <div className="mt-1 space-y-1">
        {repair.by_down_days.map((b) => (
          <BucketRow key={b.key} b={b} />
        ))}
      </div>

      {extremes.best && (
        <p className="mt-2 text-meta leading-relaxed text-ink-faint">
          n≥5 的切片里表现最好的一档是「{extremes.best.label}」（期望{" "}
          {extremes.best.expect_open ?? "—"}%、n={extremes.best.n}），最差是「
          {extremes.worst?.label ?? "—"}」（{extremes.worst?.expect_open ?? "—"}%）——
          <span className="text-ink-soft">两档都是负的</span>，所以这不是「换一类就好了」的问题。
        </p>
      )}

      {tail && (
        <p className="mt-2 rounded-lg bg-amber-500/10 px-3 py-2 text-meta leading-relaxed text-amber-300">
          {tail} —— T+1 之下这一档没有任何止损手段，是这条路径最需要防范的地方。
        </p>
      )}

      <p className="mt-2 text-meta leading-relaxed text-ink-faint">
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

export { BucketRow, RepairSection, StatTile };
