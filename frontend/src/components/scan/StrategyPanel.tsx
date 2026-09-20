import CollapsiblePanel from "../ui/CollapsiblePanel";
import Button from "../ui/Button";
import { fmtNum, fmtPct } from "../../lib/safe";
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
                : "border-slate-700 hover:border-slate-500"
            }`}
          >
            <div className="text-sm font-medium text-ink">{s.label}</div>
            <div className="mt-0.5 text-xs text-ink-faint">{s.desc}</div>
          </button>
        ))}
      </div>
      {running && <div className="rounded-lg bg-slate-800/70 px-3 py-2 text-sm text-ink-muted">策略扫描中（拉取行情与K线计算指标）...</div>}
      {!running && error && (
        <div role="alert" className="rounded-lg border border-red-800 bg-red-950/40 px-3 py-2 text-sm text-red-300">
          今日候选筛选失败：{error}
          <button onClick={() => onRun(strategy)} className="ml-3 cursor-pointer font-medium text-red-200 underline">重新筛选</button>
        </div>
      )}
      {!running && attempted && !error && result.length === 0 && (
        <div role="status" className="rounded-lg border border-slate-700 bg-slate-800/40 px-3 py-3 text-sm text-ink-soft">
          当前条件没有筛出候选。可以换一个策略，或稍后等行情更新后重试。
        </div>
      )}
      {!running && result.length > 0 && (
        <div className="max-h-96 overflow-y-auto rounded-xl border border-slate-800">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-slate-900 text-left text-xs text-ink-muted">
              <tr>
                <th scope="col" className="px-3 py-2">勾选</th>
                <th scope="col" className="px-3 py-2">名称</th>
                <th scope="col" className="px-3 py-2">代码</th>
                <th scope="col" className="px-3 py-2 text-right">价格</th>
                <th scope="col" className="px-3 py-2 text-right">涨跌幅</th>
                <th scope="col" className="px-3 py-2">策略分</th>
                <th scope="col" className="px-3 py-2">信号</th>
              </tr>
            </thead>
            <tbody>
              {result.map((s) => (
                <tr
                  key={s.code}
                  className={`cursor-pointer border-t border-slate-800/60 hover:bg-slate-800/40 ${
                    selected.has(s.code) ? "bg-slate-800/70" : ""
                  }`}
                  onClick={() => onToggle(s.code)}
                >
                  <td className="px-3 py-2">
                    <input type="checkbox" readOnly checked={selected.has(s.code)} className="accent-brand" />
                  </td>
                  <td className="px-3 py-2 text-ink">{s.name}</td>
                  <td className="px-3 py-2 text-ink-faint">{s.code}</td>
                  <td className="px-3 py-2 text-right text-ink-soft">{fmtNum(s.price)}</td>
                  <td className={`px-3 py-1.5 text-right ${pnlTone(s.change_pct)}`}>
                    {fmtPct(s.change_pct)}
                  </td>
                  <td className="px-3 py-2 text-right font-semibold text-brand-light">{fmtNum(s.strategy_score, 1)}</td>
                  <td className="px-3 py-2">
                    <div className="flex flex-wrap gap-1">
                      {s.tags.map((t, i) => (
                        <span key={i} className="rounded bg-slate-800 px-1.5 py-0.5 text-xs text-ink-soft">
                          {t}
                        </span>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </CollapsiblePanel>
  );
}
