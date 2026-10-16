import { useState } from "react";
import { addToWatchlist, getAuthToken, simTrade } from "../../api/client";
import type { Briefing, BriefingHolding, HoldingDecision } from "../../types";
import { SUB, SUB_QUIET, TEXT } from "../../lib/ui";
import { CHIP, actionTone, pnlTone } from "../../lib/tone";
import DecisionBadge from "../ui/DecisionBadge";
import { toast } from "sonner";
import { AlgoTag, Money, simErrMsg } from "./shared";

function TailHoldingCard({ h, d }: { h: BriefingHolding; d?: HoldingDecision }) {
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
            <span className="text-body font-semibold text-white">{h.name}</span>
            <span className={TEXT.meta}>{h.code}</span>
          </div>
          <div className="mt-0.5 flex items-baseline gap-2">
            <span className={TEXT.num}>
              <Money v={h.price} />
            </span>
            {h.pnl_pct != null && (
              <span className={`text-meta font-medium ${pnlTone(h.pnl_pct, 300)}`}>
                {h.pnl_pct >= 0 ? "+" : ""}
                {h.pnl_pct.toFixed(1)}%
              </span>
            )}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {/* 动作一律走 DecisionBadge（决策契约唯一渲染点）。
              有结构化决策（B）时用它的动作，否则退回旧文案。 */}
          {d ? <DecisionBadge decision={d.decision.action} long /> : (
            <span className="rounded-lg bg-surface-inset px-2 py-1 text-meta font-medium text-ink-soft">{h.action || "持有不动"}</span>
          )}
          <button
            onClick={() => void simOrder("sell")}
            disabled={simBusy}
            className={`rounded-lg border border-green-700/60 px-2 py-1 text-meta transition-colors hover:bg-green-500/20 ${CHIP.sell.bg} ${CHIP.sell.text}`}
            title="用虚拟资金模拟卖出（实时价）"
          >
            {simBusy ? "..." : "模拟卖"}
          </button>
          <button
            onClick={setReminder}
            disabled={watching}
            className={`rounded-lg border px-2 py-1 text-meta transition-colors ${
              watching
                ? "border-brand/50 text-brand-light"
                : "border-surface-line text-ink-soft hover:border-brand hover:text-brand-light"
            }`}
          >
            {watching ? "已盯盘" : busy ? "..." : "设提醒"}
          </button>
        </div>
      </div>

      <div className="mt-2 grid grid-cols-3 gap-2">
        <div className={`${CHIP.risk.bg} rounded-lg px-2 py-1.5`}>
          <div className={TEXT.meta}>止损</div>
          <div className={`text-body font-semibold ${CHIP.risk.text}`}>
            <Money v={h.stop_loss} />
          </div>
        </div>
        <div className={`${SUB_QUIET} px-2 py-1.5`}>
          <div className={TEXT.meta}>仓位</div>
          <div className={`text-body font-semibold ${CHIP.neutral.text}`}>
            {h.position_pct != null ? `${h.position_pct}%` : "—"}
          </div>
        </div>
        <div className={`${SUB_QUIET} px-2 py-1.5`}>
          <div className={TEXT.meta}>成本</div>
          <div className={`text-body font-semibold ${CHIP.neutral.text}`}>
            {h.cost_price != null ? h.cost_price.toFixed(2) : "—"}
          </div>
        </div>
      </div>

      {h.tips.length > 0 && (
        <ul className="mt-2 space-y-1 text-meta text-ink-muted">
          {h.tips.slice(0, 3).map((t, i) => (
            <li key={i} className="flex gap-1">
              <span className="text-ink-faint">·</span>
              <span>{t}</span>
            </li>
          ))}
        </ul>
      )}

      {/* 结构化持仓决策（B）：理由 + 触发价 + 失效条件。
          此前这里只有 tips 文字 —— 用户读完仍不知道「到什么价该动手」。
          止盈/止损全部锚结构位（支撑/压力/止损位），不用现价系数。 */}
      {d && (
        <div className="mt-2 space-y-1">
          <p className="text-meta leading-relaxed text-ink-soft">{d.decision.reason}</p>
          <div className="grid gap-1.5 sm:grid-cols-2">
            <div className="rounded-lg bg-surface-inset/60 px-2 py-1.5">
              <div className="text-label font-medium text-ink-muted">触发</div>
              <p className="mt-0.5 text-meta leading-relaxed text-ink-soft">{d.decision.trigger || "—"}</p>
            </div>
            <div className="rounded-lg bg-surface-inset/60 px-2 py-1.5">
              <div className="text-label font-medium text-ink-muted">失效</div>
              <p className="mt-0.5 text-meta leading-relaxed text-ink-soft">{d.decision.invalidation || "—"}</p>
            </div>
          </div>
          {d.sector_state && d.sector_state !== "follow_steady" && d.sector_state !== "unknown" && (
            <p className="text-micro text-ink-muted">
              所属板块「{d.sector}」资金状态：
              <b className={d.sector_state === "follow_exit" ? "text-green-400" : d.sector_state === "follow_ebb" ? "text-amber-300" : "text-red-400"}>
                {d.sector_state === "follow_accel" ? "加速流入" : d.sector_state === "follow_exit" ? "撤离" : "退潮"}
              </b>
            </p>
          )}
        </div>
      )}

      {(h.order_action || h.limit_price != null) && (
        <div
          className={`mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-xl border px-2 py-1.5 text-meta ${
            h.order_action === "卖出"
              ? "border-green-800/40 bg-green-500/5"
              : "border-state-danger-line bg-red-500/5"
          }`}
        >
          <span className={`font-semibold ${actionTone(h.order_action, 300)}`}>
            {h.order_action}挂单
          </span>
          {h.limit_price != null && (
            <span className="text-ink">
              价 ≈ <Money v={h.limit_price} />
            </span>
          )}
          <span className="text-ink-muted">{h.order_hint}</span>
        </div>
      )}
      {tip && <div className="mt-2 text-meta text-amber-300">{tip}</div>}
      <div className="mt-2 text-meta">
        <AlgoTag />
      </div>
    </div>
  );
}

/** 尾盘操作块：有持仓列卡片；未登录给登录引导（这一支的判定由 need_login 决定）。 */
export function TailHoldingsBlock({ tail }: { tail: Briefing["tail"] }) {
  if (tail.need_login) {
    return (
      <div className={`${SUB} px-4 py-6 text-center text-body text-ink-muted`}>
        登录后查看你的持仓尾盘操作建议
      </div>
    );
  }
  // 结构化决策按 code 索引（后端已按风险优先排序，前端不二次排序）
  const byCode = new Map((tail.decisions ?? []).map((d) => [String(d.code), d]));
  return (
    <div className="space-y-2">
      {tail.decisions_summary && (
        <p className="text-meta text-ink-muted">
          {tail.decisions_summary.summary}
          <span className="ml-1.5 text-ink-faint">按风险优先排序</span>
        </p>
      )}
      {tail.holdings.map((h) => (
        <TailHoldingCard key={h.code} h={h} d={byCode.get(String(h.code))} />
      ))}
    </div>
  );
}
