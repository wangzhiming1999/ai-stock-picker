import { motion } from "framer-motion";
import type { StockInfo } from "../../types";
import StockCard from "../StockCard";
import { cardItem, stagger } from "../../lib/motion";
import type { AnalysisItem } from "./shared";

interface Props {
  items: AnalysisItem[];
  infos: Record<string, StockInfo>;
  /** 平均分（0 表示还没结果），由宿主算好传进来 */
  avgScore: number;
  /** 评分条总宽归一化分母，由宿主算好传进来 */
  totalScore: number;
}

/**
 * 分析结果区块：平均分条 + 各股 StockCard 网格。
 *
 * 评分条宽度按「单只分 / 总分」占比分配，颜色统一走主色渐变（质量类，不占红绿，
 * 见 lib/tone.ts 的 scoreBg/scoreTone 约定）。卡列表用交错入场动画。
 */
export default function AnalysisResults({ items, infos, avgScore, totalScore }: Props) {
  if (items.length === 0) return null;

  return (
    <div className="mt-6">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-head font-semibold text-white">分析结果</h3>
        <div className="flex items-center gap-2 text-body">
          <span className="text-ink-muted">平均分</span>
          <span className="text-num font-bold text-brand-light tabular-nums">{avgScore.toFixed(1)}</span>
        </div>
      </div>
      <div className="mb-5 flex h-7 w-full overflow-hidden rounded-xl border border-surface-line bg-surface-panel">
        {items.map((item, idx) => (
          <div
            key={item.analysis.code + idx}
            className="flex items-center justify-center overflow-hidden border-r border-surface-panel text-meta font-medium text-white/90 last:border-r-0"
            style={{
              width: `${(Math.max(item.analysis.overall_score, 0) / totalScore) * 100}%`,
              background: "linear-gradient(to top, rgba(37,99,235,0.85), rgba(37,99,235,0.45))",
            }}
            title={`${item.analysis.name} ${item.analysis.overall_score.toFixed(1)}`}
          >
            {item.analysis.name}
          </div>
        ))}
      </div>
      <motion.div
        className="grid gap-5"
        variants={stagger}
        initial="hidden"
        animate="visible"
        key={items.length}
      >
        {items.map((item, idx) => (
          <motion.div key={item.analysis.code + idx} variants={cardItem}>
            <StockCard analysis={item.analysis} info={infos[item.analysis.code]} />
          </motion.div>
        ))}
      </motion.div>
    </div>
  );
}
