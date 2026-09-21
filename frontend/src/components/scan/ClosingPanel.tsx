import CollapsiblePanel from "../ui/CollapsiblePanel";
import Button from "../ui/Button";
import Table, { Th } from "../ui/Table";
import { fmtNum, fmtPct } from "../../lib/safe";
import { CELL } from "../../lib/ui";
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
              className="rounded-lg border border-surface-line-strong px-3 py-1 text-meta text-ink-soft hover:border-surface-line-hover hover:text-white"
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
        <div className="mt-2 text-meta text-ink-muted">
          缓存 {result.trade_date} ·{" "}
          {result.generated_at ? new Date(result.generated_at).toLocaleTimeString() : "-"} 生成
        </div>
      )}
      {!loading && result?.needs_scan && (
        <div className="mt-3 rounded-lg border border-state-warn-line bg-state-warn-surface p-3 text-meta text-state-warn-soft">
          今日尚未生成尾盘机会。点击上方按钮生成（每交易日仅生成一次并缓存）。
        </div>
      )}
      {result?.items?.length ? (
        <Table label="尾盘异动" maxHeight="sm" className="mt-4" head={
          <tr>
            <Th>勾选</Th>
            <Th>名称</Th>
            <Th>代码</Th>
            <Th align="right">涨幅</Th>
            <Th align="right">5分</Th>
            <Th align="right">量比</Th>
            <Th align="right">换手%</Th>
            <Th align="right">评分</Th>
          </tr>
        }>
          {result.items.map((s) => (
            <tr
              key={s.code}
              onClick={() => onToggle(s.code)}
              className={`cursor-pointer border-t border-surface-line-soft hover:bg-surface-inset/40 ${selected.has(s.code) ? "bg-surface-inset/70" : ""}`}
            >
              <td className={CELL}>
                <input type="checkbox" readOnly checked={selected.has(s.code)} className="accent-brand" />
              </td>
              <td className={`${CELL} text-ink`}>{s.name}</td>
              <td className={`${CELL} text-ink-muted`}>{s.code}</td>
              <td className={`${CELL} text-right ${pnlTone(s.change_pct)}`}>
                {fmtPct(s.change_pct)}
              </td>
              <td className={`${CELL} text-right font-semibold ${pnlTone(s.change_5min)}`}>
                {fmtPct(s.change_5min)}
              </td>
              <td className={`${CELL} text-right text-amber-400`}>{fmtNum(s.volume_ratio)}</td>
              <td className={`${CELL} text-right text-ink-muted`}>{fmtNum(s.turnover)}</td>
              <td className={`${CELL} text-right font-semibold text-brand-light`}>{fmtNum(s.score)}</td>
            </tr>
          ))}
        </Table>
      ) : null}
    </CollapsiblePanel>
  );
}
