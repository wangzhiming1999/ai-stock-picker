export type ScanViewAction = "show-view" | "run-default";

/** 所有扫描视图；只有 quick 会在首次进入时自动跑默认策略 */
export type ScanView = "quick" | "timing" | "monitor" | "tactics" | "advanced";

export function getScanViewAction(
  view: ScanView,
  hasResults: boolean,
  isRunning: boolean
): ScanViewAction {
  return view === "quick" && !hasResults && !isRunning ? "run-default" : "show-view";
}
