import { Bell, BellPlus, Trash2 } from "lucide-react";
import type { MonitorStock } from "../../types";
import { pnlTone } from "../../lib/tone";
import { CELL } from "../../lib/ui";
import { TacticChips } from "../TacticHit";
import { num, toneClass, toneDot } from "./constants";

interface Props {
  /** 缺失行情时（停牌/代码有误）传 undefined，渲染占位行 */
  it?: MonitorStock;
  code: string;
  idx: number;
  /** 是否已有本轮数据（决定占位文案是「暂无行情」还是「加载中」） */
  hasData: boolean;
  alertBusy: string | null;
  onQuickAlert: (it: MonitorStock) => void;
  onRemove: (code: string) => void;
}

/** 盯盘表格单行：现价 / 支撑压力或 VWAP / 指令 / 挂单计划（买·卖·止损档）/ 操作 */
export default function MonitorRow({ it, code, idx, hasData, alertBusy, onQuickAlert, onRemove }: Props) {
  if (!it) {
    return (
      <tr className="border-t border-surface-line-soft">
        <td className={`${CELL} text-meta text-ink-muted`}>{idx + 1}</td>
        <td className={CELL}>
          <span className="text-ink-muted">{code}</span>
        </td>
        <td colSpan={4} className={`${CELL} text-meta text-ink-soft`}>
          {hasData ? "暂无行情（可能停牌或代码有误）" : "加载中..."}
        </td>
        <td className={`${CELL} text-right`}>
          <button
            onClick={() => onRemove(code)}
            className="rounded-md p-1 text-ink-muted hover:bg-state-danger-surface hover:text-state-danger"
            title="移除"
          >
            <Trash2 className="h-4 w-4" aria-hidden />
          </button>
        </td>
      </tr>
    );
  }
  const { signal: s, advice: a } = it;
  const up = it.change_pct >= 0;
  const plan = a?.plan;
  const pnl = a?.pnl_pct;
  const intraday = a?.scope === "intraday";
  const trendMark = s?.trend === "up" ? "↑" : s?.trend === "down" ? "↓" : "→";
  return (
    <tr className="border-t border-surface-line-soft hover:bg-surface-inset/30">
      <td className={`${CELL} text-meta text-ink-muted`}>{idx + 1}</td>
      <td className={CELL}>
        <div className="font-medium text-ink-strong">{it.name}</div>
        <div className="text-meta text-ink-muted">{code}</div>
        {it.tactics && it.tactics.length > 0 && (
          <div className="mt-1">
            <TacticChips tactics={it.tactics} />
          </div>
        )}
      </td>
      <td className={`${CELL} text-right`}>
        <div className="text-ink">{num(it.price)}</div>
        <div className={`text-meta ${pnlTone(it.change_pct)}`}>
          {up ? "+" : ""}
          {num(it.change_pct, 2)}%
        </div>
        {pnl != null && (
          <div className={`text-meta ${pnlTone(pnl)}`}>
            浮盈 {pnl >= 0 ? "+" : ""}
            {num(pnl, 1)}%
          </div>
        )}
      </td>
      <td className={`${CELL} text-right`}>
        {intraday ? (
          <>
            <div className="text-ink">
              <span className="text-meta text-ink-muted">VWAP </span>
              {num(s?.vwap)}
            </div>
            <div className="text-meta">
              <span className="text-ink-muted/80">高 {num(s?.day_high)}</span>
              <span className="text-ink-faint"> / </span>
              <span className="text-ink-muted/80">低 {num(s?.day_low)}</span>
            </div>
            <div className="text-meta text-ink-soft">
              {trendMark} 强度 {num(s?.strength, 1)}
              {s?.volume_ratio != null ? ` · 量比 ${num(s.volume_ratio, 2)}x` : ""}
            </div>
          </>
        ) : (
          <>
            <div className="text-ink-soft">{num(s?.support)}</div>
            <div className="text-meta text-ink-soft">{num(s?.resistance)}</div>
            <div className="text-meta text-ink-soft">
              强度 {num(s?.strength, 1)}
              {s?.volume_ratio != null ? ` · 量比 ${num(s.volume_ratio, 2)}x` : ""}
            </div>
          </>
        )}
      </td>
      <td className={CELL}>
        <span
          title={a?.hint}
          className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-meta font-medium ${toneClass[a?.tone ?? "neutral"]}`}
        >
          <span className={`h-1.5 w-1.5 rounded-full ${toneDot[a?.tone ?? "neutral"]}`} />
          {a?.label ?? "等待信号"}
        </span>
        <div className="mt-0.5 max-w-[240px] truncate text-meta text-ink-soft" title={a?.hint}>
          {a?.hint ?? " "}
        </div>
      </td>
      <td className={CELL}>
        <div className="text-meta font-medium text-ink-strong">{a?.do ?? "—"}</div>
        <div className="mt-0.5 flex flex-wrap gap-x-2 text-meta text-ink-soft">
          <span>
            买 <b className="text-red-400/90">{num(plan?.buy)}</b>
          </span>
          <span>
            卖 <b className="text-amber-400/90">{num(plan?.sell)}</b>
          </span>
          <span>
            止损 <b className="text-amber-400/90">{num(plan?.stop)}</b>
          </span>
          {plan?.position_pct ? <span>仓位 {plan.position_pct}%</span> : null}
        </div>
        {intraday && it.daily && (
          <div className="mt-0.5 text-meta text-ink-soft">
            日线 支撑 {num(it.daily.support)} · 压力 {num(it.daily.resistance)}
          </div>
        )}
      </td>
      <td className={`${CELL} text-right`}>
        <div className="flex items-center justify-end gap-1">
          <button
            onClick={() => onQuickAlert(it)}
            disabled={alertBusy === code}
            className="rounded-md p-1 text-ink-muted hover:bg-surface-line/50 hover:text-amber-300"
            title="按建议价建到价提醒（到价后报警中心提醒）"
          >
            {alertBusy === code ? (
              <Bell className="h-4 w-4 animate-pulse" aria-hidden />
            ) : (
              <BellPlus className="h-4 w-4" aria-hidden />
            )}
          </button>
          <button
            onClick={() => onRemove(code)}
            className="rounded-md p-1 text-ink-muted hover:bg-state-danger-surface hover:text-state-danger"
            title="移除监控"
          >
            <Trash2 className="h-4 w-4" aria-hidden />
          </button>
        </div>
      </td>
    </tr>
  );
}
