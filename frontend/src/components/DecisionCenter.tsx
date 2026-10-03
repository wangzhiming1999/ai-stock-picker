import { Suspense } from "react";
import { lazyRetry } from "../lib/lazyRetry";
import { STACK } from "../lib/ui";
import RecommendPanel from "./RecommendPanel";
import PanelSkeleton from "./ui/PanelSkeleton";

const VanguardPanel = lazyRetry(() => import("./VanguardPanel"));

interface Props {
  onPick: (codes: string[]) => void;
}

/** Recommendation first, then live money/trend confirmation and execution levels. */
export default function DecisionCenter({ onPick }: Props) {
  return (
    <div className={STACK}>
      <RecommendPanel onPick={onPick} />
      <Suspense fallback={<PanelSkeleton label="正在加载资金与趋势确认" />}>
        <VanguardPanel onPick={onPick} />
      </Suspense>
    </div>
  );
}
