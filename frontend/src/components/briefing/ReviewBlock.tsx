import { Bell } from "lucide-react";
import type { Briefing } from "../../types";
import { SUB_QUIET, TEXT } from "../../lib/ui";
import { downTone, pnlTone, upTone } from "../../lib/tone";

/** 当日复盘内容（标题由 ③ 分区提供）：持仓盈亏快照 + 今日触发预警 */
export function ReviewBlock({ review }: { review: NonNullable<Briefing["review"]> }) {
  const hp = review.holdings_pnl;
  const fmt = (v?: number | null, pct = false) => {
    if (v == null) return "—";
    const s = (v >= 0 ? "+" : "") + v.toFixed(2);
    return pct ? `${s}%` : s;
  };
  return (
    <>
      {review.summary && <p className="text-meta leading-relaxed text-ink-soft">{review.summary}</p>}
      {hp && (hp.total_pnl != null || hp.count) && (
        <div className="mt-2 grid grid-cols-3 gap-2">
          <div className={`${SUB_QUIET} px-2 py-1.5`}>
            <div className={TEXT.meta}>持仓总盈亏</div>
            <div className={`text-body font-semibold ${pnlTone(hp.total_pnl, 300)}`}>
              {fmt(hp.total_pnl)}
              {hp.total_pnl_pct != null && <span className="ml-1 text-meta font-normal">({fmt(hp.total_pnl_pct, true)})</span>}
            </div>
          </div>
          <div className={`${SUB_QUIET} px-2 py-1.5`}>
            <div className={TEXT.meta}>最强</div>
            <div className={`truncate text-body font-semibold ${upTone(300)}`}>
              {hp.best?.name ?? "—"} {hp.best?.pnl_pct != null && fmt(hp.best.pnl_pct, true)}
            </div>
          </div>
          <div className={`${SUB_QUIET} px-2 py-1.5`}>
            <div className={TEXT.meta}>最弱</div>
            <div className={`truncate text-body font-semibold ${downTone(300)}`}>
              {hp.worst?.name ?? "—"} {hp.worst?.pnl_pct != null && fmt(hp.worst.pnl_pct, true)}
            </div>
          </div>
        </div>
      )}
      {review.alerts_today && review.alerts_today.length > 0 && (
        <div className="mt-2 space-y-1">
          {review.alerts_today.map((a, i) => (
            <div key={i} className="flex items-center gap-2 text-meta text-ink-soft">
              <Bell
                className={`h-3 w-3 shrink-0 ${a.severity === "danger" ? "text-red-400" : "text-amber-400"}`} aria-hidden />
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
