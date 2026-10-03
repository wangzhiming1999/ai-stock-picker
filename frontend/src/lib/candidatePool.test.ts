import assert from "node:assert/strict";
import test from "node:test";

import { mergeCandidateCodes, normalizeCandidateCodes, parseCandidateCodes } from "./candidatePool.ts";

test("候选池只保留六位股票代码、去重并限制 30 只", () => {
  const input = ["600519", " 000858 ", "600519", "abc", "300750", ...Array.from({ length: 40 }, (_, i) => String(i).padStart(6, "0"))];
  const result = normalizeCandidateCodes(input);

  assert.equal(result.length, 30);
  assert.deepEqual(result.slice(0, 3), ["600519", "000858", "300750"]);
});

test("新选择排在候选池前面，旧候选按原顺序保留", () => {
  assert.deepEqual(mergeCandidateCodes(["600519", "000858"], ["300750", "600519"]), [
    "300750",
    "600519",
    "000858",
  ]);
});

test("手工输入支持空格、逗号和中文逗号", () => {
  assert.deepEqual(parseCandidateCodes("600519, 000858，300750\ninvalid"), ["600519", "000858", "300750"]);
});
