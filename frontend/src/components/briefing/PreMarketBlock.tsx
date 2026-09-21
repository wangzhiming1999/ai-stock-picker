import type { Briefing } from "../../types";
import { SUB_QUIET, TEXT } from "../../lib/ui";
import { dirTone, pnlTone } from "../../lib/tone";

/** 盘前预读内容（标题由 ③ 分区提供）：仅盘前时段 9:00–9:25 展示 */
export function PreMarketBlock({ data }: { data: Briefing }) {
  const m = data.market;
  const tone = dirTone(m.direction ?? "");
  const overseas = m.pre_market?.overseas;
  return (
    <>
      <div className="flex flex-wrap items-end gap-x-5 gap-y-1">
        <div className="flex items-baseline gap-2">
          <span className={TEXT.meta}>大方向</span>
          <span className={`text-h1 font-bold ${tone.text}`}>{m.direction || "—"}</span>
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
                <div className="truncate text-meta text-ink-muted">{o.name}</div>
                <div className={`text-body font-semibold ${pnlTone(o.change_pct, 300)}`}>
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
