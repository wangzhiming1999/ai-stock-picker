import assert from "node:assert/strict";
import test from "node:test";

import { autoCandidateEmptyMessage } from "./sandu.ts";

test("资金流源不可用时展示后端故障原因，而不是误报全部被过滤", () => {
  const message = autoCandidateEmptyMessage({
    source: "unavailable",
    count: 0,
    candidates: [],
    notice: "资金流数据源暂不可用：RuntimeError",
  });

  assert.equal(message, "资金流数据源暂不可用：RuntimeError");
});

test("数据源正常但候选为空时才显示过滤结果", () => {
  const message = autoCandidateEmptyMessage({
    source: "fund_flow_main_net",
    count: 0,
    candidates: [],
  });

  assert.match(message, /全部被过滤/);
});
