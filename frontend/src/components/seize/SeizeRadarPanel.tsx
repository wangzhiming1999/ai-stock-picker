import { useCallback, useEffect, useRef, useState } from "react";
import { Flame, RefreshCw } from "lucide-react";
import { fetchSeizeRadar } from "../../api/client";
import { CaliberLine } from "../CaliberNote";
import { pnlTone } from "../../lib/tone";
import { TEXT, STACK, CELL } from "../../lib/ui";
import { signedPct } from "../market/format";
import Table, { Th } from "../ui/Table";
import type { SeizeRadar, SeizeBroken, SeizeReseal, SeizeSealed } from "../../types";

/**
 * 封板雷达（抢封板观察层）。
 *
 * ## 它是什么
 * 把「封板瞬间」拆成两个真实可下手窗口，全部从现有安全数据源（东财 push2ex 涨停池 +
 * 炸板池，单请求、零额外风控风险）派生：
 *   · 刚封板（just_sealed）—— 首封时间距今 ≤300s，最后封单窗口；
 *   · 回封候选（reseal）—— 炸板池里仍贴着涨停价的票，拉升回封过程中买入；
 *   · 炸板预警（broken_alert）—— 已明显掉离涨停、振幅大，风险提示。
 *
 * ## 它不是什么（与涨停梯队同一套纪律）
 * 卖出口径 = limitup_premium（涨停价买入 → 次日集合竞价卖出），但本面板**不构成买卖指令**：
 *   · 读数不含动作词；状态色用主色/琥珀，不占红绿（红绿是方向语义，会被读成"该动手了"）；
 *   · 回封候选的收益是**条件性**读数（条件于回封成功），明确标注「回封失败则无此收益」；
 *   · 所有百分比口径说明挂在 CaliberLine，不与"胜率"并列。
 */

/** 后端字段渲染兜底：非有限数一律 "—"（见项目兜底纪律）。 */
function fmt(v: number | null | undefined, digits = 2): string {
  return v != null && Number.isFinite(v) ? v.toFixed(digits) : "—";
}

function PremiumCell({ premium }: { premium?: { expect_pct: number | null; tradable?: boolean } }) {
  if (!premium) return <span className="text-ink-muted">—</span>;
  const ep = premium.expect_pct;
  if (ep == null || !Number.isFinite(ep)) return <span className="text-ink-muted">—</span>;
  return (
    <span
      className={premium.tradable ? "text-ink" : "text-amber-300"}
      title={premium.tradable ? "可成交档" : "缩量一字/秒板，多数挂不上单"}
    >
      {signedPct(ep)}
    </span>
  );
}

function SealedTable({ rows }: { rows: SeizeSealed[] }) {
  if (rows.length === 0)
    return <p className="text-meta text-ink-faint">暂无刚封板标的（首封距今 ≤5 分钟）。</p>;
  return (
    <Table
      label="刚封板"
      maxHeight="md"
      head={
        <tr>
          <Th>代码 / 名称</Th>
          <Th align="right">现价</Th>
          <Th align="right">涨跌幅</Th>
          <Th align="right">首封</Th>
          <Th align="right">封单(亿)</Th>
          <Th align="right">封单/流通</Th>
          <Th align="right">次日竞价卖出</Th>
          <Th align="right">次日涨停价</Th>
        </tr>
      }
    >
      {rows.map((r) => (
        <tr key={r.code} className="border-t border-surface-line/60">
          <td className={CELL}>
            <div className="font-medium text-ink">{r.name}</div>
            <div className="text-meta text-ink-muted">{r.code}</div>
          </td>
          <td className={`${CELL} text-right tabular-nums text-ink`}>{fmt(r.price)}</td>
          <td className={`${CELL} text-right tabular-nums ${pnlTone(r.change_pct)}`}>
            {signedPct(r.change_pct)}
          </td>
          <td className={`${CELL} text-right tabular-nums text-ink-soft`}>
            {r.seal_time || "—"}
            <span className="block text-meta text-ink-muted">{Math.round(r.seconds_since_seal)}s 前</span>
          </td>
          <td className={`${CELL} text-right tabular-nums text-ink-soft`}>{fmt(r.seal_fund_yi)}</td>
          <td className={`${CELL} text-right tabular-nums text-ink-soft`}>{fmt(r.seal_ratio)}%</td>
          <td className={`${CELL} text-right tabular-nums`}>
            <PremiumCell premium={r.premium} />
          </td>
          <td className={`${CELL} text-right tabular-nums text-ink-soft`}>{fmt(r.next_limit_price)}</td>
        </tr>
      ))}
    </Table>
  );
}

