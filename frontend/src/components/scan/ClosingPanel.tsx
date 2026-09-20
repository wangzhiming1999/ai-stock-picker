import CollapsiblePanel from "../ui/CollapsiblePanel";
import Button from "../ui/Button";
import { fmtNum, fmtPct } from "../../lib/safe";
import { pnlTone } from "../../lib/tone";
import type { OpportunityResult } from "../../types";

interface Props {
  result: OpportunityResult | null;
  loading: boolean;
  cooldown: number;
  selected: Set<string>;
  /** 走缓存时先过二次确认与冷却闸门，再 force 重跑 */
  onRun: () => void;
  onImportAll: () => void;
  onPickSelected: () => void;
  onToggle: (code: string) => void;
}

export default function ClosingPanel({ result, loading, cooldown, selected, onRun, onImportAll, onPickSelected, onToggle }: Props) {
  return (
    <CollapsiblePanel
      id="scan_closing"
      title="收盘前有哪些异动"
      subtitle="仅 14:45-15:00 使用 · 需防范尾盘诱多"
      action={
        result?.items?.length ? (
          <div className="flex items-center gap-2">
            <button
              onClick={onImportAll}
              className="rounded-lg border border-slate-600 px-3 py-1 text-xs text-ink-soft hover:border-slate-400 hover:text-white"
            >
              全部加自选
            </button>
            <Button variant="primary" size="sm"
              onClick={onPickSelected}
              disabled={selected.size === 0}
              >
              勾选 {selected.size} 只去分析 →
            </Button>
          </div>
        ) : undefined
      }
    >
      <Button variant="info" size="lg"
        onClick={onRun}
        disabled={loading || cooldown > 0}
        >
        {loading
          ? "扫描中..."
          : cooldown > 0
            ? `冷却 ${cooldown}s`
            : result?.cached
              ? "刷新缓存（强制重跑）"
              : "扫描尾盘机会（14:45-15:00）"}
      </Button>
      {result?.cached && result.trade_date && (
        <div className="mt-2 text-xs text-ink-faint">
          缓存 {result.trade_date} ·{" "}
          {result.generated_at ? new Date(result.generated_at).toLocaleTimeString() : "-"} 生成
        </div>
      )}
      {!loading && result?.needs_scan && (
        <div className="mt-3 rounded-lg border border-amber-800/60 bg-amber-950/20 p-3 text-xs text-amber-200">
          今日尚未生成尾盘机会。点击上方按钮生成（每交易日仅生成一次并缓存）。
        </div>
      )}
      {result?.items?.length ? (
        <div className="mt-4 max-h-96 overflow-y-auto rounded-xl border border-slate-800">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-slate-900 text-left text-xs text-ink-muted">
              <tr>
                <th scope="col" className="px-3 py-2">勾选</th>
                <th scope="col" className="px-3 py-2">名称</th>
                <th scope="col" className="px-3 py-2">代码</th>
                <th scope="col" className="px-3 py-2 text-right">涨幅</th>
                <th scope="col" className="px-3 py-2 text-right">5分</th>
                <th scope="col" className="px-3 py-2 text-right">量比</th>
                <th scope="col" className="px-3 py-2 text-right">换手%</th>
                <th scope="col" className="px-3 py-2 text-right">评分</th>
              </tr>
            </thead>
            <tbody>
              {result.items.map((s) => (
                <tr
                  key={s.code}
                  onClick={() => onToggle(s.code)}
                  className={`cursor-pointer border-t border-slate-800/60 hover:bg-slate-800/40 ${selected.has(s.code) ? "bg-slate-800/70" : ""}`}
                >
                  <td className="px-3 py-2">
                    <input type="checkbox" readOnly checked={selected.has(s.code)} className="accent-brand" />
                  </td>
                  <td className="px-3 py-2 text-ink">{s.name}</td>
                  <td className="px-3 py-2 text-ink-faint">{s.code}</td>
                  <td className={`px-3 py-1.5 text-right ${pnlTone(s.change_pct)}`}>
                    {fmtPct(s.change_pct)}
                  </td>
                  <td className={`px-3 py-1.5 text-right font-semibold ${pnlTone(s.change_5min)}`}>
                    {fmtPct(s.change_5min)}
                  </td>
                  <td className="px-3 py-2 text-right text-amber-400">{fmtNum(s.volume_ratio)}</td>
                  <td className="px-3 py-2 text-right text-ink-muted">{fmtNum(s.turnover)}</td>
                  <td className="px-3 py-2 text-right font-semibold text-brand-light">{fmtNum(s.score)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </CollapsiblePanel>
  );
}
