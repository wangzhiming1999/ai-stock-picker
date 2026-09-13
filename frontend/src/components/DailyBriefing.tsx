import { type MouseEvent, type ReactNode, useCallback, useEffect, useState } from "react";
import { ArrowDownRight, ArrowUpRight, Bell, ClipboardCheck, Plus, RefreshCw, ShieldCheck, Sunrise, Target } from "lucide-react";
import { addToWatchlist, fetchBriefing, getAuthToken, simTrade } from "../api/client";
import type { Briefing, BriefingHolding, BriefingStock, BriefingTactics } from "../types";
import { actionBadge, actionTone, CHIP, dirTone, downTone, pnlTone, upTone } from "../lib/tone";
import { CARD, DIVIDER, SECTION, SUB, SUB_QUIET, TEXT } from "../lib/ui";
import { toast } from "sonner";

/** ③ 分区：不套容器，只用一条分隔线 + 留白切分主卡内部主题 */
function Section({
  icon,
  title,
  hint,
  children,
}: {
  icon: ReactNode;
  title: string;
  hint?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className={`mt-4 ${DIVIDER} pt-4`}>
      <div className={SECTION}>
        {icon}
        {title}
        {hint}
      </div>
      <div className="mt-2.5">{children}</div>
    </div>
  );
}

