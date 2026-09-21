import { useCallback, useEffect, useState } from "react";
import { CalendarDays, Eye, ShieldCheck, Unlock } from "lucide-react";
import { fetchDailyRecommend } from "../api/client";
import { fmtDate, fmtDayLabel, isTodayCN } from "../lib/dates";
import { confirmForceRefresh, useSpotCooldown } from "../lib/spotGuard";
import CollapsiblePanel from "./ui/CollapsiblePanel";
import WatchStar from "./WatchStar";
import type { DailyRecommendResult } from "../types";
import { downTone, pnlTone, upTone } from "../lib/tone";
import { confidenceHint, confidenceLabel } from "../lib/confidence";
import Button from "./ui/Button";

/** 拦截原因 -> 白话。逐条映射，不能整串替换（否则多条原因会串味）。 */
const BLOCKER_LABELS: Record<string, string> = {
  风险收益比不足: "上涨空间暂时不够覆盖下跌风险",
  策略强度不足: "上涨信号还不够强",
  动量不足: "上涨力度还需要确认",
  趋势未确认: "还没形成稳定上涨趋势",
  等待趋势确认: "还没形成稳定上涨趋势",
  等待动量确认: "上涨力度还需要确认",
  涨幅过高: "短期涨幅偏高，别追",
  流动性异常: "成交不够活跃，进出不便",
};

/** 把 status / blockers 转成白话；后端新增原因时原样透出，不吞信息。 */
function plainStatus(status: string, blockers?: string[]): string {
  const raw = blockers?.length ? blockers.join("、") : status;
  return raw
    .split(/[、,，]/)
    .map((t) => t.trim())
    .filter(Boolean)
    .map((t) => BLOCKER_LABELS[t] ?? t)
    .join("、");
}

interface Props {
  onPick: (codes: string[]) => void;
  /** 折叠态：被外层 CollapsiblePanel 包裹时，不再渲染自身面板头，避免双层标题 */
  collapsed?: boolean;
}

