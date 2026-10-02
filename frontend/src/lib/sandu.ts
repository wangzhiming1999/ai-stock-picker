import type { SanduAutoCandidatesResult } from "../types";

export function autoCandidateEmptyMessage(result: SanduAutoCandidatesResult): string {
  if (result.source === "unavailable") {
    return result.notice || "主力资金流数据源暂不可用，请稍后重试或手动输入代码";
  }
  return "主力净流入榜暂无可选候选（全部被过滤），稍后再试或手动输入代码";
}
