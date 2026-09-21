import CollapsiblePanel from "../ui/CollapsiblePanel";
import Button from "../ui/Button";
import Table, { Th } from "../ui/Table";
import { fmtNum, fmtPct } from "../../lib/safe";
import { CELL } from "../../lib/ui";
import { pnlTone } from "../../lib/tone";
import { STRATEGIES } from "./shared";
import type { StrategyName, StrategyStock } from "../../types";

interface Props {
  strategy: StrategyName;
  running: boolean;
  result: StrategyStock[];
  selected: Set<string>;
  attempted: boolean;
  error: string;
  cooldown: number;
  onRun: (s: StrategyName) => void;
  onForceRefresh: () => void;
  onImportAll: () => void;
  onPickSelected: () => void;
  onToggle: (code: string) => void;
}

export default function StrategyPanel({ strategy, running, result, selected, attempted, error, cooldown, onRun, onForceRefresh, onImportAll, onPickSelected, onToggle }: Props) {
  return (
    <CollapsiblePanel
      id="scan_strategy"
      title="一键找候选"
      subtitle="选择一种目标，按缓存行情给出候选；需要最新数据用强制刷新"
      action={
        <div className="flex items-center gap-2">
          <Button variant="outlineQuiet" size="sm"
            onClick={onForceRefresh}
            disabled={running || cooldown > 0}
            >
            {cooldown > 0 ? `冷却 ${cooldown}s` : "强制刷新"}
          </Button>
          {result.length > 0 && (
            <>
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
            </>
          )}
        </div>
      }
    >
      <div className="mb-4 grid grid-cols-2 gap-2 lg:grid-cols-4">
        {STRATEGIES.map((s) => (
          <button
            key={s.name}
            onClick={() => onRun(s.name)}
            disabled={running}
            className={`rounded-lg border p-3 text-left transition-colors ${
              strategy === s.name && result.length > 0
                ? "border-brand bg-brand/10"
                : "border-surface-line hover:border-surface-line-hover"
            }`}
          >
            <div className="text-body font-medium text-ink">{s.label}</div>
            <div className="mt-0.5 text-meta text-ink-soft">{s.desc}</div>
          </button>
        ))}
      </div>
      {running && <div className="rounded-lg bg-surface-inset/70 px-3 py-2 text-body text-ink-muted">策略扫描中（拉取行情与K线计算指标）...</div>}
      {!running && error && (
        <div role="alert" className="rounded-lg border border-state-danger-line bg-state-danger-surface px-3 py-2 text-body text-state-danger-soft">
          今日候选筛选失败：{error}
          <button onClick={() => onRun(strategy)} className="ml-3 cursor-pointer font-medium text-red-200 underline">重新筛选</button>
        </div>
      )}
      {!running && attempted && !error && result.length === 0 && (
        <div role="status" className="rounded-lg border border-surface-line bg-surface-inset/40 px-3 py-3 text-body text-ink-soft">
          当前条件没有筛出候选。可以换一个策略，或稍后等行情更新后重试。
        </div>
      )}
      {!running && result.length > 0 && (
        <Table label="策略扫描结果" maxHeight="sm" head={
          <tr>
            <Th>勾选</Th>
            <Th>名称</Th>
            <Th>代码</Th>
            <Th align="right">价格</Th>
            <Th align="right">涨跌幅</Th>
            <Th>策略分</Th>
            <Th>信号</Th>
          </tr>
        }>
          {result.map((s) => (
            <tr
              key={s.code}
              className={`cursor-pointer border-t border-surface-line-soft hover:bg-surface-inset/40 ${
                selected.has(s.code) ? "bg-surface-inset/70" : ""
              }`}
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
              <td className={`${CELL} text-right font-semibold text-brand-light`}>{fmtNum(s.strategy_score, 1)}</td>
              <td className={CELL}>
                <div className="flex flex-wrap gap-1">
                  {s.tags.map((t, i) => (
                    <span key={i} className="rounded-md bg-surface-inset px-1.5 py-0.5 text-meta text-ink-soft">
                      {t}
                    </span>
                  ))}
                </div>
              </td>
            </tr>
          ))}
        </Table>
      )}
    </CollapsiblePanel>
  );
}
