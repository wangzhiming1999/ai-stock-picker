import { useCallback, useEffect, useState } from "react";
import { ArrowDownRight, ArrowUpRight, Bell, RefreshCw, Target } from "lucide-react";
import { fetchBriefing } from "../api/client";
import type { Briefing, BriefingHolding, BriefingStock } from "../types";

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
  return (
    <button
      onClick={() => onPick(s.code)}
      className="w-full rounded-lg border border-slate-800 bg-slate-900/60 p-3 text-left transition-colors hover:border-brand/50 hover:bg-slate-900"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-baseline gap-2">
          <span className="font-semibold text-slate-100">{s.name}</span>
          <span className="text-xs text-slate-500">{s.code}</span>
        </div>
        <span className="text-xs text-slate-400">
          置信 <span className="font-semibold text-brand">{s.confidence ?? "—"}</span>
        </span>
      </div>

      <div className="mt-2 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
        <div className="rounded bg-slate-800/60 px-2 py-1">
          <div className="text-slate-500">现价</div>
          <div className="text-slate-200"><Money v={s.price} /></div>
        </div>
        <div className="rounded bg-green-500/10 px-2 py-1">
          <div className="text-green-500/70">买点</div>
          <div className="text-green-300"><Money v={s.buy_point} /></div>
        </div>
        <div className="rounded bg-red-500/10 px-2 py-1">
          <div className="text-red-500/70">止损</div>
          <div className="text-red-300"><Money v={s.stop_loss} /></div>
        </div>
        <div className="rounded bg-slate-800/60 px-2 py-1">
          <div className="text-slate-500">建议</div>
          <div className="text-slate-200">
            {s.suggest_shares ? `${s.suggest_shares}股` : "—"}
          </div>
        </div>
      </div>

      <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-slate-400">{s.reason}</p>
    </button>
  );
}

function TailHoldingCard({ h }: { h: BriefingHolding }) {
  const tone = actionTone(h.action);
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
      <div className="flex items-center justify-between">
        <div className="flex items-baseline gap-2">
          <span className="font-semibold text-slate-100">{h.name}</span>
          <span className="text-xs text-slate-500">{h.code}</span>
        </div>
        <span className={`rounded px-2 py-0.5 text-xs font-medium ${tone.bg} ${tone.text}`}>{tone.label}</span>
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
          <div className="text-red-500/70">止损</div>
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

        {/* 主区：按交易时段切换 */}
        {phase === "closed" && (
          <div className="rounded-lg border border-amber-800/40 bg-amber-500/5 px-4 py-3 text-sm text-amber-200/90">
            今日非交易日，下方为下一交易日关注池，开盘前可据此准备。
          </div>
        )}

        {phase === "tail" && (
          <div className="space-y-3">
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

        <p className="mt-3 text-center text-[11px] text-slate-600">
          信号由技术位推导，仅供参考，不构成投资建议
        </p>
      </div>
    </section>
  );
}
