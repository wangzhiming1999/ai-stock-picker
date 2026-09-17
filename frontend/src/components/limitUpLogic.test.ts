import assert from "node:assert/strict";
import { test } from "node:test";
import type { LimitUpLadderGroup } from "../types.ts";
import { ladderGaps } from "./limitUpLogic.ts";

function group(key: number, count: number): LimitUpLadderGroup {
  return { key, label: `${key}板`, count, items: [] };
}

test("梯队完整时没有断层", () => {
  assert.deepEqual(ladderGaps([group(3, 2), group(2, 4), group(1, 10)]), []);
});

test("缺中间档时报出该档", () => {
  assert.deepEqual(ladderGaps([group(4, 1), group(2, 3), group(1, 10)]), [3]);
});

test("最高档不参与断层判断", () => {
  // 3 板是当前最高档，即使它是孤零零的一只也不该被报成断层
  assert.deepEqual(ladderGaps([group(3, 1), group(1, 10)]), [2]);
  assert.deepEqual(ladderGaps([group(3, 1), group(2, 5), group(1, 10)]), []);
});

test("首板为空时不报断层（首板不是断层语义）", () => {
  assert.deepEqual(ladderGaps([group(2, 3)]), []);
});

test("6板+ 是合并档：8 板与 5 板并存时不误报 6、7 板断层", () => {
  // 分桶 key 封顶为 6，因此 top = 6，只检查 2..5，不会把 6/7 板当成空缺
  assert.deepEqual(ladderGaps([group(6, 2), group(5, 1), group(4, 1), group(3, 1), group(2, 1), group(1, 9)]), []);
});

test("空梯队返回空数组，不抛异常", () => {
  assert.deepEqual(ladderGaps([]), []);
});
