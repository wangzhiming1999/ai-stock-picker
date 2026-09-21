import CollapsiblePanel from "../ui/CollapsiblePanel";
import Button from "../ui/Button";
import Input from "../ui/Input";
import Table, { Th } from "../ui/Table";
import { fmtNum, fmtPct } from "../../lib/safe";
import { CELL } from "../../lib/ui";
import { pnlTone } from "../../lib/tone";
import type { ScanFilters, ScanFilterKey } from "./shared";
import type { ScanStock } from "../../types";

interface Props {
  scanning: boolean;
  scanResult: ScanStock[];
  selected: Set<string>;
  err: string;
  filters: ScanFilters;
  onFilterChange: (key: ScanFilterKey, value: string) => void;
  onScan: () => void;
  onImportAll: () => void;
  onPickSelected: () => void;
  onToggle: (code: string) => void;
}

export default function MarketScanPanel({ scanning, scanResult, selected, err, filters, onFilterChange, onScan, onImportAll, onPickSelected, onToggle }: Props) {
  return (
    <CollapsiblePanel
      id="scan_market"
      title="按条件筛选"
      subtitle="这里只按价格、涨幅和成交额过滤，不代表技术形态已经确认"
    >
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <label className="block">
          <span className="mb-1 block text-meta text-ink-muted">最低涨幅 %</span>
          <Input value={filters.minChange} onChange={(e) => onFilterChange("minChange", e.target.value)} className="w-full rounded-lg bg-surface-inset/70 px-3 py-1.5 text-body" />
        </label>
        <label className="block">
          <span className="mb-1 block text-meta text-ink-muted">最低成交额(亿)</span>
          <Input value={filters.minAmount} onChange={(e) => onFilterChange("minAmount", e.target.value)} className="w-full rounded-lg bg-surface-inset/70 px-3 py-1.5 text-body" />
        </label>
        <label className="block">
          <span className="mb-1 block text-meta text-ink-muted">最低股价</span>
          <Input value={filters.minPrice} onChange={(e) => onFilterChange("minPrice", e.target.value)} className="w-full rounded-lg bg-surface-inset/70 px-3 py-1.5 text-body" />
        </label>
        <label className="block">
          <span className="mb-1 block text-meta text-ink-muted">最高股价</span>
          <Input value={filters.maxPrice} onChange={(e) => onFilterChange("maxPrice", e.target.value)} className="w-full rounded-lg bg-surface-inset/70 px-3 py-1.5 text-body" />
        </label>
        <label className="block">
          <span className="mb-1 block text-meta text-ink-muted">数量上限</span>
          <Input value={filters.limit} onChange={(e) => onFilterChange("limit", e.target.value)} className="w-full rounded-lg bg-surface-inset/70 px-3 py-1.5 text-body" />
        </label>
      </div>
      <button
        onClick={onScan}
        disabled={scanning}
        className="mt-4 rounded-lg bg-brand px-6 py-2 text-body font-medium text-white hover:bg-brand-dark">
        {scanning ? "扫描中..." : "开始扫描"}
      </button>

      {err && <div className="mt-3 rounded-lg border border-state-danger-line bg-state-danger-surface px-3 py-2 text-body text-state-danger-soft">{err}</div>}

      {scanResult.length > 0 && (
        <div className="mt-4">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-body text-ink-muted">扫描结果 {scanResult.length} 只（按成交额排序）</span>
            <div className="flex items-center gap-2">
              <button
                onClick={onImportAll}
                className="rounded-lg border border-surface-line-strong px-3 py-1 text-meta text-ink-soft hover:border-surface-line-hover hover:text-white"
              >
                全部加自选
              </button>
              <Button variant="primary" size="md"
                onClick={onPickSelected}
                disabled={selected.size === 0}
                >
                勾选 {selected.size} 只去分析 →
              </Button>
            </div>
          </div>
          <Table label="全市场扫描结果" maxHeight="sm" head={
            <tr>
              <Th>勾选</Th>
              <Th>名称</Th>
              <Th>代码</Th>
              <Th align="right">价格</Th>
              <Th align="right">涨跌幅</Th>
              <Th align="right">成交额(亿)</Th>
            </tr>
          }>
            {scanResult.map((s) => (
              <tr
                key={s.code}
                className={`cursor-pointer border-t border-surface-line-soft hover:bg-surface-inset/40 ${selected.has(s.code) ? "bg-surface-inset/70" : ""}`}
                onClick={() => onToggle(s.code)}
              >
                <td className={CELL}>
                  <input type="checkbox" readOnly checked={selected.has(s.code)} className="accent-brand" />
                </td>
                <td className={`${CELL} text-ink`}>{s.name}</td>
                <td className={`${CELL} text-ink-muted`}>{s.code}</td>
                <td className={`${CELL} text-right text-ink-soft`}>{fmtNum(s.price)}</td>
                <td className={`${CELL} text-right ${pnlTone(s.change_pct)}`}>
                  {fmtPct(s.change_pct)}
                </td>
                <td className={`${CELL} text-right text-ink-muted`}>{fmtNum(s.amount_yi)}</td>
              </tr>
            ))}
          </Table>
        </div>
      )}
    </CollapsiblePanel>
  );
}
