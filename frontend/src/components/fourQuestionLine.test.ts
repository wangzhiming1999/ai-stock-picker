import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import type { FourQuestions } from "../types.ts";

/**
 * 四问守卫的前端守卫。
 *
 * ## 为什么这个文件主要在读源码而不是测函数
 *
 * 四问的**判据**在后端（`calibers.four_questions`），前端只负责渲染。
 * 前端真正可能出错的地方只有一个、但它是致命的：
 *
 * **把「答不上来」渲染成「通过」。**
 *
 * 后端三态分得很清楚（`passed` = true / false / null），但渲染层只要写成
 * `passed ? 通过 : 不通过`，null 就会落进 else 分支变成红色「不通过」——
 * 用户看到的是「已检查、发现失真」，而真实情况是「根本没检查」。
 * 更坏的写法是 `passed !== false`，那 null 会变成绿色「通过」，守卫直接变橡皮章。
 *
 * 这两类错误都不会让页面崩、也不会让 typecheck 报错 —— 只能靠断言源码结构来拦。
 */

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const SRC = readFileSync(join(ROOT, "components/FourQuestionLine.tsx"), "utf8");

test("三态判断必须先看 answered，不能把 null 混进通过或失败分支", () => {
  // `!item.answered` 必须排在最前，且 passed === false 必须是显式比较。
  // 若写成 `item.passed === false` 以外的形式（如 `!item.passed`），
  // null 会被当成 false（红色误报）；若写成 `item.passed`（真值判断），null 会被当成通过。
  assert.match(SRC, /if \(!item\.answered\)/, "必须先判 answered");
  assert.match(SRC, /item\.passed === false/, "必须用显式 === false 判不通过（不能真值判断）");
  assert.doesNotMatch(SRC, /if \(!item\.passed\)/, "禁止 `!item.passed`：会把 null 判成不通过");
  assert.doesNotMatch(SRC, /item\.passed \?/, "禁止真值三元：会把 null 判成通过");
});

test("答不上来必须是独立的第三个分支，且视觉与「通过」不同", () => {
  // 三种 mark：✓ 通过 / × 不通过 / ? 答不上来。少一个就说明有一态被合并了。
  assert.match(SRC, /mark: "✓"/, "缺「通过」的标记");
  assert.match(SRC, /mark: "×"/, "缺「不通过」的标记");
  assert.match(SRC, /mark: "\?"/, "缺「答不上来」的标记 —— 它不能被并进通过或不通过");
  // 答不上来走灰（ink-muted），与通过的 ink-soft 区分开
  assert.match(SRC, /mark: "\?"[\s\S]{0,80}text-ink-muted/, "答不上来应走中性灰档");
});

