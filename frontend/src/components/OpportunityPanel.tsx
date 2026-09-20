import { Suspense } from "react";
import { Lightbulb, ScanSearch, Shapes } from "lucide-react";
import { subNavFor } from "../lib/subnav";
import { useSubPage } from "../lib/useSubPage";
import type { NavJump } from "../lib/featureMap";
import { lazyRetry } from "../lib/lazyRetry";
import { STACK } from "../lib/ui";
import PanelSkeleton from "./ui/PanelSkeleton";
import RecommendPanel from "./RecommendPanel";
import SubNav from "./ui/SubNav";
import PageHeader from "./ui/PageHeader";

const ScanPanel = lazyRetry(() => import("./ScanPanel"));
const TacticView = lazyRetry(() => import("./TacticView"));

const SUB_ICON = { recommend: Lightbulb, scan: ScanSearch, tactic: Shapes } as const;
const SUB_KEYS = { recommend: "recommend", scan: "scan", tactic: "tactic" } as const;

interface Props {
  onPick: (codes: string[]) => void;
  /** 从功能地图跳进来的落点 */
  jump?: NavJump | null;
}

/**
 * 选机会 · 「今天买什么」
 *
 * 三个子页是三条互不相同的**票源**：
 *   推荐（模型打分）→ 扫描（策略 / 异动 / 自定义条件）→ 形态（K 线量价条件命中）
 *
 * ## 重构改了两处
 * 1. **「验证」搬走了**（去了「研究」）。它回答的是另一个问题：
 *    这三个子页都在给「今天的票」，验证在给「这套方法可不可信」。
 * 2. **「实战形态」从扫描页里提了出来**。它原本是扫描页的第四个视图 ——
 *    要点进「选机会」→ 再点「扫描」→ 再点「看实战形态」，深度 3 且没有回头路。
 *
 * ⚠️ 本页所有产出都是**候选**，不是指令。子页内的免责说明不要为了排版干净删掉。
 */
export default function OpportunityPanel({ onPick, jump }: Props) {
  const { sub, changeSub, isVisible, isMounted } = useSubPage("opportunity", jump, SUB_KEYS.recommend);
  const items = subNavFor("opportunity").map((s) => ({
    ...s,
    icon: SUB_ICON[s.key as keyof typeof SUB_ICON],
  }));

  return (
    <div className={STACK}>
      <PageHeader
        icon={Lightbulb}
        title="选机会"
        desc="今天买什么：模型推荐、规则扫描、形态命中 —— 三条票源，产出都是候选不是指令"
      />

      <SubNav id="opportunity" items={items} value={sub} onChange={changeSub} />

      {isMounted(SUB_KEYS.recommend) && (
        <div className={isVisible(SUB_KEYS.recommend)}>
          <RecommendPanel onPick={onPick} />
        </div>
      )}

      {isMounted(SUB_KEYS.scan) && (
        <div className={isVisible(SUB_KEYS.scan)}>
          <Suspense fallback={<PanelSkeleton label="正在加载扫描区" />}>
            <ScanPanel onPick={onPick} />
          </Suspense>
        </div>
      )}

      {isMounted(SUB_KEYS.tactic) && (
        <div className={isVisible(SUB_KEYS.tactic)}>
          <Suspense fallback={<PanelSkeleton label="正在加载形态命中" />}>
            <TacticView onPick={onPick} />
          </Suspense>
        </div>
      )}
    </div>
  );
}
