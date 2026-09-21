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

export default function AuctionPanel({ result, loading, cooldown, selected, onRun, onImportAll, onPickSelected, onToggle }: Props) {
  return (
    <CollapsiblePanel
      id="scan_auction"
      title="开盘前有哪些异动"
      subtitle="仅 9:15-9:30 使用 · 异动不等于可以买"
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
      <Button variant="warn" size="lg"
        onClick={onRun}
        disabled={loading || cooldown > 0}
        >
        {loading
          ? "扫描中..."
          : cooldown > 0
            ? `冷却 ${cooldown}s`
            : result?.cached
              ? "刷新缓存（强制重跑）"
              : "扫描早盘竞价（9:15-9:30）"}
      </Button>
      {result?.cached && result.trade_date && (
        <div className="mt-2 text-meta text-ink-muted">
          缓存 {result.trade_date} ·{" "}
          {result.generated_at ? new Date(result.generated_at).toLocaleTimeString() : "-"} 生成
        </div>
      )}
      {!loading && result?.needs_scan && (
        <div className="mt-3 rounded-lg border border-state-warn-line bg-state-warn-surface p-3 text-meta text-state-warn-soft">
          今日尚未生成早盘竞价机会。点击上方按钮生成（每交易日仅生成一次并缓存）。
        </div>
      )}
      {result?.items?.length ? (
        <Table label="竞价异动" maxHeight="sm" className="mt-4" head={
          <tr>
            <Th>勾选</Th>
            <Th>名称</Th>
            <Th>代码</Th>
            <Th align="right">涨幅</Th>
            <Th align="right">量比</Th>
            <Th align="right">成交额(亿)</Th>
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
              <td className={`${CELL} text-right text-amber-400 font-semibold`}>{fmtNum(s.volume_ratio)}</td>
              <td className={`${CELL} text-right text-ink-muted`}>{fmtNum(s.amount_yi)}</td>
              <td className={`${CELL} text-right font-semibold text-brand-light`}>{fmtNum(s.score)}</td>
            </tr>
          ))}
        </Table>
      ) : null}
    </CollapsiblePanel>
  );
}
