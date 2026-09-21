import { Download, Plus } from "lucide-react";
import type { MonitorInterval } from "../../types";
import { INTERVALS, LS_INTERVAL } from "./constants";
import Input from "../ui/Input";

interface Props {
  input: string;
  setInput: (v: string) => void;
  onAdd: () => void;
  onImportWatchlist: () => void;
  onImportHoldings: () => void;
  interval: MonitorInterval;
  setInterval: (v: MonitorInterval) => void;
}

/** 顶部工具条：周期切换 + 代码输入 + 导入自选/持仓 */
export default function MonitorToolbar({
  input,
  setInput,
  onAdd,
  onImportWatchlist,
  onImportHoldings,
  interval,
  setInterval,
}: Props) {
  return (
    <>
      {/* 周期切换：日线定方向，分钟线定这一笔 */}
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <div className="inline-flex rounded-lg border border-surface-line p-0.5">
          {INTERVALS.map((it) => (
            <button
              key={it.value}
              onClick={() => {
                setInterval(it.value);
                try {
                  localStorage.setItem(LS_INTERVAL, it.value);
                } catch {
                  /* ignore */
                }
              }}
              title={it.hint}
              className={`rounded-md px-3 py-1 text-meta transition-colors ${
                interval === it.value ? "bg-brand/15 text-brand-light" : "text-ink-muted hover:text-ink"
              }`}
            >
              {it.label}
            </button>
          ))}
        </div>
        <span className="text-meta text-ink-muted">
          {INTERVALS.find((i) => i.value === interval)?.hint}
        </span>
      </div>

      {/* 添加栏 */}
      <div className="mb-2 flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="flex flex-1 gap-2">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                onAdd();
              }
            }}
            placeholder="输入股票代码，空格/逗号分隔，如 600519 000858"
            className="flex-1 rounded-lg bg-surface-panel px-3 py-2 text-body"
          />
          <button
            onClick={onAdd}
            className="inline-flex items-center gap-1 rounded-lg bg-surface-inset px-3 py-2 text-body text-ink hover:bg-surface-line"
          >
            <Plus className="h-4 w-4" aria-hidden /> 添加
          </button>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={onImportWatchlist}
            title="把自选股一次性加入监控名单"
            className="inline-flex items-center gap-1 rounded-lg border border-surface-line px-2.5 py-1.5 text-meta text-ink-muted hover:text-ink"
          >
            <Download className="h-3.5 w-3.5" aria-hidden /> 导入自选
          </button>
          <button
            onClick={onImportHoldings}
            title="把持仓加入监控，并带上成本价（指令会显示浮盈浮亏）"
            className="inline-flex items-center gap-1 rounded-lg border border-surface-line px-2.5 py-1.5 text-meta text-ink-muted hover:text-ink"
          >
            <Download className="h-3.5 w-3.5" aria-hidden /> 导入持仓
          </button>
        </div>
      </div>
    </>
  );
}
