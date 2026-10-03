import { Suspense } from "react";
import { lazyRetry } from "../lib/lazyRetry";
import { STACK } from "../lib/ui";
import { CaliberIncomparabilityNote } from "./CaliberNote";
import EvidenceLedgerPanel from "./EvidenceLedgerPanel";
import DataHealthPanel from "./DataHealthPanel";
import WinratePanel from "./WinratePanel";
import PanelSkeleton from "./ui/PanelSkeleton";

const BacktestPanel = lazyRetry(() => import("./BacktestPanel"));
const TacticBacktestPanel = lazyRetry(() => import("./TacticBacktestPanel"));

/** Evidence level → settled performance → reproducible backtests. */
export default function VerificationCenter() {
  return (
    <div className={STACK}>
      <CaliberIncomparabilityNote />
      <DataHealthPanel />
      <EvidenceLedgerPanel />
      <WinratePanel />
      <Suspense fallback={<PanelSkeleton label="正在加载组合回测" />}>
        <BacktestPanel />
      </Suspense>
      <Suspense fallback={<PanelSkeleton label="正在加载形态回测" />}>
        <TacticBacktestPanel />
      </Suspense>
    </div>
  );
}
