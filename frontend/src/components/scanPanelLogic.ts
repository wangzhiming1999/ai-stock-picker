export type ScanViewAction = "show-view" | "run-default";

/**
 * 所有扫描视图；只有 quick 会在首次进入时自动跑默认策略。
 *
 * 注：原 monitor（盯盘）视图已提升到「今日作战」页作为主视图，
 * 不再属于选股扫描的范畴——盯盘是「现在怎么办」，不是「选哪只票」。
 */
export type ScanView = "quick" | "timing" | "tactics" | "advanced";

export function getScanViewAction(
  view: ScanView,
  hasResults: boolean,
  isRunning: boolean
): ScanViewAction {
  return view === "quick" && !hasResults && !isRunning ? "run-default" : "show-view";
}