export default function DailyRecommendCard({ onPick, collapsed = false }: Props) {
  const { seconds: cooldown } = useSpotCooldown();
  const [data, setData] = useState<DailyRecommendResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());

  const load = useCallback(async (force = false) => {
    setLoading(true);
    setErr("");
    setPicked(new Set());
    try {
      setData(await fetchDailyRecommend(force));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const toggle = (code: string) => {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  const pickAll = () => {
    if (data?.recommendations?.length) {
      onPick(data.recommendations.map((r) => r.code));
    }
  };

  const actions = data?.recommendations?.length ? (
    <Button variant="primary" size="sm"
      onClick={pickAll}
      >
      全部去分析 →
    </Button>
  ) : null;

  const forceRefresh = async () => {
    if (!(await confirmForceRefresh())) return;
    await load(true);
  };

  const refreshBtn = (
    <Button variant="outlineQuiet" size="sm"
      onClick={() => void forceRefresh()}
      disabled={loading || cooldown > 0}
      >
      {loading ? "生成中..." : cooldown > 0 ? `冷却 ${cooldown}s` : "强制刷新"}
    </Button>
  );

  const body = (
    <>
      {err && <div className="rounded-lg border border-state-danger-line bg-state-danger-surface px-3 py-2 text-body text-state-danger-soft">{err}</div>}

      {data?.date && (
        <div className="mb-3 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-xl border border-surface-line bg-surface-inset/40 px-3 py-2 text-meta text-ink-muted">
          <CalendarDays className="h-3.5 w-3.5 shrink-0 text-ink-faint" aria-hidden />
          <span>
            数据截至 <span className="font-medium text-ink">{fmtDayLabel(data.date)}</span> 收盘
            {data.target_date && (
              <>
                <span className="mx-1.5 text-ink-faint">→</span>
                目标关注 <span className="font-medium text-amber-300">{fmtDayLabel(data.target_date)}</span>
              </>
            )}
          </span>
          {isTodayCN(data.date) ? (
            <span className="rounded-md bg-brand/10 px-1.5 py-0.5 text-meta text-brand-light">当日收盘</span>
          ) : (
            <span className="rounded-md bg-amber-500/10 px-1.5 py-0.5 text-meta text-amber-400">最近交易日</span>
          )}
          <span className="ml-auto rounded-md bg-surface-panel px-1.5 py-0.5 text-meta text-ink-muted">
            {data.source === "llm" ? "AI 精选" : data.source === "rule" ? "规则推荐" : "暂无推荐"} ·{" "}
            {data.candidates} 只达到行动级别
            {(data.watch_candidates ?? data.watchlist?.length ?? 0) > 0 &&
              ` · ${data.watch_candidates ?? data.watchlist?.length} 只被拦下待解锁`}
          </span>
        </div>
      )}

      {!data && !err && <div className="p-3 text-body text-ink-soft">正在扫描全市场并生成 AI 推荐...</div>}

      {data?.message && <div className="rounded-lg bg-surface-inset/70 px-3 py-2 text-body text-ink-muted">{data.message}</div>}

      {data?.recommendations?.length ? (
        <div className="space-y-3">
          <div className="max-h-[480px] space-y-2 overflow-y-auto pr-1">
          {data.recommendations.map((r, idx) => (
            <div
              key={r.code}
              onClick={() => toggle(r.code)}
              className={`cursor-pointer rounded-lg border p-3 transition-colors ${
                picked.has(r.code) ? "border-brand bg-brand/10" : "border-surface-line hover:border-surface-line-hover"
              }`}
            >
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-2">
                  <span className="flex h-5 w-5 items-center justify-center rounded-md bg-surface-inset text-meta font-bold text-ink-muted">
                    {idx + 1}
                  </span>
                  <span className="text-body font-medium text-white">{r.name}</span>
                  <span className="text-meta text-ink-muted">{r.code}</span>
                  <span className={`text-meta font-medium ${pnlTone(r.change_pct)}`}>
                    {r.change_pct >= 0 ? "+" : ""}
                    {r.change_pct.toFixed(2)}%
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-meta text-ink-soft">{r.price.toFixed(2)}</span>
                  <span
                    title={confidenceHint(r.confidence_source)}
                    className="rounded-md bg-state-warn-surface px-1.5 py-0.5 text-meta font-semibold text-state-warn-soft"
                  >
                    {confidenceLabel(r.confidence_source)} {r.confidence.toFixed(1)}
                  </span>
                  {picked.has(r.code) && <span className="text-meta text-brand-light">✓</span>}
                  <WatchStar code={r.code} />
                </div>
              </div>
              <p className="mt-1.5 text-meta leading-relaxed text-ink-muted">{r.reason}</p>
              {!!r.tags?.length && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {r.tags.map((tag) => (
                    <span key={tag} className="rounded-md border border-surface-line bg-surface-panel px-1.5 py-0.5 text-meta text-ink-muted">
                      {tag}
                    </span>
                  ))}
                </div>
              )}
              {(r.trigger || r.invalidation || r.target || r.expected_price != null) && (
                <>
                  <div className="mt-2 grid gap-1 rounded-xl border border-surface-line bg-surface-panel/70 p-2 text-meta sm:grid-cols-2 lg:grid-cols-4">
                    <div>
                      <span className="text-ink-muted">预期价格：</span>
                      {r.expected_price != null ? (
                        <>
                          <span className="font-semibold text-ink">{r.expected_price.toFixed(2)}</span>
                          <span className="text-ink-muted">
                            （{r.expected_price_setup === "breakout" ? "突破位" : "回踩位"}）
                          </span>
                          {r.expected_price_gap_pct != null && (
                            <span className="ml-1 text-ink-muted">
                              距现价 {r.expected_price_gap_pct >= 0 ? "+" : ""}
                              {r.expected_price_gap_pct}%
                            </span>
                          )}
                        </>
                      ) : (
                        // 结构位样本不足时显示「—」：折算成现价会造出一个假锚点
                        <span className="text-ink-faint">—</span>
                      )}
                    </div>
                    <div><span className="text-ink-muted">触发：</span><span className="text-green-300">{r.trigger || "等待确认"}</span></div>
                    <div><span className="text-ink-muted">失效：</span><span className="text-red-300">{r.invalidation || "转弱放弃"}</span></div>
                    <div><span className="text-ink-muted">目标：</span><span className="text-ink-soft">{r.target || "待确认"}</span></div>
                  </div>
                  {r.expected_price_note && (
                    <p className="mt-1 text-meta leading-relaxed text-ink-faint">
                      预期价格是执行锚点：{r.expected_price_note}。它取自结构位而非预测，
                      结构位买入侧实测超额为负（证据档 unsupported），只作挂单价参考。
                    </p>
                  )}
                </>
              )}
            </div>
          ))}
          </div>
        </div>
      ) : null}

      {data && !data.recommendations.length && !!data.watchlist?.length && (
        <div className="mt-3 space-y-3">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="flex items-center gap-1.5 text-body font-semibold text-amber-200">
                <Eye className="h-4 w-4" aria-hidden /> 先观察，别急着买
              </div>
            </div>
            <span className="rounded-full border border-state-warn-line bg-amber-500/10 px-2.5 py-1 text-meta text-state-warn-soft">
              {data.watchlist.length} 只待解锁
            </span>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            {data.watchlist.map((item) => {
              const unlock = item.unlock ?? item.trigger;
              const hasRR =
                item.rr_ratio != null || item.upside_pct != null || item.downside_pct != null;
              return (
                <button
                  key={item.code}
                  type="button"
                  onClick={() => onPick([item.code])}
                  className="group rounded-xl border border-surface-line bg-surface-inset/70 p-3 text-left transition hover:border-state-warn-line hover:bg-state-warn-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <span className="font-medium text-ink-strong">{item.name}</span>
                      <span className="ml-1.5 text-meta text-ink-muted">{item.code}</span>
                    </div>
                    <span className="text-meta font-semibold text-amber-300">{item.score.toFixed(1)}</span>
                  </div>
                  <div className="mt-2 flex items-start gap-1.5 text-meta text-ink-muted">
                    <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-400" aria-hidden />
                    <span>
                      <span className="text-ink-muted">拦截原因：</span>
                      {plainStatus(item.status, item.blockers)}
                    </span>
                  </div>
                  {hasRR && (
                    <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-meta">
                      {item.upside_pct != null && (
                        <span className="text-ink-soft">
                          上行 <span className={upTone()}>+{item.upside_pct}%</span>
                        </span>
                      )}
                      {item.downside_pct != null && (
                        <span className="text-ink-soft">
                          下行 <span className={downTone()}>-{item.downside_pct}%</span>
                        </span>
                      )}
                      {item.rr_ratio != null && (
                        <span className="text-ink-soft">
                          盈亏比{" "}
                          <span className={item.rr_ratio >= 1.2 ? upTone() : downTone()}>
                            {item.rr_ratio.toFixed(2)}
                          </span>
                          <span className="text-ink-muted"> / 门槛 1.2</span>
                        </span>
                      )}
                    </div>
                  )}
                  <div className="mt-1.5 flex items-start gap-1.5 text-meta text-ink-muted group-hover:text-ink-muted">
                    <Unlock className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500/80" aria-hidden />
                    <span>
                      <span className="text-ink-muted">解锁条件：</span>
                      {unlock || "等待技术信号进一步确认后再评估"}
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </>
  );

  if (collapsed) {
    return (
      <div className="space-y-3">
        <div className="flex items-center justify-end gap-2">
          {actions}
          {refreshBtn}
        </div>
        {body}
      </div>
    );
  }

  return (
    <CollapsiblePanel
      id="daily_recommend"
      title={data ? `今天有哪些可行动机会 · ${fmtDate(data.date)}` : "今天有哪些可行动机会"}
      action={
        <div className="flex items-center gap-2">
          {actions}
          {refreshBtn}
        </div>
      }
    >
      {body}
    </CollapsiblePanel>
  );
}
