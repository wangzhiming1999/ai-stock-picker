import type { Dispatch, SetStateAction } from "react";
import StockSearchInput from "../StockSearchInput";
import Button from "../ui/Button";
import { parseCodesFromText, type Phase } from "./shared";
import { CARD_FLUSH } from "../../lib/ui";

interface Props {
  input: string;
  /** 受控输入：由宿主持有，这里只透传。支持函数式更新（点选代码时去重追加）。 */
  onInputChange: Dispatch<SetStateAction<string>>;
  phase: Phase;
  /** 触发分析（点「开始分析」）。宿主传 run，保持请求生命周期在宿主内。 */
  onRun: (raw: string) => void;
  /** 运行中点的「停止」：中止但面板留着，方便换一批股票重跑 */
  onStop: () => void;
  /** 多空研究员对辩开关 */
  debate: boolean;
  onDebateChange: (v: boolean) => void;
}

/**
 * 输入区：搜索框 + 开始/停止 + 对辩开关。
 *
 * 为什么输入框状态留在宿主：深度分析是**流式长按**场景，Ctrl/Cmd+Enter 在键盘监听里
 * 也要读到最新 input，而那个监听刻意不随 input 变化重绑。所以 input 必须放在宿主、
 * 经 ref 暴露，这里只做展示与透传，不自己持有。
 */
export default function AnalysisInput({
  input,
  onInputChange,
  phase,
  onRun,
  onStop,
  debate,
  onDebateChange,
}: Props) {
  return (
    <div className={`${CARD_FLUSH} p-4`}>
      <label className="mb-2 block text-body font-medium text-ink-soft">
        股票搜索 <span className="ml-1 text-meta font-normal text-ink-muted">（代码/名称 · 支持多只）</span>
      </label>
      <div className="flex flex-col gap-3 sm:flex-row">
        <StockSearchInput
          value={input}
          onChange={onInputChange}
          onPickCode={(code) => {
            onInputChange((prev) => {
              const existing = parseCodesFromText(prev);
              if (existing.includes(code)) return prev;
              return [...existing, code].join(", ");
            });
          }}
          disabled={phase === "running"}
        />
        {phase === "running" ? (
          <button
            onClick={onStop}
            className="rounded-lg border border-surface-line-strong bg-surface-inset px-6 py-2.5 text-body font-medium text-ink hover:bg-surface-line"
          >
            停止
          </button>
        ) : (
          <Button variant="primary" size="xl" onClick={() => onRun(input)}>
            开始分析
          </Button>
        )}
      </div>
      <p className="mt-2 text-meta text-ink-soft">
        提示：Ctrl + Enter 触发分析 · Esc 收起 · 分析期间主界面可继续操作
      </p>
      <label className="mt-2 flex cursor-pointer items-start gap-2 text-meta text-ink-muted">
        <input
          type="checkbox"
          checked={debate}
          onChange={(e) => onDebateChange(e.target.checked)}
          disabled={phase === "running"}
          className="mt-0.5 accent-blue-600"
        />
        <span>
          多空研究员对辩
          <span className="ml-1 text-ink-muted">
            （每只票额外 2 轮 LLM 调用，更慢；结论仅为分歧与风险提示，不构成买卖依据）
          </span>
        </span>
      </label>
    </div>
  );
}