function ResealTable({ rows }: { rows: SeizeReseal[] }) {
  if (rows.length === 0)
    return <p className="text-meta text-ink-faint">暂无回封候选（炸板池里贴着涨停价的票）。</p>;
  return (
    <Table
      label="回封候选"
      maxHeight="md"
      head={
        <tr>
          <Th>代码 / 名称</Th>
          <Th align="right">现价</Th>
          <Th align="right">涨跌幅</Th>
          <Th align="right">距涨停%</Th>
          <Th align="right">振幅</Th>
          <Th>状态</Th>
          <Th align="right">条件收益*</Th>
          <Th>板块</Th>
        </tr>
      }
    >
      {rows.map((r) => (
        <tr key={r.code} className="border-t border-surface-line/60">
          <td className={CELL}>
            <div className="font-medium text-ink">{r.name}</div>
            <div className="text-meta text-ink-muted">{r.code}</div>
          </td>
          <td className={`${CELL} text-right tabular-nums text-ink`}>{fmt(r.price)}</td>
          <td className={`${CELL} text-right tabular-nums ${pnlTone(r.change_pct)}`}>
            {signedPct(r.change_pct)}
          </td>
          <td className={`${CELL} text-right tabular-nums text-brand-light`}>{fmt(r.dist_to_limit_pct)}%</td>
          <td className={`${CELL} text-right tabular-nums text-ink-soft`}>{fmt(r.amplitude)}%</td>
          <td className={CELL}>
            {r.recovering ? (
              <span className="rounded-md bg-brand/15 px-1.5 py-0.5 text-meta text-brand-light">回升中</span>
            ) : (
              <span className="rounded-md bg-surface-inset/60 px-1.5 py-0.5 text-meta text-ink-muted">贴板</span>
            )}
          </td>
          <td
            className={`${CELL} text-right tabular-nums text-ink-soft`}
            title={r.premium_if_sealed.note}
          >
            {signedPct(r.premium_if_sealed.expect_pct)}
          </td>
          <td className={`${CELL} text-meta text-ink-soft`}>{r.sector}</td>
        </tr>
      ))}
    </Table>
  );
}

function BrokenTable({ rows }: { rows: SeizeBroken[] }) {
  if (rows.length === 0) return <p className="text-meta text-ink-faint">暂无炸板预警。</p>;
  return (
    <Table
      label="炸板预警"
      maxHeight="sm"
      head={
        <tr>
          <Th>代码 / 名称</Th>
          <Th align="right">现价</Th>
          <Th align="right">距涨停%</Th>
          <Th align="right">振幅</Th>
          <Th align="right">开板</Th>
          <Th>板块</Th>
        </tr>
      }
    >
      {rows.map((r) => (
        <tr key={r.code} className="border-t border-surface-line/60">
          <td className={CELL}>
            <div className="font-medium text-ink">{r.name}</div>
            <div className="text-meta text-ink-muted">{r.code}</div>
          </td>
          <td className={`${CELL} text-right tabular-nums text-ink`}>{fmt(r.price)}</td>
          <td className={`${CELL} text-right tabular-nums text-amber-300`}>{fmt(r.dist_to_limit_pct)}%</td>
          <td className={`${CELL} text-right tabular-nums text-ink-soft`}>{fmt(r.amplitude)}%</td>
          <td className={`${CELL} text-right tabular-nums text-ink-soft`}>{r.break_count}</td>
          <td className={`${CELL} text-meta text-ink-soft`}>{r.sector}</td>
        </tr>
      ))}
    </Table>
  );
}

