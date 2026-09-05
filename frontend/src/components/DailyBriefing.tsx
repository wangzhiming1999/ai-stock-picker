import { type MouseEvent, useCallback, useEffect, useState } from "react";
import { ArrowDownRight, ArrowUpRight, Bell, ClipboardCheck, Plus, RefreshCw, Sunrise, Target } from "lucide-react";
import { addToWatchlist, fetchBriefing, getAuthToken, simTrade } from "../api/client";
import type { Briefing, BriefingHolding, BriefingStock } from "../types";
import { toast } from "sonner";

/** 当日复盘块：持仓盈亏快照 + 今日触发预警（登录用户） */
function ReviewBlock({ review }: { review: NonNullable<Briefing["review"]> }) {
  const hp = review.holdings_pnl;
  const fmt = (v?: number | null, pct = false) => {
    if (v == null) return "—";
    const s = (v >= 0 ? "+" : "") + v.toFixed(2);
    return pct ? `${s}%` : s;
  };
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
      <div className="flex items-center gap-2 text-sm font-medium text-slate-200">
        <ClipboardCheck className="h-4 w-4 text-brand" />
        当日复盘
      </div>
      {review.summary && <p className="mt-1.5 text-xs text-slate-300">{review.summary}</p>}
      {hp && (hp.total_pnl != null || hp.count) && (
        <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
          <div className="rounded bg-slate-800/60 px-2 py-1.5">
            <div className="text-slate-500">持仓总盈亏</div>
            <div className={(hp.total_pnl ?? 0) >= 0 ? "text-green-300" : "text-red-300"}>
              {fmt(hp.total_pnl)}
              {hp.total_pnl_pct != null && <span className="ml-1">({fmt(hp.total_pnl_pct, true)})</span>}
            </div>
          </div>
          <div className="rounded bg-slate-800/60 px-2 py-1.5">
            <div className="text-slate-500">最强</div>
            <div className="text-green-300">
              {hp.best?.name ?? "—"} {hp.best?.pnl_pct != null && fmt(hp.best.pnl_pct, true)}
            </div>
          </div>
          <div className="rounded bg-slate-800/60 px-2 py-1.5">
            <div className="text-slate-500">最弱</div>
            <div className="text-red-300">
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
    </div>
  );
}

/** 模拟盘失败统一降级提示：500/网络错误给友好文案，其余透传后端消息 */
function simErrMsg(e: unknown): string {
  const msg = (e as Error)?.message || "";
  if (/500|NetworkError|Failed to fetch|timeout/i.test(msg)) return "模拟盘后端暂不可用，请稍后重试";
  return msg;
}

/** 技术位由规则推导的标识，避免误当确定性建议 */
function AlgoTag() {
  return (
    <span
      className="rounded bg-slate-700/40 px-1 text-[9px] leading-none text-slate-400"
      title="该价位/手数由技术位规则推导，非确定性建议"
    >
      算法推导
    </span>
  );
}

interface Props {
  onPick: (codes: string[]) => void;
}

function dirTone(direction: string): { text: string; bg: string; ring: string } {
  if (direction.includes("涨")) return { text: "text-green-400", bg: "bg-green-500/10", ring: "ring-green-500/30" };
  if (direction.includes("跌")) return { text: "text-red-400", bg: "bg-red-500/10", ring: "ring-red-500/30" };
  return { text: "text-amber-300", bg: "bg-amber-500/10", ring: "ring-amber-500/30" };
}

function actionTone(action: string): { text: string; bg: string; label: string } {
  if (action.includes("减仓")) return { text: "text-red-300", bg: "bg-red-500/10", label: "减仓" };
  if (action.includes("加仓")) return { text: "text-green-300", bg: "bg-green-500/10", label: "可加仓" };
  return { text: "text-slate-300", bg: "bg-slate-500/10", label: "持有" };
}

function Money({ v }: { v?: number | null }) {
  if (v == null) return <span className="text-slate-600">—</span>;
  return <span>{v.toFixed(2)}</span>;
}

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
      className="cursor-pointer rounded-lg border border-slate-800 bg-slate-900/60 p-3 transition-colors hover:border-brand/50 hover:bg-slate-900"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-baseline gap-2">
          <span className="font-semibold text-slate-100">{s.name}</span>
          <span className="text-xs text-slate-500">{s.code}</span>
        </div>
        <button
          onClick={addWatch}
          disabled={added}
          className={`flex shrink-0 items-center gap-1 rounded border px-2 py-0.5 text-[11px] transition-colors ${
            added
              ? "border-green-700 text-green-400"
              : "border-slate-700 text-slate-300 hover:border-brand hover:text-brand"
          }`}
        >
          <Plus className="h-3 w-3" />
          {added ? "已自选" : busy ? "..." : "加自选"}
        </button>
        <button
          onClick={simBuy}
          disabled={simBusy}
          className="flex shrink-0 items-center gap-1 rounded border border-red-800/60 bg-red-500/10 px-2 py-0.5 text-[11px] text-red-300 transition-colors hover:bg-red-500/20"
          title="用虚拟资金按建议手数一键模拟买入"
        >
          {simBusy ? "..." : "模拟买"}
        </button>
      </div>

      <div className="mt-1 flex items-center gap-1 text-xs text-slate-400">
        置信 <span className="font-semibold text-brand">{s.confidence ?? "—"}</span>
        {tip && <span className="ml-1 text-[11px] text-amber-300">{tip}</span>}
      </div>

      <div className="mt-2 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
        <div className="rounded bg-slate-800/60 px-2 py-1">
          <div className="text-slate-500">现价</div>
          <div className="text-slate-200"><Money v={s.price} /></div>
        </div>
        <div className="rounded bg-green-500/10 px-2 py-1">
          <div className="flex items-center gap-1 text-green-500/70">买点 <AlgoTag /></div>
          <div className="text-green-300"><Money v={s.buy_point} /></div>
        </div>
        <div className="rounded bg-red-500/10 px-2 py-1">
          <div className="flex items-center gap-1 text-red-500/70">止损 <AlgoTag /></div>
          <div className="text-red-300"><Money v={s.stop_loss} /></div>
        </div>
        <div className="rounded bg-slate-800/60 px-2 py-1">
          <div className="flex items-center gap-1 text-slate-500">建议 <AlgoTag /></div>
          <div className="text-slate-200">
            {s.suggest_shares ? `${s.suggest_shares}股` : "—"}
          </div>
        </div>
      </div>

      <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-slate-400">{s.reason}</p>
    </div>
  );
}

