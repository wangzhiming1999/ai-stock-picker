export type ScanViewAction = "show-view" | "run-default";

export function getScanViewAction(
  view: "quick" | "timing" | "monitor" | "advanced",
  hasResults: boolean,
  isRunning: boolean
): ScanViewAction {
  return view === "quick" && !hasResults && !isRunning ? "run-default" : "show-view";
}
