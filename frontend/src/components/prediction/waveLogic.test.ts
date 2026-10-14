import assert from "node:assert/strict";
import { test } from "node:test";
import type { WaveAnalysis, WaveLevel, WaveRule } from "../../types.ts";
import {
  LOW_CONFIDENCE,
  clampMarksToDates,
  confidencePct,
  failedRequiredRules,
  failedRules,
  failedSoftRules,
  hasWave,
  isInProgress,
  rulesPassed,
  targetTexts,
  waveChips,
  waveMarkTooltip,
  waveMarks,
} from "./waveLogic.ts";

function rule(name: string, ok: boolean, opts: Partial<WaveRule> = {}): WaveRule {
  return { name, ok, detail: "", applicable: true, required: true, ...opts };
}

function level(over: Partial<WaveLevel> = {}): WaveLevel {
  return {
    degree: "日线",
    pattern: "impulse",
    position: "5",
    position_cn: "第 5 浪（末段）",
    direction: "down",
    confidence: 0.8,
    bars: 180,
    threshold_pct: 3.4,
    pivots: [],
    waves: [],
    rules: [],
    targets: [],
    parent: null,
    note: "",
    ...over,
  };
}

function analysis(daily: WaveLevel, weekly: WaveLevel): WaveAnalysis {
  return { daily, weekly, note: "" };
}

test("hasWave：两个级别都没浪位时整块不渲染", () => {
  const empty = level({ position: null, position_cn: null });
  assert.equal(hasWave(null), false);
  assert.equal(hasWave(undefined), false);
  assert.equal(hasWave(analysis(empty, empty)), false);
  assert.equal(hasWave(analysis(level(), empty)), true);
  assert.equal(hasWave(analysis(empty, level())), true);
});

test("confidencePct：字段缺失或非法一律回 0，不抛异常", () => {
  assert.equal(confidencePct(level({ confidence: 0.929 })), 93);
  assert.equal(confidencePct(level({ confidence: 0 })), 0);
  assert.equal(confidencePct(level({ confidence: undefined as unknown as number })), 0);
  assert.equal(confidencePct(level({ confidence: Number.NaN })), 0);
  assert.equal(confidencePct(null), 0);
});

test("isInProgress：只看最后一段是否未走完", () => {
  const mk = (prov: boolean) => level({ waves: [{ provisional: prov } as never] });
  assert.equal(isInProgress(mk(true)), true);
  assert.equal(isInProgress(mk(false)), false);
  assert.equal(isInProgress(level({ waves: [] })), false);
  assert.equal(isInProgress(null), false);
});

test("failedRules：不适用（未走完那条）不算未通过，软性规则也要报出来", () => {
  const r = [
    rule("第2浪不破第1浪起点", true),
    rule("第3浪越过第1浪终点", false, { applicable: false }),
    rule("第2/4浪形态交替", false, { required: false }),
  ];
  const failed = failedRules(level({ rules: r }));
  assert.deepEqual(
    failed.map((x) => x.name),
    ["第2/4浪形态交替"],
  );
});

test("必过铁律与软性规则必须分开报：软性不过不该渲染成告警", () => {
  const r = [
    rule("第3浪不是最短", true),
    rule("第4浪不与第1浪重叠", false),
    rule("第2/4浪形态交替", false, { required: false }),
    rule("C浪/A浪长度比在0.618~1.618", false, { required: false }),
  ];
  const lv = level({ rules: r });
  assert.deepEqual(
    failedRequiredRules(lv).map((x) => x.name),
    ["第4浪不与第1浪重叠"],
  );
  assert.deepEqual(
    failedSoftRules(lv).map((x) => x.name),
    ["第2/4浪形态交替", "C浪/A浪长度比在0.618~1.618"],
  );
});

test("rulesPassed：只有「必过且不适用」以外的规则全过才算通过", () => {
  assert.equal(rulesPassed(level({ rules: [rule("a", true), rule("b", false, { required: false })] })), true);
  assert.equal(rulesPassed(level({ rules: [rule("a", true), rule("b", false)] })), false);
  assert.equal(rulesPassed(level({ rules: [rule("a", false, { applicable: false })] })), true);
  assert.equal(rulesPassed(level({ rules: [] })), true);
});

test("LOW_CONFIDENCE 落在「铁律全过」与「有铁律没过」之间", () => {
  // 后端把没过铁律的划分压到 <= 0.30；全过但结构不完整约 0.55~0.7。
  // 阈值必须严格夹在这两段之间，否则要么把猜测当结论、要么把正常读数弱化掉。
  assert.ok(LOW_CONFIDENCE > 0.3);
  assert.ok(LOW_CONFIDENCE < 0.55);
});

test("waveChips / targetTexts / waveMarks：字段齐备时正确映射", () => {
  const lv = level({
    waves: [
      {
        label: "1",
        label_cn: "第 1 浪（推动）",
        from_date: "2026-05-13",
        to_date: "2026-06-08",
        from_price: 4242.57,
        to_price: 3959.34,
        pct: -6.68,
        bars: 18,
        provisional: false,
        current: false,
      },
      {
        label: "5",
        label_cn: "第 5 浪（末段）",
        from_date: "2026-08-18",
        to_date: "2026-10-12",
        from_price: 3990.3,
        to_price: 3797.24,
        pct: -4.84,
        bars: 33,
        provisional: true,
        current: true,
      },
    ],
    targets: [{ label: "5", price: 3707.07, basis: "5 = 第1浪 × 1" }],
  });

  const chips = waveChips(lv);
  assert.equal(chips[0].text, "1 -6.68%");
  assert.equal(chips[1].text, "5 -4.84%");
  assert.equal(chips[1].current, true);
  assert.match(chips[0].hint, /2026-05-13 → 2026-06-08/);

  assert.deepEqual(targetTexts(lv), ["3707.07（5 = 第1浪 × 1）"]);

  // 标注点取每一浪的**终点**（波浪派标准画法：标签落在浪走完的位置）
  assert.deepEqual(waveMarks(lv), [
    { date: "2026-06-08", price: 3959.34, label: "1" },
    { date: "2026-10-12", price: 3797.24, label: "5" },
  ]);
});

test("waveMarks：脏数据（缺日期 / 非数字价）被过滤，不产出坏坐标", () => {
  const lv = level({
    waves: [
      { to_date: "", to_price: 1, label: "1" } as never,
      { to_date: "2026-06-08", to_price: Number.NaN, label: "2" } as never,
      { to_date: "2026-06-22", to_price: 4163.1, label: "3" } as never,
    ],
  });
  assert.deepEqual(waveMarks(lv), [{ date: "2026-06-22", price: 4163.1, label: "3" }]);
});

test("clampMarksToDates：窗口外的坐标必须被丢掉（否则 ECharts 画到轴外）", () => {
  const marks = [
    { date: "2025-11-21", price: 3834.89, label: "c1" },
    { date: "2026-10-12", price: 3797.24, label: "5" },
  ];
  assert.deepEqual(clampMarksToDates(marks, ["2026-09-01", "2026-10-12"]), [
    { date: "2026-10-12", price: 3797.24, label: "5" },
  ]);
  assert.deepEqual(clampMarksToDates(marks, []), []);
});

test("waveMarkTooltip：c1~c5 与 A/B/C 与数字各有读法", () => {
  assert.equal(waveMarkTooltip("c3"), "C 浪第 3 子浪");
  assert.equal(waveMarkTooltip("C"), "C 浪");
  assert.equal(waveMarkTooltip("B"), "B 浪");
  assert.equal(waveMarkTooltip("5"), "第 5 浪");
  assert.equal(waveMarkTooltip(""), "");
});