function PreMarketBlock({ data }: { data: Briefing }) {
  const m = data.market;
  const tone = dirTone(m.direction ?? "");
  const overseas = m.pre_market?.overseas;
  return (
    <div className="rounded-lg border border-amber-800/40 bg-amber-500/5 p-3">
      <div className="flex items-center gap-2 text-sm font-medium text-amber-200/90">
        <Sunrise className="h-4 w-4" />
        盘前预读 · 今日大方向
      </div>
      <div className="mt-2 flex flex-wrap items-end gap-x-4 gap-y-1">
        <div className="flex items-baseline gap-2">
          <span className="text-xs text-slate-500">大方向</span>
          <span className={`text-xl font-bold ${tone.text}`}>{m.direction || "—"}</span>
        </div>
        <div className="flex items-baseline gap-2">
          <span className="text-xs text-slate-500">建议仓位</span>
          <span className="text-base font-semibold text-slate-100">{m.position_suggestion || "—"}</span>
        </div>
      </div>
      <div className="mt-3">
        <div className="text-xs text-slate-500">隔夜外盘</div>
        {overseas && overseas.length > 0 ? (
          <div className="mt-1 grid grid-cols-3 gap-2">
            {overseas.map((o) => (
              <div key={o.name} className="rounded bg-slate-800/60 px-2 py-1 text-xs">
                <div className="truncate text-slate-400">{o.name}</div>
                <div className={o.change_pct >= 0 ? "text-green-300" : "text-red-300"}>
                  {o.change_pct >= 0 ? "+" : ""}
                  {o.change_pct.toFixed(2)}%
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="mt-1 text-xs text-slate-500">{m.pre_market?.note || "外盘数据暂不可用"}</div>
        )}
      </div>
    </div>
  );
}

function TailHoldingCard({ h }: { h: BriefingHolding }) {
  const tone = actionTone(h.action);
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
    <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-baseline gap-2">
          <span className="font-semibold text-slate-100">{h.name}</span>
          <span className="text-xs text-slate-500">{h.code}</span>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className={`rounded px-2 py-0.5 text-xs font-medium ${tone.bg} ${tone.text}`}>{tone.label}</span>
          <button
            onClick={() => void simOrder("sell")}
            disabled={simBusy}
            className="rounded border border-green-700/60 bg-green-500/10 px-2 py-0.5 text-[11px] text-green-300 transition-colors hover:bg-green-500/20"
            title="用虚拟资金模拟卖出（实时价）"
          >
            {simBusy ? "..." : "模拟卖"}
          </button>
          <button
            onClick={setReminder}
            disabled={watching}
            className={`rounded border px-2 py-0.5 text-[11px] transition-colors ${
              watching
                ? "border-brand/50 text-brand"
                : "border-slate-700 text-slate-300 hover:border-brand hover:text-brand"
            }`}
          >
            {watching ? "已盯盘" : busy ? "..." : "设提醒"}
          </button>
        </div>
      </div>

      <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
        <div className="rounded bg-slate-800/60 px-2 py-1">
          <div className="text-slate-500">现价/盈亏</div>
          <div className={h.pnl_pct != null && h.pnl_pct >= 0 ? "text-green-300" : "text-red-300"}>
            <Money v={h.price} />
            {h.pnl_pct != null && <span className="ml-1">{h.pnl_pct >= 0 ? "+" : ""}{h.pnl_pct.toFixed(1)}%</span>}
          </div>
        </div>
        <div className="rounded bg-red-500/10 px-2 py-1">
          <div className="flex items-center gap-1 text-red-500/70">止损 <AlgoTag /></div>
          <div className="text-red-300"><Money v={h.stop_loss} /></div>
        </div>
        <div className="rounded bg-slate-800/60 px-2 py-1">
          <div className="text-slate-500">仓位</div>
          <div className="text-slate-200">{h.position_pct != null ? `${h.position_pct}%` : "—"}</div>
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
          className={`mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border px-2 py-1.5 text-xs ${
            h.order_action === "卖出"
              ? "border-red-800/40 bg-red-500/5"
              : "border-green-800/40 bg-green-500/5"
          }`}
        >
          <span className={`font-semibold ${h.order_action === "卖出" ? "text-red-300" : "text-green-300"}`}>
            {h.order_action}挂单
          </span>
          {h.limit_price != null && (
            <span className="text-slate-200">
              价 ≈ <Money v={h.limit_price} />
            </span>
          )}
          <span className="text-slate-400">
            <AlgoTag /> {h.order_hint}
          </span>
        </div>
      )}
      {tip && <div className="mt-2 text-[11px] text-amber-300">{tip}</div>}
    </div>
  );
}

