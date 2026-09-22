import { cn } from "../../lib/cn";
import { DECISION_CHIP, decisionLabel, type Decision } from "../../lib/decision";

interface Props {
  decision: Decision;
  /** 用长文案（「不参与（空仓等待）」）—— 留给横向有空间的位置 */
  long?: boolean;
  /** 动作后的补充说明，如触发价「到 12.34」。让「买什么」变成「什么价买」。 */
  note?: string;
  className?: string;
}

/**
 * 决策动作角标 —— 全站唯一的动作渲染点。
 *
 * 存在的意义是不让各页面自己拼「建议减仓」「可关注」这类中文：动作词一旦分散，
 * 同一个动作在不同页面就会长得不一样，用户读到的是措辞而不是结论。
 * 颜色取自 `DECISION_CHIP`（买/加 = 红，卖/减 = 绿，持有/不参与 = 中性）。
 */
export default function DecisionBadge({ decision, long = false, note, className }: Props) {
  const chip = DECISION_CHIP[decision];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-meta font-medium",
        chip.bg,
        chip.text,
        className
      )}
    >
      {decisionLabel(decision, { long })}
      {note && <span className="font-normal opacity-80">{note}</span>}
    </span>
  );
}
