import { type MouseEvent, useState } from "react";
import { Plus, ShieldCheck } from "lucide-react";
import { addToWatchlist, getAuthToken, simTrade } from "../../api/client";
import type { BriefingStock } from "../../types";
import { DIVIDER, SUB, TEXT } from "../../lib/ui";
import { CHIP, pnlTone } from "../../lib/tone";
import { confidenceHint, confidenceLabel } from "../../lib/confidence";
import { toast } from "sonner";
import { AlgoTag, Money, simErrMsg } from "./shared";

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
                ? "border-slate-700 text-ink-faint"
                : "border-slate-700 text-ink-soft hover:border-brand hover:text-brand-light"
            }`}
          >
            <Plus className="h-3 w-3" aria-hidden />
            {added ? "已自选" : busy ? "..." : "自选"}
          </button>
        </div>
      </div>

      {/* 置信度：给数值一个标尺，否则「置信 7」没有任何参照。
          标签随来源变化 —— AI 自评 vs 规则策略分是两回事，不能共用「置信」一个词 */}
      {s.confidence != null && (
        <div className="mt-2 flex items-center gap-2">
          <span className={TEXT.meta} title={confidenceHint(s.confidence_source)}>
            {confidenceLabel(s.confidence_source)}
          </span>
          <span className="text-xs font-semibold text-ink">{s.confidence}</span>
          <span className="h-1 w-16 overflow-hidden rounded-full bg-slate-800/40">
            <span
              className="block h-full rounded-full bg-brand"
              style={{ width: `${Math.max(0, Math.min(10, s.confidence)) * 10}%` }}
            />
          </span>
          <span className="text-xs text-ink-faint">/ 10</span>
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

      <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-ink-muted">{s.reason}</p>

      {(s.trigger || s.invalidation) && (
        <div className={`mt-2 space-y-1 ${DIVIDER} pt-2 text-xs`}>
          <div>
            <span className={TEXT.meta}>满足才关注　</span>
            <span className="text-ink">{s.trigger}</span>
          </div>
          <div>
            <span className={TEXT.meta}>出现即放弃　</span>
            <span className="text-ink-muted">{s.invalidation}</span>
          </div>
        </div>
      )}

      <div className="mt-2 text-xs">
        <AlgoTag />
      </div>
    </div>
  );
}

/** 早盘方向块：今天关注这几只（没推荐时给空状态卡片，文案原样保留）。 */
export function MorningStocksBlock({ stocks, onPick }: { stocks: BriefingStock[]; onPick: (codes: string[]) => void }) {
  if (stocks.length === 0) {
    return (
      <div
        role="status"
        className="flex items-start gap-3 rounded-xl border border-amber-900/40 bg-amber-500/5 px-3 py-3"
      >
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" aria-hidden />
        <div>
          <div className="text-sm font-medium text-amber-200">没有股票同时满足上涨趋势和风险控制要求</div>
          <p className="mt-1 text-xs leading-relaxed text-ink-muted">
            先不新开仓。下方"先观察，别急着买"会列出接近条件的股票，以及还要等待什么。
          </p>
        </div>
      </div>
    );
  }
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {stocks.map((s) => (
        <MorningStockCard key={s.code} s={s} onPick={(c) => onPick([c])} />
      ))}
    </div>
  );
}
