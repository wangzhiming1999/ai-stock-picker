import { Suspense } from "react";
import { lazyRetry } from "../lib/lazyRetry";
import { STACK } from "../lib/ui";
import PanelSkeleton from "./ui/PanelSkeleton";

const ScanPanel = lazyRetry(() => import("./ScanPanel"));
const TacticView = lazyRetry(() => import("./TacticView"));
const ChipPanel = lazyRetry(() => import("./ChipPanel"));
const SanduPanel = lazyRetry(() => import("./sandu/SanduPanel"));

interface Props {
  onPick: (codes: string[]) => void;
}

/** One task-oriented home for every way of finding and structurally checking candidates. */
export default function ScanCenter({ onPick }: Props) {
  return (
    <div className={STACK}>
      <Suspense fallback={<PanelSkeleton label="正在加载策略扫描" />}>
        <ScanPanel onPick={onPick} />
      </Suspense>
      <Suspense fallback={<PanelSkeleton label="正在加载K线形态" />}>
        <TacticView onPick={onPick} />
      </Suspense>
      <Suspense fallback={<PanelSkeleton label="正在加载筹码结构" />}>
        <ChipPanel onPick={onPick} />
      </Suspense>
      <Suspense fallback={<PanelSkeleton label="正在加载三度评分" />}>
        <SanduPanel onPick={onPick} />
      </Suspense>
    </div>
  );
}
