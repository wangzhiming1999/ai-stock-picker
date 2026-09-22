import assert from "node:assert/strict";
import { test } from "node:test";
import {
  DECISION_CHIP,
  DECISION_LABEL,
  DECISION_LONG_LABEL,
  DECISION_ORDER,
  DECISIONS,
  decisionLabel,
  isDecision,
} from "./decision.ts";
import { CHIP } from "./tone.ts";

/**
 * 决策契约守卫。
 *
 * 这套断言的目的是让「动作词只有一个来源」这件事可被机器验证：此前项目里
 * 各模块自己拼「持有观察」「建议减仓」「可关注」，前端只能靠正则猜中文含义
 * （见 tone.ts::actionBadge 的历史实现）。任何让动作词重新分散的改动都应该在这里失败。
 */

test("动作表覆盖 6 态，且每个动作都有文案与配色", () => {
  assert.equal(DECISIONS.length, 6);
  for (const d of DECISIONS) {
    assert.ok(DECISION_LABEL[d], `${d} 缺短标签`);
    assert.ok(DECISION_LONG_LABEL[d], `${d} 缺长标签`);
    assert.ok(DECISION_CHIP[d].bg, `${d} 缺底色`);
    assert.ok(DECISION_CHIP[d].text, `${d} 缺文字色`);
    assert.equal(typeof DECISION_ORDER[d], "number", `${d} 缺优先级`);
  }
});

test("「不参与」是与买卖并列的一等公民，且长文案必须带原因", () => {
  assert.ok(DECISIONS.includes("skip"));
  assert.equal(DECISION_LABEL.skip, "不参与");
  // 长标签若只有「不参与」两个字，它自己就又变成一个没有结论的模糊词
  assert.match(DECISION_LONG_LABEL.skip, /空仓|等待/);
});

test("色值与 tone.ts::CHIP 对齐 —— 改任一边这条会失败", () => {
  assert.deepEqual(DECISION_CHIP.buy, CHIP.buy);
  assert.deepEqual(DECISION_CHIP.add, CHIP.buy);
  assert.deepEqual(DECISION_CHIP.reduce, CHIP.sell);
  assert.deepEqual(DECISION_CHIP.sell, CHIP.sell);
  assert.deepEqual(DECISION_CHIP.hold, CHIP.neutral);
  assert.deepEqual(DECISION_CHIP.skip, CHIP.neutral);
});

test("中性档不得吃方向色：绿=跌，会给「别动」镀上看空的错觉", () => {
  for (const d of ["hold", "skip"] as const) {
    assert.doesNotMatch(DECISION_CHIP[d].text, /green/, `${d} 用了绿色`);
    assert.doesNotMatch(DECISION_CHIP[d].text, /red/, `${d} 用了红色`);
  }
});

test("未知动作降级为「不参与」，不抛异常、也不渲染成买入", () => {
  assert.equal(decisionLabel(null), "不参与");
  assert.equal(decisionLabel(undefined), "不参与");
  assert.equal(decisionLabel("yolo"), "不参与");
  assert.equal(decisionLabel("buy"), "买入");
  assert.equal(decisionLabel("skip", { long: true }), "不参与（空仓等待）");
  assert.equal(isDecision("buy"), true);
  assert.equal(isDecision(" hold"), false);
  assert.equal(isDecision(undefined), false);
});

test("处置优先级：风险处置先于开仓，「不参与」排最后", () => {
  assert.ok(DECISION_ORDER.sell < DECISION_ORDER.reduce);
  assert.ok(DECISION_ORDER.reduce < DECISION_ORDER.buy);
  assert.ok(DECISION_ORDER.add < DECISION_ORDER.hold);
  assert.ok(DECISION_ORDER.hold < DECISION_ORDER.skip);
});
