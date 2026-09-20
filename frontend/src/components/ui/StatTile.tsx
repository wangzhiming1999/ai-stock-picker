import type { ReactNode } from "react";
import { STAT, STAT_LABEL, STAT_VALUE } from "../../lib/ui";

interface Props {
  /** 数值本身（已格式化好的文案，如 "1,234" / "+2.31%"） */
  value: ReactNode;
  /** 这个数字是什么 */
  label: string;
  /**
   * 数字的颜色类。需要按语义上色时传 tone 函数的返回值，如
   * `valueClass={pnlTone(totalPnl)}` / `valueClass={pctTone(hitRate)}`。
   * 不传则用默认色 text-ink。
   */
  valueClass?: string;
}

/**
 * 统计格：一个数字 + 一行标签的等宽单元。
 *
 * 此前这套结构在 4 个文件里逐字重复了 17 次
 * （PortfolioPanel / PredictionCard / SimPanel / WinratePanel），
 * 底色、内边距、字号、字重全靠复制 —— 改一次要动 17 处。
 */
export default function StatTile({ value, label, valueClass }: Props) {
  return (
    <div className={STAT}>
      <div className={`${STAT_VALUE} ${valueClass ?? "text-ink"}`}>{value}</div>
      <div className={STAT_LABEL}>{label}</div>
    </div>
  );
}
