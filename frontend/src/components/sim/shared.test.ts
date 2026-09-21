import assert from "node:assert/strict";
import { test } from "node:test";
import { slippageLabel, slippagePct } from "./shared.ts";

/**
 * 执行偏差（预期价格 vs 实际成交价）的纯逻辑测试。
 *
 * 为什么要单独测：这一列由 v13 迁移引入，**迁移没跑时它是 undefined**，
 * 而卖出单永远没有它。三种「没有值」的情况都必须返回 null 而不是 0
 * —— 返回 0 会渲染成「比预期贵 0.00%」，把一个缺失值伪装成一条事实。
 */

// 断言渲染文案而不是浮点原值：12.4 与 12.3 都存不下精确二进制，
// 用 === 比 (0.1/12.3)*100 会在最后一个 ulp 上随机失败（测的是浮点表示，不是逻辑）。
test("成交价高于计划价 → 判为买贵", () => {
  const pct = slippagePct({ price: 12.4, expected_price: 12.3 });
  assert.ok(pct !== null && pct > 0);
  assert.equal(slippageLabel(pct), "成交比预期贵 0.81%");
});

test("成交价低于计划价 → 判为买便宜", () => {
  const pct = slippagePct({ price: 12.2, expected_price: 12.3 });
  assert.ok(pct !== null && pct < 0);
  assert.equal(slippageLabel(pct), "成交比预期便宜 0.81%");
});

test("成交价等于计划价 → 0，且文案说「贵」（不是「便宜」）", () => {
  assert.equal(slippagePct({ price: 12.3, expected_price: 12.3 }), 0);
  assert.match(slippageLabel(0), /贵 0\.00%/);
});

test("预期价格缺失一律返回 null（迁移未执行 / 卖出单）", () => {
  assert.equal(slippagePct({ price: 12.3 }), null);
  assert.equal(slippagePct({ price: 12.3, expected_price: null }), null);
  assert.equal(slippagePct({ price: 12.3, expected_price: undefined }), null);
});

test("计划价为 0 或非法值时返回 null，不做除零", () => {
  assert.equal(slippagePct({ price: 12.3, expected_price: 0 }), null);
  assert.equal(slippagePct({ price: 12.3, expected_price: -1 }), null);
  assert.equal(slippagePct({ price: 12.3, expected_price: Number.NaN }), null);
  assert.equal(slippagePct({ price: Number.NaN, expected_price: 12.3 }), null);
});

test("文案用「贵/便宜」而不是红绿：滑点是执行成本，不是价格方向", () => {
  assert.equal(slippageLabel(0.8), "成交比预期贵 0.80%");
  assert.equal(slippageLabel(-0.8), "成交比预期便宜 0.80%");
  assert.equal(slippageLabel(1.234), "成交比预期贵 1.23%");
});
