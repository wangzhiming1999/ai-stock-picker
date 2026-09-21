import assert from "node:assert/strict";
import { test } from "node:test";
import type { LimitUpFocus, LimitUpFocusRow, LimitUpLadderGroup } from "../types.ts";
import { adviceBadgeText, focusCount, ladderGaps } from "./limitUpLogic.ts";

function focusRow(code: string): LimitUpFocusRow {
  return {
    code,
    name: `股${code}`,
    boards: 2,
    sector: "半导体",
    price: 12,
    expected_price: 12,
    expected_price_basis: "limit_up_price",
    expected_price_note: "",
    next_limit_price: 13.2,
    limit_pct: 10,
    turnover: 8,
    seal_ratio: 3,
    seal_time: "09:31:00",
    break_count: 0,
    seal_fund_yi: 2,
    expect_pct: 1.56,
    tier: 1,
    tier_label: "资金面最强",
    rate: 54,
    rate_n: 50,
    basis: [],
  };
}

function focus(relay: string[], first: string[]): LimitUpFocus {
  return {
    relay: relay.map(focusRow),
    first: first.map(focusRow),
    rejected: {},
    rejected_labels: {},
    cut: 0,
    total: relay.length + first.length,
    note: "",
  };
}

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

test("候选数 = 连板 + 首板（只用于计数，两组的率不可比）", () => {
  assert.equal(focusCount(focus(["600001", "600002"], ["600003"])), 3);
  assert.equal(focusCount(focus([], [])), 0);
  assert.equal(focusCount(null), 0);
  assert.equal(focusCount(undefined), 0);
});

test("可打板档的徽标带上候选数（用户反馈的「没说打板什么」）", () => {
  assert.equal(
    adviceBadgeText({ level: "hunt", title: "可打板", focus: focus(["600001"], ["600002"]) }),
    "今日建议：可打板 · 候选 2 只",
  );
});

test("可打板但没筛出标的时徽标要说清楚，不是默默少一个数", () => {
  assert.equal(
    adviceBadgeText({ level: "hunt", title: "可打板", focus: focus([], []) }),
    "今日建议：可打板 · 无可执行标的",
  );
});

test("非 hunt 档不报候选数（那两档不给清单，报数会让人以为被藏起来）", () => {
  assert.equal(adviceBadgeText({ level: "watch", title: "只看不动手" }), "今日建议：只看不动手");
  assert.equal(
    adviceBadgeText({ level: "avoid", title: "空仓等待", focus: null }),
    "今日建议：空仓等待",
  );
});

test("旧后端缺 focus 字段时不抛异常（滚动发布期必须降级）", () => {
  assert.equal(adviceBadgeText({ level: "hunt", title: "可打板" }), "今日建议：可打板 · 无可执行标的");
});
