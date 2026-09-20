export type ScanViewAction = "show-view" | "run-default";

/**
 * 所有扫描视图；只有 quick 会在首次进入时自动跑默认策略。
 *
 * 注：原 monitor（盯盘）视图已提升到「今日作战」作为子页，
 *    原 tactics（实战形态）视图已提升到「选机会」作为并列子页。
 *    两者都不是「选哪只票」这个动作的一部分 —— 盯盘是「现在怎么办」，
 *    形态是「这类 K 线条件今天命中了哪些」。留在这里只会让扫描页越堆越厚。
 */
export type ScanView = "quick" | "timing" | "advanced";

export function getScanViewAction(
  view: ScanView,
  hasResults: boolean,
  isRunning: boolean
): ScanViewAction {
  return view === "quick" && !hasResults && !isRunning ? "run-default" : "show-view";
}
