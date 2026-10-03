import { Suspense } from "react";
import { lazyRetry } from "../lib/lazyRetry";
import { STACK } from "../lib/ui";
import SeizeRadarPanel from "./seize/SeizeRadarPanel";
import PanelSkeleton from "./ui/PanelSkeleton";

const LimitUpDownPanel = lazyRetry(() => import("./opportunity/LimitUpDownPanel"));

/** Intraday sealing activity and the broader limit-up/down risk temperature in one flow. */
export default function MarketCenter() {
  return (
    <div className={STACK}>
      <SeizeRadarPanel />
      <Suspense fallback={<PanelSkeleton label="正在加载涨跌停温度" />}>
        <LimitUpDownPanel />
      </Suspense>
    </div>
  );
}