export default function SeizeRadarPanel() {
  const [radar, setRadar] = useState<SeizeRadar | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<number | null>(null);
  const pollRef = useRef(15_000);

  const load = useCallback(async (force = false) => {
    try {
      const data = await fetchSeizeRadar(force);
      setRadar(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "获取封板雷达失败");
    }
  }, []);

  useEffect(() => {
    let stopped = false;
    const tick = () => {
      if (stopped) return;
      timerRef.current = window.setTimeout(async () => {
        await load();
        tick();
      }, pollRef.current);
    };
    void load().then(() => {
      pollRef.current = 15_000;
      tick();
    });
    return () => {
      stopped = true;
      if (timerRef.current) window.clearTimeout(timerRef.current);
    };
  }, [load]);

  const c = radar?.counts;
  const premium = radar?.premium_summary;

  return (
    <div className={STACK}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2 text-meta text-ink-muted">
          <span className="inline-flex items-center gap-1.5 rounded-md bg-brand/15 px-2 py-1 text-brand-light">
            <Flame className="h-3.5 w-3.5" aria-hidden /> 刚封板 {c?.just_sealed ?? 0}
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-md bg-surface-inset/70 px-2 py-1">
            回封候选 {c?.reseal ?? 0}
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-md bg-amber-500/10 px-2 py-1 text-amber-300">
            炸板预警 {c?.broken_alert ?? 0}
          </span>
          {radar && (
            <span className="text-ink-faint">
              {radar.trade_date} · {radar.session}
              {radar.market_open ? " · 盘中" : " · 非盘中"}
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={() => void load(true)}
          className="inline-flex items-center gap-1 text-ink-muted hover:text-ink"
          title="刷新封板雷达（读后端 15s 缓存，force 才穿透行情源）"
        >
          <RefreshCw className="h-3.5 w-3.5" aria-hidden /> 刷新
        </button>
      </div>

      {error && !radar && <p className="text-meta text-amber-300">封板雷达暂不可用：{error}</p>}
      {!radar && !error && <p className="text-meta text-ink-soft">加载封板雷达…</p>}

      {radar && (
        <>
          {/* 策略与卖出口径说明：封板瞬间观察，次日竞价卖出。非买入指令。 */}
          <div className="rounded-xl border border-surface-line bg-surface-raised px-3 py-3">
            <div className="flex items-center gap-2">
              <span className="text-meta font-semibold text-brand-light">封板瞬间观察 · 次日竞价卖出</span>
              {radar.evidence?.badge && (
                <span className="rounded-md bg-surface-line/60 px-1.5 py-0.5 text-meta text-ink-muted">
                  {radar.evidence.badge} · 非买入信号
                </span>
              )}
            </div>
            <p className="mt-1.5 text-meta leading-relaxed text-ink-soft">
              拉升封板 → 持有过夜 → 次日集合竞价卖出。卖出口径复用{" "}
              <span className="text-ink">limitup_premium</span>
              （涨停价买入 → 次日竞价卖出，历史期望约 +2%、胜率约 62%）。
              <span className="text-ink-muted">
                本面板只做观察与收益读数，不构成买卖指令；封板瞬间能否抢到取决于实时盘口。
              </span>
            </p>
            {premium?.headline && (
              <p className="mt-1.5 rounded-lg bg-surface-inset/50 px-3 py-2 text-meta leading-relaxed text-ink-soft">
                {premium.headline}
              </p>
            )}
          </div>

          <div>
            <h3 className={TEXT.label}>刚封板（最后封单窗口）</h3>
            <SealedTable rows={radar.just_sealed} />
          </div>

          <div>
            <h3 className={TEXT.label}>回封候选（炸板池贴涨停价）</h3>
            {!radar.zb_ok && (
              <p className="text-meta text-amber-300">炸板池拉取失败，回封候选与炸板预警仅反映部分信息。</p>
            )}
            <ResealTable rows={radar.reseal} />
            <p className="mt-1 text-meta text-ink-faint">
              * 条件收益：若回封成功，按次日竞价卖出同口径读数；回封失败则无此收益，属条件性读数。
            </p>
          </div>

          <div>
            <h3 className={TEXT.label}>炸板预警（已掉离涨停）</h3>
            <BrokenTable rows={radar.broken_alert} />
          </div>

          <CaliberLine caliber={radar.caliber} />
          {radar.note && <p className="text-meta text-ink-faint">{radar.note}</p>}
        </>
      )}
    </div>
  );
}
