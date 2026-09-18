import assert from "node:assert/strict";
import { test } from "node:test";
import type { LimitDownBucket } from "../types.ts";
import {
  extremeBuckets,
  fmtDownUpRatio,
  tailSummary,
  winRateShortfall,
} from "./limitDownLogic.ts";

test("胜率缺口 = 打平胜率 − 实际胜率", () => {
  // 实测口径：胜率 4.5%、打平需 80.6% → 离成立还差 76.1 个百分点
  assert.equal(winRateShortfall({ n: 133, win_rate_open: 4.5, breakeven_win_rate: 80.6 }), 76.1);
});

test("数据不足时返回 null，不能当成 0", () => {
  // 0 会被读成「已经打平」，而真实含义是「算不出来」
  assert.equal(winRateShortfall({ n: 0 }), null);
  assert.equal(winRateShortfall(undefined), null);
  assert.equal(winRateShortfall({ n: 5, win_rate_open: 10 }), null);
});

test("打平线低于实际胜率时为负缺口", () => {
  assert.equal(winRateShortfall({ n: 30, win_rate_open: 70, breakeven_win_rate: 60 }), -10);
});

test("涨跌停比：缺失显示破折号而不是 0.00", () => {
  assert.equal(fmtDownUpRatio(null), "—");
  assert.equal(fmtDownUpRatio(undefined), "—");
  // 0 是「当天没有跌停」，是有效值，必须与缺失区分
  assert.equal(fmtDownUpRatio(0), "0.00");
  // 用能精确表示的数值断言格式约定：0.235 的浮点值是 0.234999…，
  // 拿它断言等于在测浮点表示而不是在测「保留两位小数」
  assert.equal(fmtDownUpRatio(0.25), "0.25");
  assert.equal(fmtDownUpRatio(1.5), "1.50");
});

test("极值切片：忽略样本量不足的档", () => {
  const buckets: LimitDownBucket[] = [
    { key: "a", label: "样本小但亮眼", n: 3, expect_open: 8 },
    { key: "b", label: "大样本较好", n: 93, expect_open: -4.04 },
    { key: "c", label: "大样本最差", n: 6, expect_open: -7.17 },
  ];
  const { best, worst } = extremeBuckets(buckets, 5);
  // n=3 的那档被排除 —— 否则「+8%」会被读成规律
  assert.equal(best?.key, "b");
  assert.equal(worst?.key, "c");
});

test("极值切片：全部低于门槛时返回 null", () => {
  const { best, worst } = extremeBuckets([{ key: "a", label: "x", n: 2, expect_open: 5 }], 5);
  assert.equal(best, null);
  assert.equal(worst, null);
});

test("极值切片：空输入与缺失输入都不抛", () => {
  assert.deepEqual(extremeBuckets(undefined), { best: null, worst: null });
  assert.deepEqual(extremeBuckets([]), { best: null, worst: null });
});

test("尾部风险描述带样本量，并点明卖不出去的那一档", () => {
  assert.equal(
    tailSummary({ drop9_n: 19, drop9_rate: 14.3, unsellable_n: 3 }, 133),
    "次日跌停开盘 19 / 133 次（14.3%），其中 3 次一字封死、挂单也卖不出去",
  );
});

test("没有卖不出去的样本时不硬凑那句话", () => {
  assert.equal(
    tailSummary({ drop9_n: 19, drop9_rate: 14.3, unsellable_n: 0 }, 133),
    "次日跌停开盘 19 / 133 次（14.3%）",
  );
});

test("尾部风险：无样本时返回 null", () => {
  assert.equal(tailSummary(undefined, 133), null);
  assert.equal(tailSummary({ drop9_n: 0, drop9_rate: 0, unsellable_n: 0 }, 0), null);
});
