import assert from "node:assert/strict";
import { test } from "node:test";
import { confidenceHint, confidenceLabel, confidenceUnknownSource } from "./confidence.ts";

test("LLM 自评与规则分不能被叫成同一个名字", () => {
  assert.equal(confidenceLabel("llm_self_report"), "AI 自评");
  assert.equal(confidenceLabel("rule_score"), "策略分");
  assert.notEqual(confidenceLabel("llm_self_report"), confidenceLabel("rule_score"));
});

test("老数据没有 confidence_source 时不猜来源", () => {
  for (const missing of [undefined, null, "", "unknown_future_value"]) {
    assert.equal(confidenceLabel(missing), "置信");
    assert.equal(confidenceUnknownSource(missing), true);
  }
});

test("已知来源不算缺失", () => {
  assert.equal(confidenceUnknownSource("llm_self_report"), false);
  assert.equal(confidenceUnknownSource("rule_score"), false);
});

test("hint 必须点明「不是胜率预估」—— 否则数字还是会被当成成功概率", () => {
  assert.match(confidenceHint("llm_self_report"), /不是胜率预估/);
  assert.match(confidenceHint("rule_score"), /不是胜率预估/);
});

test("规则分 hint 交代算法来源，LLM hint 交代主观性质", () => {
  assert.match(confidenceHint("rule_score"), /动量/);
  assert.match(confidenceHint("llm_self_report"), /主观/);
});

test("来源缺失时如实说明，不静默返回空串", () => {
  const hint = confidenceHint(undefined);
  assert.ok(hint.length > 0);
  assert.match(hint, /来源未知/);
});