export default function DailyBriefing({ onPick }: Props) {
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
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const m = data?.market;
  const tone = dirTone(m?.direction ?? "");
  const phase = data?.phase ?? "morning";

  return (
    <section className="overflow-hidden rounded-xl border border-slate-800 bg-gradient-to-b from-slate-900 to-slate-950">
      {/* 总览条 */}
      <div className={`border-b border-slate-800 px-4 py-3 ${tone.bg}`}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Target className="h-4 w-4 text-brand" />
            <span className="text-xs text-slate-400">
              {data ? `${data.session} · 目标：盈利` : "今日作战简报"}
            </span>
          </div>
          <button
            onClick={() => void load()}
            disabled={loading}
            className="flex items-center gap-1 rounded-lg border border-slate-700 px-2 py-1 text-xs text-slate-400 hover:text-slate-200"
          >
            <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} />
            刷新
          </button>
        </div>

        {data ? (
          <div className="mt-2 flex flex-wrap items-end gap-x-4 gap-y-1">
            <div className="flex items-baseline gap-2">
              <span className="text-xs text-slate-500">今日大方向</span>
              <span className={`text-2xl font-bold ${tone.text}`}>{m?.direction || "—"}</span>
            </div>
            <div className="flex items-baseline gap-2">
              <span className="text-xs text-slate-500">建议仓位</span>
              <span className="text-lg font-semibold text-slate-100">{m?.position_suggestion || "—"}</span>
            </div>
            <span className="text-xs text-slate-500">
              指向 {data.target_date ?? "—"}（{data.is_trading_day ? "交易日" : "非交易日"}）
            </span>
          </div>
        ) : (
          <div className="mt-2 text-sm text-slate-500">加载中…</div>
        )}

        {m?.trading_advice && (
          <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-slate-400">{m.trading_advice}</p>
        )}
      </div>

      <div className="p-4">
        {err && <div className="mb-3 rounded-lg border border-red-800 bg-red-950/40 px-3 py-2 text-xs text-red-300">{err}</div>}

        {/* 盘前预读（仅盘前时段 9:00–9:25） */}
        {data?.is_premarket && <PreMarketBlock data={data} />}

        {/* 主区：按交易时段切换 */}
        {phase === "closed" && (
          <div className="rounded-lg border border-amber-800/40 bg-amber-500/5 px-4 py-3 text-sm text-amber-200/90">
            今日非交易日，下方为下一交易日关注池，开盘前可据此准备。
          </div>
        )}

        {/* 当日复盘（登录 + 有数据时展示：昨日操作结果与今日预警） */}
        {data?.review && (data.review.summary || data.review.alerts_today) && (
          <ReviewBlock review={data.review} />
        )}

        {phase === "tail" && (
          <div className="space-y-3">
            {data?.is_tail_urgent && (
              <div className="flex items-center gap-2 rounded-lg border border-red-800/50 bg-red-500/10 px-3 py-2 text-xs font-medium text-red-200">
                <Bell className="h-4 w-4 animate-pulse" />
                尾盘窗口（14:45–15:00）：收盘前必须完成挂单，否则今日无法操作
              </div>
            )}
            <div className="flex items-center gap-2 text-sm font-medium text-slate-200">
              <Bell className="h-4 w-4 text-brand" />
              尾盘操作（{data?.tail.summary ?? "持仓决策"}）
            </div>
            {data?.tail.need_login ? (
              <div className="rounded-lg border border-slate-800 bg-slate-900/60 px-4 py-6 text-center text-sm text-slate-400">
                登录后查看你的持仓尾盘操作建议
              </div>
            ) : data && data.tail.holdings.length > 0 ? (
              data.tail.holdings.map((h) => <TailHoldingCard key={h.code} h={h} />)
            ) : (
              <div className="rounded-lg border border-slate-800 bg-slate-900/60 px-4 py-6 text-center text-sm text-slate-400">
                {data?.tail.summary ?? "暂无持仓"}
              </div>
            )}
          </div>
        )}

        {/* 早盘关注池（任何时段都展示，作为今日清单） */}
        <div className="space-y-3">
          <div className="flex items-center gap-2 text-sm font-medium text-slate-200">
            {phase === "morning" ? (
              <ArrowUpRight className="h-4 w-4 text-green-400" />
            ) : (
              <ArrowDownRight className="h-4 w-4 text-slate-400" />
            )}
            {phase === "morning" ? "今日买什么（早盘关注池）" : "今日关注池（供尾盘对照）"}
          </div>
          {data && data.morning.stocks.length > 0 ? (
            <div className="grid gap-2 sm:grid-cols-2">
              {data.morning.stocks.map((s) => (
                <MorningStockCard key={s.code} s={s} onPick={(c) => onPick([c])} />
              ))}
            </div>
          ) : (
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 px-4 py-6 text-center text-sm text-slate-400">
              暂无推荐，收盘后策略扫描生成明日关注池
            </div>
          )}
        </div>

        <p className="mt-3 text-center text-[11px] leading-relaxed text-slate-600">
          买点 / 止损 / 手数均为<span className="text-slate-500">算法推导</span>，仅供参考，不构成投资建议；据此操作风险自担。
        </p>
      </div>
    </section>
  );
}
