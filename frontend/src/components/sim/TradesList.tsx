import type { SimTradesData } from "../../types";
import { fmtTradeTime, slippageLabel, slippagePct } from "./shared";

/** 最近成交流水：买/卖徽章 + 标的 + 股数@价 + 预期价与滑点 + 时间。 */
export default function TradesList({ trades }: { trades: SimTradesData | null }) {
  if (!trades || trades.trades.length === 0) return null;
  return (
    <div className="mt-4 border-t border-slate-800 pt-3">
      <div className="mb-2 text-xs font-semibold text-ink-muted">最近成交（{trades.total}）</div>
      <div className="max-h-48 space-y-1 overflow-y-auto">
        {trades.trades.map((t) => {
          const slip = slippagePct(t);
          return (
            <div key={t.id} className="flex items-center justify-between rounded bg-slate-800/40 px-3 py-1.5 text-xs">
              <span className="flex flex-wrap items-center gap-2">
                <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${t.side === "buy" ? "bg-red-900/40 text-red-300" : "bg-green-900/40 text-green-300"}`}>
                  {t.side === "buy" ? "买" : "卖"}
                </span>
                <span className="text-ink">{t.name || t.code}</span>
                <span className="text-ink-faint">{t.shares}股 @ {t.price}</span>
                {t.expected_price != null && (
                  <span className="text-ink-faint">
                    预期 <span className="text-ink-muted">{t.expected_price}</span>
                  </span>
                )}
                {slip != null && <span className="text-ink-faint">{slippageLabel(slip)}</span>}
              </span>
              <span className="text-ink-faint">{fmtTradeTime(t.executed_at)}</span>
            </div>
          );
        })}
      </div>
      <p className="mt-1.5 text-xs text-ink-faint">
        预期价格是你建仓时填的计划成交价，只用于看执行偏差，<b className="text-ink-muted">不参与盈亏计算</b>。
      </p>
    </div>
  );
}