test("三种 verdict 各有独立文案，不能只靠颜色区分", () => {
  // inflated / unknown 走显式分支；credible 是兜底 return（没有失败项也没有未答项时）。
  for (const verdict of ["inflated", "unknown"]) {
    assert.match(SRC, new RegExp(`verdict === "${verdict}"`), `缺 ${verdict} 分支`);
  }
  // 兜底分支必须明确是 credible，不能是别的值
  assert.match(SRC, /return \{\s*\n\s*title: "四问齐备/, "缺 credible 兜底分支");
  // 每个分支都要有 title 文案 —— 只出色块的话，色弱用户读不出结论
  const titles = SRC.match(/title: "[^"]+"/g) ?? [];
  assert.ok(titles.length >= 3, `结论横幅应至少三处 title 文案，实际 ${titles.length}`);
});

test("四问区不得折叠、不得藏进 tooltip", () => {
  // 这层守卫的存在理由恰恰是「容易被忽略」，折叠即等于没有。
  assert.doesNotMatch(SRC, /Collapsible|<details|onClick|group-hover/, "四问区不得可折叠/可点击");
  assert.doesNotMatch(SRC, /title=\{/, "不要用原生 title tooltip 承载问项内容");
});

test("四个问项固定顺序渲染，且每项都有 detail 文案", () => {
  // 后端已保证顺序，前端按 items 原序渲染即可 —— 但必须要求 detail 非空，
  // 否则会出现一个只有问法、没有结论的空行。
  assert.match(SRC, /four\.items\.map/, "必须按 items 原序渲染");
  assert.match(SRC, /item\.detail/, "每项必须渲染 detail");
  assert.match(SRC, /item\.label/, "每项必须渲染问法");
});

test("计数口径：answered/total 与两个清单都要显示", () => {
  assert.match(SRC, /four\.answered_count/, "缺「几项有交代」");
  assert.match(SRC, /four\.total_questions/, "缺「共几项」");
  assert.match(SRC, /four\.failed_keys/, "缺失真项计数");
  assert.match(SRC, /four\.unanswered_keys/, "缺答不上来项计数");
});

/* ── 接线：WinratePanel 两个块都要渲染 ─────────────────────────────── */

test("胜率看板两个统计块都接了四问", () => {
  const panel = readFileSync(join(ROOT, "components/WinratePanel.tsx"), "utf8");
  assert.match(panel, /data\.prediction\.four_questions/, "大盘命中率块未接四问");
  assert.match(panel, /data\.recommendation\.four_questions/, "推荐胜率块未接四问");
  // 四问必须在口径说明之后 —— 阅读顺序是「数字是什么 → 数字站不站得住」
  const caliberAt = panel.indexOf("<CaliberLine");
  const fourAt = panel.indexOf("<FourQuestionLine");
  assert.ok(caliberAt >= 0 && fourAt > caliberAt, "四问应渲染在口径说明之后");
});

/* ── 表格型口径：每行必须独立判定 ─────────────────────────────────── */

test("形态回测：四问必须逐行渲染，不能只显示第一行", () => {
  const panel = readFileSync(join(ROOT, "components/TacticBacktestPanel.tsx"), "utf8");
  // 每个形态的样本量/分布/符号翻转都不同，只渲染 items[0] 会让
  // 下面所有形态共用同一个结论 —— 这是个很自然、也很容易写出来的错误。
  assert.doesNotMatch(panel, /items\??\.?\[0\]/, "禁止只渲染第一行的四问");
  assert.match(panel, /FourQuestionLine four=\{it\.four_questions\}/, "四问必须绑定当前行");
  // 且必须在行内（明细展开区），而不是面板底部
  const rowAt = panel.search(/FourQuestionLine four=\{it\.four_questions\}/);
  const mapAt = panel.search(/items\.map/);
  assert.ok(rowAt > mapAt, "四问必须在 items.map 的行渲染内");
});

test("连板晋级率：四问常驻渲染（这三问答不上来正是核心信息）", () => {
  const team = readFileSync(join(ROOT, "components/market/LimitUpTeam.tsx"), "utf8");
  assert.match(team, /FourQuestionLine four=\{relay\.four_questions\}/, "晋级率未接四问");
  // 晋级率只有「有 n 吗」答得上，其余三问都是「答不上来」——
  // 这正是本口径的头号陷阱（晋级了也可能买不进），折叠就等于没接。
  assert.doesNotMatch(team, /Collapsible[\s\S]{0,200}relay\.four_questions/, "晋级率四问不得折叠");
});

test("premium 回测类型备好四问字段（端点手动触发，未接轮询）", () => {
  const types = readFileSync(join(ROOT, "types.ts"), "utf8");
  assert.match(types, /interface LimitUpPremiumBacktestResult/);
  // 可成交那一问恒为 100%（只取换手≥5%），但字段语义要写清是「已筛过」而非「已验证」
  assert.match(types, /样本内可成交比例恒为 100%/);
  assert.match(types, /median_excess_pct\?/);
});

test("premium 回测端点不得被顺手加进常规轮询", () => {
  // 该端点 force=true 会真实打行情源（逐只日 K），是风控主因。
  const client = readFileSync(join(ROOT, "api/client.ts"), "utf8");
  const hasPolling = /premium-backtest/.test(client);
  if (hasPolling) {
    // 若确实接了客户端，必须带显式 force 开关且默认不带
    assert.match(client, /premiumBacktest[\s\S]{0,200}force/, "接线时必须显式暴露 force 开关");
  }
});

/* ── 第二批接线 ───────────────────────────────────────────────────── */

test("策略回测：四问 + 对比基准超额，且两者不混淆", () => {
  const panel = readFileSync(join(ROOT, "components/BacktestPanel.tsx"), "utf8");
  assert.match(panel, /FourQuestionLine four=\{result\.four_questions\}/, "策略回测未接四问");
  // vs_benchmark 必须单独渲染，且文案点明「超额不是符号稳定性」
  assert.match(panel, /vs_benchmark/, "未渲染对比基准超额");
  assert.match(panel, /超额不是符号稳定性/, "必须点明超额 ≠ 符号稳定性（本口径只有一条基准线）");
});

test("策略回测类型：n 单位是调仓期，vs_benchmark 可空", () => {
  const types = readFileSync(join(ROOT, "types.ts"), "utf8");
  assert.match(types, /n 单位是\*\*调仓期\*\*（`periods`），不是股票池/);
  assert.match(types, /vs_benchmark\?:/);
  // 基准取数失败时必须为 null，不能退化成 0（0 会被读成「打平」）
  assert.match(types, /vs_benchmark\?: \{[\s\S]{0,200}\} \| null/);
});

test("跌停修复：四问只挂全体口径，不逐档铺开", () => {
  const panel = readFileSync(join(ROOT, "components/market/LimitDownRepair.tsx"), "utf8");
  assert.match(panel, /FourQuestionLine four=\{o\.four_questions\}/, "未挂全体口径的四问");
  // BucketRow 是逐档渲染；四问若放进 BucketRow 会变成一屏「样本不足」，
  // 把真正的结论淹掉
  const rowBody = panel.slice(panel.indexOf("function BucketRow"), panel.indexOf("function RepairSection"));
  assert.doesNotMatch(rowBody, /FourQuestionLine/, "四问不得放进逐档的 BucketRow");
});

test("Agent 决策：只渲染采纳组四问（对照组会诱导相减）", () => {
  const sec = readFileSync(join(ROOT, "components/sim/AgentDecisionsSection.tsx"), "utf8");
  assert.match(sec, /FourQuestionLine four=\{stats\.adopted\.four_questions\}/);
  // 两个命中率并排时读者会本能相减，而采纳与否是用户自己选的 —— 不是随机对照。
  // 把对照组的四问也渲染出来会让「对照」字样出现在旁边，反而加强相减暗示。
  assert.doesNotMatch(sec, /FourQuestionLine four=\{stats\.ignored_control/, "不得渲染对照组四问");
});

test("agent_plan 类型标注对照组不可相减", () => {
  const types = readFileSync(join(ROOT, "types.ts"), "utf8");
  const at = types.indexOf("ignored_control:");
  assert.ok(at >= 0, "未找到 ignored_control 字段");
  // 注释就在字段声明前 200 字内（不要用跨整个文件的匹配，那会误命中别的类型）
  const before = types.slice(Math.max(0, at - 220), at);
  assert.match(before, /不可与 adopted 直接相减/, "对照组字段缺少「不可相减」标注");
});

test("seize 两个回测类型：期望符号相反，必须标注不可混读", () => {
  const types = readFileSync(join(ROOT, "types.ts"), "utf8");
  assert.match(types, /两者\*\*期望符号相反\*\*，不可混读、不可相加/);
  // n 用 settled 不用 n（含未结算行会虚高）
  assert.match(types, /四问的 n 用它，不用 n（含未结算行会虚高）/);
});

/* ── 覆盖率提示（2026-10-17 线上实测后加）───────────────────────── */

test("执行追踪覆盖率必须显式渲染，否则「可成交 100%」会掩盖「只有 1 个样本」", () => {
  const panel = readFileSync(join(ROOT, "components/WinratePanel.tsx"), "utf8");
  assert.match(panel, /execution_tracked_ratio/, "未渲染执行追踪覆盖率");
  assert.match(panel, /legacy_without_execution_tracking/, "未说明迁移前历史行数量");
  // 阈值：低于 80% 就要提示（线上实测只有 4%）
  assert.match(panel, /execution_tracked_ratio < 80/, "缺少覆盖率阈值判断");
});

test("覆盖率字段的类型注释点明它比可成交比例更该先看", () => {
  const types = readFileSync(join(ROOT, "types.ts"), "utf8");
  assert.match(types, /这个数比可成交比例更该先看/);
  assert.match(types, /legacy_without_execution_tracking/, "缺 legacy 行数字段");
});

test("四问是可选字段，缺失时组件返回 null 而不是崩", () => {
  // 四问是后端新增字段；老缓存 / 降级响应里可能没有它。
  // 渲染层必须能容 null，否则一次后端降级会让整个胜率面板白屏。
  assert.match(SRC, /if \(!four \|\| !Array\.isArray/, "必须先容错再渲染");
  assert.match(SRC, /return null/, "缺失四问时应静默不渲染");
});

/* ── 类型契约 ─────────────────────────────────────────────────────── */

test("FourQuestions 类型把 verdict 与 passed 的取值域锁死", () => {
  const types = readFileSync(join(ROOT, "types.ts"), "utf8");
  assert.match(types, /verdict: "credible" \| "inflated" \| "unknown"/);
  // passed 必须是 boolean | null，三态在类型层可见
  assert.match(types, /passed: boolean \| null/);
  assert.match(types, /answered: boolean/);
});

test("组件体内：字段读取排在空值守卫之后，且禁止非空断言", () => {
  // 只看组件函数体（从 export function FourQuestionLine 起）——
  // verdictBanner 是定义在它上方的纯辅助函数，源码位置靠前但运行时在守卫后才被调用。
  const bodyAt = SRC.search(/export function FourQuestionLine/);
  assert.ok(bodyAt >= 0, "组件入口未找到");
  const body = SRC.slice(bodyAt);

  const guardAt = body.search(/if \(!four \|\| !Array\.isArray/);
  const readAt = body.search(/four\.(items|answered_count|verdict|failed_keys|unanswered_keys)/);
  assert.ok(guardAt >= 0, "组件体内缺空值守卫");
  assert.ok(readAt > guardAt, "四问字段的读取必须排在空值守卫之后");
  assert.doesNotMatch(SRC, /four!\./, "禁止非空断言");
});