/** 当日复盘内容（标题由 ③ 分区提供）：持仓盈亏快照 + 今日触发预警 */
function ReviewBlock({ review }: { review: NonNullable<Briefing["review"]> }) {
  const hp = review.holdings_pnl;
  const fmt = (v?: number | null, pct = false) => {
    if (v == null) return "—";
    const s = (v >= 0 ? "+" : "") + v.toFixed(2);
    return pct ? `${s}%` : s;
  };
  return (
    <>
      {review.summary && <p className="text-xs leading-relaxed text-slate-300">{review.summary}</p>}
      {hp && (hp.total_pnl != null || hp.count) && (
        <div className="mt-2 grid grid-cols-3 gap-2">
          <div className={`${SUB_QUIET} px-2 py-1.5`}>
            <div className={TEXT.meta}>持仓总盈亏</div>
            <div className={`text-sm font-semibold ${pnlTone(hp.total_pnl, 300)}`}>
              {fmt(hp.total_pnl)}
              {hp.total_pnl_pct != null && <span className="ml-1 text-xs font-normal">({fmt(hp.total_pnl_pct, true)})</span>}
            </div>
          </div>
          <div className={`${SUB_QUIET} px-2 py-1.5`}>
            <div className={TEXT.meta}>最强</div>
            <div className={`truncate text-sm font-semibold ${upTone(300)}`}>
              {hp.best?.name ?? "—"} {hp.best?.pnl_pct != null && fmt(hp.best.pnl_pct, true)}
            </div>
          </div>
          <div className={`${SUB_QUIET} px-2 py-1.5`}>
            <div className={TEXT.meta}>最弱</div>
            <div className={`truncate text-sm font-semibold ${downTone(300)}`}>
              {hp.worst?.name ?? "—"} {hp.worst?.pnl_pct != null && fmt(hp.worst.pnl_pct, true)}
            </div>
          </div>
        </div>
      )}
      {review.alerts_today && review.alerts_today.length > 0 && (
        <div className="mt-2 space-y-1">
          {review.alerts_today.map((a, i) => (
            <div key={i} className="flex items-center gap-2 text-xs text-slate-300">
              <Bell
                className={`h-3 w-3 shrink-0 ${a.severity === "danger" ? "text-red-400" : "text-amber-400"}`}
              />
              <span className="truncate">
                {a.title} · {a.message}
              </span>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

/** 模拟盘失败统一降级提示：500/网络错误给友好文案，其余透传后端消息 */
function simErrMsg(e: unknown): string {
  const msg = (e as Error)?.message || "";
  if (/500|NetworkError|Failed to fetch|timeout/i.test(msg)) return "模拟盘后端暂不可用，请稍后重试";
  return msg;
}

/** 算法推导标识：不预判确定性，整卡只出现一次（放在卡片页脚），避免每个数字都挂标签 */
function AlgoTag() {
  return (
    <span className="text-slate-600" title="买点 / 止损 / 手数由技术位规则推导，非确定性建议">
      算法推导
    </span>
  );
}

interface Props {
  onPick: (codes: string[]) => void;
  onSettled?: () => void;
}

function Money({ v }: { v?: number | null }) {
  if (v == null) return <span className="text-slate-500">—</span>;
  return <span>{v.toFixed(2)}</span>;
}

/** 关注池股票卡：主数字只留 3 个（买点 / 止损 / 建议手数），现价并入头部 */
function MorningStockCard({ s, onPick }: { s: BriefingStock; onPick: (c: string) => void }) {
  const [added, setAdded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [tip, setTip] = useState("");
  const [simBusy, setSimBusy] = useState(false);

  const flashTip = (msg: string) => {
    setTip(msg);
    setTimeout(() => setTip(""), 1800);
  };

  const addWatch = async (e: MouseEvent) => {
    e.stopPropagation();
    if (busy || added) return;
    if (!getAuthToken()) {
      flashTip("请先登录");
      return;
    }
    setBusy(true);
    try {
      await addToWatchlist(s.code);
      setAdded(true);
      flashTip("已加入自选");
    } catch (err) {
      flashTip((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  /** 一键模拟买入（V5 闭环）：按建议手数预填，实时价成交 */
  const simBuy = async (e: MouseEvent) => {
    e.stopPropagation();
    if (simBusy) return;
    if (!getAuthToken()) {
      flashTip("请先登录");
      return;
    }
    setSimBusy(true);
    try {
      const shares = s.suggest_shares && s.suggest_shares % 100 === 0 ? s.suggest_shares : 100;
      const r = await simTrade({
        code: s.code,
        side: "buy",
        shares,
        source: "briefing",
        related_reco_id: s.id ?? null,
        note: `简报一键买入 · ${s.reason.slice(0, 30)}`,
      });
      toast.success("已模拟买入", { description: `${s.name} ${shares}股 @ 实时价` });
      flashTip("已模拟买入");
      void r;
    } catch (err) {
      toast.error(simErrMsg(err));
      flashTip(simErrMsg(err));
    } finally {
      setSimBusy(false);
    }
  };

  return (
    <div
      onClick={() => onPick(s.code)}
      className={`${SUB} cursor-pointer p-3 transition-colors hover:bg-slate-800`}
    >
      {/* 头部：名称 + 现价涨跌 + 操作 */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-baseline gap-2">
            <span className="text-sm font-semibold text-white">{s.name}</span>
            <span className={TEXT.meta}>{s.code}</span>
          </div>
          <div className="mt-0.5 flex items-baseline gap-2">
            <span className={TEXT.num}>
              <Money v={s.price} />
            </span>
            {s.change_pct != null && (
              <span className={`text-xs font-medium ${pnlTone(s.change_pct, 300)}`}>
                {s.change_pct >= 0 ? "+" : ""}
                {s.change_pct.toFixed(2)}%
              </span>
            )}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <button
            onClick={simBuy}
            disabled={simBusy}
            className={`rounded-lg border border-red-800/60 px-2 py-1 text-xs transition-colors hover:bg-red-500/20 ${CHIP.buy.bg} ${CHIP.buy.text}`}
            title="用虚拟资金按建议手数一键模拟买入"
          >
            {simBusy ? "..." : "模拟买"}
          </button>
          <button
            onClick={addWatch}
            disabled={added}
            className={`flex items-center gap-1 rounded-lg border px-2 py-1 text-xs transition-colors ${
              added
                ? "border-slate-700 text-slate-500"
                : "border-slate-700 text-slate-300 hover:border-brand hover:text-brand"
            }`}
          >
            <Plus className="h-3 w-3" />
            {added ? "已自选" : busy ? "..." : "自选"}
          </button>
        </div>
      </div>

      {/* 置信度：给数值一个标尺，否则「置信 7」没有任何参照 */}
      {s.confidence != null && (
        <div className="mt-2 flex items-center gap-2">
          <span className={TEXT.meta}>置信</span>
          <span className="text-xs font-semibold text-slate-200">{s.confidence}</span>
          <span className="h-1 w-16 overflow-hidden rounded-full bg-slate-800/40">
            <span
              className="block h-full rounded-full bg-brand"
              style={{ width: `${Math.max(0, Math.min(10, s.confidence)) * 10}%` }}
            />
          </span>
          <span className="text-xs text-slate-600">/ 10</span>
          {tip && <span className="ml-auto text-xs text-amber-300">{tip}</span>}
        </div>
      )}
      {s.confidence == null && tip && <div className="mt-1 text-xs text-amber-300">{tip}</div>}

      {/* 三个关键数字 */}
      <div className="mt-2 grid grid-cols-3 gap-2">
        <div className={`${CHIP.buy.bg} rounded-lg px-2 py-1.5`}>
          <div className={TEXT.meta}>买点</div>
          <div className={`text-sm font-semibold ${CHIP.buy.text}`}>
            <Money v={s.buy_point} />
          </div>
        </div>
        <div className={`${CHIP.risk.bg} rounded-lg px-2 py-1.5`}>
          <div className={TEXT.meta}>止损</div>
          <div className={`text-sm font-semibold ${CHIP.risk.text}`}>
            <Money v={s.stop_loss} />
          </div>
        </div>
        <div className={`${CHIP.neutral.bg} rounded-lg px-2 py-1.5`}>
          <div className={TEXT.meta}>建议</div>
          <div className={`text-sm font-semibold ${CHIP.neutral.text}`}>
            {s.suggest_shares ? `${s.suggest_shares}股` : "—"}
          </div>
        </div>
      </div>

      <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-slate-400">{s.reason}</p>

      {(s.trigger || s.invalidation) && (
        <div className={`mt-2 space-y-1 ${DIVIDER} pt-2 text-xs`}>
          <div>
            <span className={TEXT.meta}>满足才关注　</span>
            <span className="text-slate-200">{s.trigger}</span>
          </div>
          <div>
            <span className={TEXT.meta}>出现即放弃　</span>
            <span className="text-slate-400">{s.invalidation}</span>
          </div>
        </div>
      )}

      <div className="mt-2 text-xs">
        <AlgoTag />
      </div>
    </div>
  );
}

/** 盘前预读内容（标题由 ③ 分区提供）：仅盘前时段 9:00–9:25 展示 */
function PreMarketBlock({ data }: { data: Briefing }) {
  const m = data.market;
  const tone = dirTone(m.direction ?? "");
  const overseas = m.pre_market?.overseas;
  return (
    <>
      <div className="flex flex-wrap items-end gap-x-5 gap-y-1">
        <div className="flex items-baseline gap-2">
          <span className={TEXT.meta}>大方向</span>
          <span className={`text-xl font-bold ${tone.text}`}>{m.direction || "—"}</span>
        </div>
        <div className="flex items-baseline gap-2">
          <span className={TEXT.meta}>建议仓位</span>
          <span className={TEXT.num}>{m.position_suggestion || "—"}</span>
        </div>
      </div>
      <div className="mt-3">
        <div className={TEXT.meta}>隔夜外盘</div>
        {overseas && overseas.length > 0 ? (
          <div className="mt-1.5 grid grid-cols-3 gap-2">
            {overseas.map((o) => (
              <div key={o.name} className={`${SUB_QUIET} px-2 py-1.5`}>
                <div className="truncate text-xs text-slate-400">{o.name}</div>
                <div className={`text-sm font-semibold ${pnlTone(o.change_pct, 300)}`}>
                  {o.change_pct >= 0 ? "+" : ""}
                  {o.change_pct.toFixed(2)}%
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className={`mt-1 ${TEXT.meta}`}>{m.pre_market?.note || "外盘数据暂不可用"}</div>
        )}
      </div>
    </>
  );
}

function TailHoldingCard({ h }: { h: BriefingHolding }) {
  const tone = actionBadge(h.action);
  const [watching, setWatching] = useState(false);
  const [busy, setBusy] = useState(false);
  const [tip, setTip] = useState("");
  const [simBusy, setSimBusy] = useState(false);

  const flashTip = (msg: string) => {
    setTip(msg);
    setTimeout(() => setTip(""), 1800);
  };

  const setReminder = async () => {
    if (busy || watching) return;
    if (!getAuthToken()) {
      flashTip("请先登录");
      return;
    }
    setBusy(true);
    try {
      await addToWatchlist(h.code);
      setWatching(true);
      flashTip("已盯盘，盘中提醒即将上线");
    } catch (err) {
      flashTip((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  /** 一键模拟买入/卖出（V5）：按尾盘挂单方向预填，实时价成交 */
  const simOrder = async (side: "buy" | "sell") => {
    if (simBusy) return;
    if (!getAuthToken()) {
      flashTip("请先登录");
      return;
    }
    setSimBusy(true);
    try {
      const r = await simTrade({ code: h.code, side, shares: 100, source: "briefing", note: `简报尾盘${side === "buy" ? "买入" : "卖出"}` });
      toast.success(side === "buy" ? "已模拟买入" : "已模拟卖出", { description: `${h.name} 100股 @ 实时价` });
      flashTip(side === "buy" ? "已模拟买入" : "已模拟卖出");
      void r;
    } catch (err) {
      toast.error(simErrMsg(err));
      flashTip(simErrMsg(err));
    } finally {
      setSimBusy(false);
    }
  };

  return (
    <div className={`${SUB} p-3`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-baseline gap-2">
            <span className="text-sm font-semibold text-white">{h.name}</span>
            <span className={TEXT.meta}>{h.code}</span>
          </div>
          <div className="mt-0.5 flex items-baseline gap-2">
            <span className={TEXT.num}>
              <Money v={h.price} />
            </span>
            {h.pnl_pct != null && (
              <span className={`text-xs font-medium ${pnlTone(h.pnl_pct, 300)}`}>
                {h.pnl_pct >= 0 ? "+" : ""}
                {h.pnl_pct.toFixed(1)}%
              </span>
            )}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <span className={`rounded-lg px-2 py-1 text-xs font-medium ${tone.bg} ${tone.text}`}>{tone.label}</span>
          <button
            onClick={() => void simOrder("sell")}
            disabled={simBusy}
            className={`rounded-lg border border-green-700/60 px-2 py-1 text-xs transition-colors hover:bg-green-500/20 ${CHIP.sell.bg} ${CHIP.sell.text}`}
            title="用虚拟资金模拟卖出（实时价）"
          >
            {simBusy ? "..." : "模拟卖"}
          </button>
          <button
            onClick={setReminder}
            disabled={watching}
            className={`rounded-lg border px-2 py-1 text-xs transition-colors ${
              watching
                ? "border-brand/50 text-brand"
                : "border-slate-700 text-slate-300 hover:border-brand hover:text-brand"
            }`}
          >
            {watching ? "已盯盘" : busy ? "..." : "设提醒"}
          </button>
        </div>
      </div>

      <div className="mt-2 grid grid-cols-3 gap-2">
        <div className={`${CHIP.risk.bg} rounded-lg px-2 py-1.5`}>
          <div className={TEXT.meta}>止损</div>
          <div className={`text-sm font-semibold ${CHIP.risk.text}`}>
            <Money v={h.stop_loss} />
          </div>
        </div>
        <div className={`${SUB_QUIET} px-2 py-1.5`}>
          <div className={TEXT.meta}>仓位</div>
          <div className={`text-sm font-semibold ${CHIP.neutral.text}`}>
            {h.position_pct != null ? `${h.position_pct}%` : "—"}
          </div>
        </div>
        <div className={`${SUB_QUIET} px-2 py-1.5`}>
          <div className={TEXT.meta}>成本</div>
          <div className={`text-sm font-semibold ${CHIP.neutral.text}`}>
            {h.cost_price != null ? h.cost_price.toFixed(2) : "—"}
          </div>
        </div>
      </div>

      {h.tips.length > 0 && (
        <ul className="mt-2 space-y-1 text-xs text-slate-400">
          {h.tips.slice(0, 3).map((t, i) => (
            <li key={i} className="flex gap-1">
              <span className="text-slate-600">·</span>
              <span>{t}</span>
            </li>
          ))}
        </ul>
      )}

      {(h.order_action || h.limit_price != null) && (
        <div
          className={`mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-xl border px-2 py-1.5 text-xs ${
            h.order_action === "卖出"
              ? "border-green-800/40 bg-green-500/5"
              : "border-red-800/40 bg-red-500/5"
          }`}
        >
          <span className={`font-semibold ${actionTone(h.order_action, 300)}`}>
            {h.order_action}挂单
          </span>
          {h.limit_price != null && (
            <span className="text-slate-200">
              价 ≈ <Money v={h.limit_price} />
            </span>
          )}
          <span className="text-slate-400">{h.order_hint}</span>
        </div>
      )}
      {tip && <div className="mt-2 text-xs text-amber-300">{tip}</div>}
      <div className="mt-2 text-xs">
        <AlgoTag />
      </div>
    </div>
  );
}

/** 形态命中块：持仓偏风险（优先处理），关注池偏买点 */
function TacticsBlock({ tactics, onPick }: { tactics: BriefingTactics; onPick: (codes: string[]) => void }) {
  const groups = [
    { key: "holdings", label: "持仓形态信号", hint: "偏卖出 / 风险，优先处理", items: tactics.holdings },
    { key: "morning", label: "关注池形态命中", hint: "偏买点，需结合买点与止损", items: tactics.morning },
  ].filter((g) => g.items.length > 0);

  if (groups.length === 0) return null;

  return (
    <>
      {tactics.summary && <p className="text-xs leading-relaxed text-slate-400">{tactics.summary}</p>}
      <div className="mt-2 space-y-2">
        {groups.map((g) => (
          <div key={g.key}>
            <div className={TEXT.meta}>
              {g.label} · {g.hint}
            </div>
            <div className="mt-1 space-y-1">
              {g.items.map((it) => (
                <button
                  key={it.code}
                  onClick={() => onPick([it.code])}
                  className={`${SUB_QUIET} w-full px-2 py-1.5 text-left transition-colors hover:bg-slate-800/70`}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs font-medium text-slate-100">{it.name}</span>
                    <span className={TEXT.meta}>{it.code}</span>
                    {it.tactics.map((t) => (
                      <span
                        key={t.key}
                        title={t.action}
                        className={`rounded-lg px-1.5 py-0.5 text-xs ${
                          t.direction === "buy" ? "bg-red-600/20" : "bg-green-600/20"
                        } ${actionTone(t.direction, 300)}`}
                      >
                        {t.name}
                      </span>
                    ))}
                  </div>
                  <div className="mt-0.5 text-xs leading-relaxed text-slate-400">
                    {it.tactics.map((t) => t.action).join("；")}
                  </div>
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </>
  );
}

export default function DailyBriefing({ onPick, onSettled }: Props) {
  const [data, setData] = useState<Briefing | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setErr("");
    try {
      setData(await fetchBriefing());
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
      onSettled?.();
    }
  }, [onSettled]);

  useEffect(() => {
    void load();
  }, [load]);

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
          <Target className="h-4 w-4 text-brand" />
          <h1 className={TEXT.title}>今天怎么做</h1>
          {data && <span className={TEXT.meta}>· {data.target_date ?? "下一个交易日"}</span>}
        </div>
        <button
          onClick={() => void load()}
          disabled={loading}
          className="flex items-center gap-1 rounded-lg border border-slate-700 px-2.5 py-1 text-xs text-slate-400 transition-colors hover:text-slate-200 disabled:opacity-50"
        >
          <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} />
          刷新
        </button>
      </div>

      {err && (
        <div className="mt-3 rounded-xl border border-red-800/70 bg-red-950/40 px-3 py-2 text-xs text-red-300">{err}</div>
      )}

      {!data ? (
        <div className="mt-4 text-sm text-slate-500">加载中…</div>
      ) : (
        <>
          {/* ① 主结论：全屏唯一一处 24px，视线第一落点 */}
          <div className={`mt-4 ${TEXT.hero} ${hasPicks ? upTone(300) : "text-amber-300"}`}>{mainAction}</div>
          {m?.trading_advice && (
            <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-slate-400">{m.trading_advice}</p>
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
              <Bell className="h-4 w-4 animate-pulse" />
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
            <Section icon={<Bell className="h-4 w-4 text-brand" />} title={`尾盘操作（${data.tail.summary ?? "持仓决策"}）`}>
              {needLogin ? (
                <div className={`${SUB} px-4 py-6 text-center text-sm text-slate-400`}>
                  登录后查看你的持仓尾盘操作建议
                </div>
              ) : (
                <div className="space-y-2">
                  {data.tail.holdings.map((h) => (
                    <TailHoldingCard key={h.code} h={h} />
                  ))}
                </div>
              )}
            </Section>
          )}

          {/* ③ 分区：今天关注这几只（任何时段都作为今日清单） */}
          <Section
            icon={
              phase === "morning" ? (
                <ArrowUpRight className={`h-4 w-4 ${upTone(400)}`} />
              ) : (
                <ArrowDownRight className="h-4 w-4 text-slate-400" />
              )
            }
            title={hasPicks ? "今天关注这几只" : "为什么今天没有推荐"}
            hint={hasPicks ? <span className={TEXT.meta}>共 {picks.length} 只</span> : undefined}
          >
            {hasPicks ? (
              <div className="grid gap-2 sm:grid-cols-2">
                {picks.map((s) => (
                  <MorningStockCard key={s.code} s={s} onPick={(c) => onPick([c])} />
                ))}
              </div>
            ) : (
              <div
                role="status"
                className="flex items-start gap-3 rounded-xl border border-amber-900/40 bg-amber-500/5 px-3 py-3"
              >
                <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
                <div>
                  <div className="text-sm font-medium text-amber-200">没有股票同时满足上涨趋势和风险控制要求</div>
                  <p className="mt-1 text-xs leading-relaxed text-slate-400">
                    先不新开仓。下方"先观察，别急着买"会列出接近条件的股票，以及还要等待什么。
                  </p>
                </div>
              </div>
            )}
          </Section>

          {/* ③ 分区：盘前预读（仅 9:00–9:25） */}
          {data.is_premarket && (
            <Section icon={<Sunrise className="h-4 w-4 text-amber-400" />} title="盘前预读">
              <PreMarketBlock data={data} />
            </Section>
          )}

          {/* ③ 分区：当日复盘 */}
          {reviewReady && data.review && (
            <Section icon={<ClipboardCheck className="h-4 w-4 text-brand" />} title="当日复盘">
              <ReviewBlock review={data.review} />
            </Section>
          )}

          {/* ③ 分区：形态命中（附加信息，放最后） */}
          {tacticsReady && data.tactics && (
            <Section icon={<Target className="h-4 w-4 text-sky-400" />} title="形态命中">
              <TacticsBlock tactics={data.tactics} onPick={onPick} />
            </Section>
          )}

          <p className={`mt-4 ${DIVIDER} pt-3 text-center text-xs leading-relaxed text-slate-600`}>
            买点 / 止损 / 手数均为算法推导，仅供参考，不构成投资建议；据此操作风险自担。
          </p>
        </>
      )}
    </section>
  );
}
