/**
 * 配色对比度守卫 · 单一实测来源
 *
 * 为什么需要它：`tailwind.config.js` / `lib/ui.ts` / `lib/tone.ts` 的注释里
 * 写满了「实测 7.23:1」这类数字。数字一旦和代码脱钩就变成假账 ——
 * 别人照着注释做决定，实际早就不成立了。这个脚本把注释里的承诺变成可执行断言。
 *
 * 跑法：`npm run contrast`（CI 也会跑）。
 *
 * 它守六件事：
 *   ① 五档文字色 × 四层表面，全部 >= 4.5:1（WCAG AA 正文）
 *   ② 相邻表面之间相对亮度差 >= 12%（否则「层级看不清」这个历史缺陷会复发）
 *   ③ `line-strong`（交互描边）>= 3:1（WCAG 1.4.11 非文字对比）
 *   ④ 实底按钮上的白字 >= 4.5:1，红绿琥珀在四层表面上 >= 4.5:1
 *   ⑤ 装饰性描边**不该** >= 3:1（反向断言：太抢眼会和交互边界混淆）
 *   ⑥ 文字阶梯相邻两档相对亮度差 >= 12%
 *      —— ① 只保证「每档对背景够亮」，不保证「两档互相能分辨」。
 *         这条是补的：实测 ink-faint(#8fa0b8) 与 ink-muted(#94a3b8)
 *         原本只差 4.4% 亮度，五档名义上存在、实际只有四档可用。
 */
import cfg from "../tailwind.config.js";

/* ── WCAG 相对亮度 / 对比度 ─────────────────────────────────────────── */

const chan = (c) => {
  const v = c / 255;
  return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
};

function luminance(hex) {
  const h = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b);
}

function ratio(a, b) {
  const [la, lb] = [luminance(a), luminance(b)];
  const [hi, lo] = la > lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}

/** 相邻层相对亮度差（%）。历史缺陷是 2~4%，人眼分辨不出。 */
function separation(a, b) {
  const [la, lb] = [luminance(a), luminance(b)];
  return (Math.abs(la - lb) / Math.max(la, lb)) * 100;
}

/* ── 从 tailwind 配置取实测对象（不硬编码，避免两处漂移）───────────── */

const C = cfg.theme.extend.colors;
const SURFACE = {
  canvas: C.surface.canvas,
  panel: C.surface.panel,
  inset: C.surface.inset,
  raised: C.surface.raised,
};
const SURFACE_ORDER = ["canvas", "panel", "inset", "raised"];
const INK = C.ink;

/**
 * 语义色（红涨 / 绿跌 / 琥珀警戒）。定义在 `lib/tone.ts` 的 class 字面量里，
 * 不是 tailwind 配置项 —— 所以这里显式对齐，tone.ts 换档位时同步改这里。
 */
const SEMANTIC = {
  "红 400 / 涨": "#f87171",
  "红 300 / 涨・芯片": "#fca5a5",
  "绿 400 / 跌": "#4ade80",
  "绿 300 / 跌・芯片": "#86efac",
  "琥珀 400 / 警戒": "#fbbf24",
  "琥珀 300 / 警戒・芯片": "#fcd34d",
};

/** 实底按钮填充 → 白字必须可读。 */
const FILL_WITH_WHITE = {
  "brand": C.brand.DEFAULT,
  "brand-dark": C.brand.dark,
  "red-600 / 危险": "#dc2626",
  "amber-700 / 警戒": "#b45309",
};

/* ── 断言 ───────────────────────────────────────────────────────────── */

const AA = 4.5;
const NON_TEXT = 3;
const MIN_SEPARATION = 12;

let failures = 0;

function check(ok, label, detail) {
  if (!ok) failures += 1;
  console.log(`${ok ? "  ok  " : "  FAIL"}  ${label.padEnd(46)} ${detail}`);
}

console.log("\n① 文字色 × 表面阶梯（需 >= 4.5:1）\n");
console.log("          " + SURFACE_ORDER.map((s) => s.padStart(9)).join(""));
for (const [name, hex] of Object.entries(INK)) {
  const cells = SURFACE_ORDER.map((s) => ratio(hex, SURFACE[s]));
  const ok = cells.every((r) => r >= AA);
  failures += ok ? 0 : 1;
  console.log(
    `  ${ok ? "ok  " : "FAIL"}  ink-${name.padEnd(8)} ` +
      cells.map((r) => r.toFixed(2).padStart(9)).join("") +
      `   ${hex}`
  );
}

console.log("\n② 语义色 × 表面阶梯（需 >= 4.5:1，红绿是文字色不是底色）\n");
for (const [name, hex] of Object.entries(SEMANTIC)) {
  const cells = SURFACE_ORDER.map((s) => ratio(hex, SURFACE[s]));
  const ok = cells.every((r) => r >= AA);
  failures += ok ? 0 : 1;
  console.log(
    `  ${ok ? "ok  " : "FAIL"}  ${name.padEnd(18)} ` +
      cells.map((r) => r.toFixed(2).padStart(9)).join("") +
      `   ${hex}`
  );
}

console.log(`\n③ 相邻表面可分度（需 >= ${MIN_SEPARATION}%：低于此值人眼分辨不出层级）\n`);
for (let i = 1; i < SURFACE_ORDER.length; i += 1) {
  const a = SURFACE_ORDER[i - 1];
  const b = SURFACE_ORDER[i];
  const d = separation(SURFACE[a], SURFACE[b]);
  check(d >= MIN_SEPARATION, `${a} → ${b}`, `${d.toFixed(1)}%`);
}

console.log(`\n④ 交互描边 line-strong（需 >= ${NON_TEXT}:1，WCAG 1.4.11）\n`);
for (const s of ["canvas", "panel", "inset", "raised"]) {
  const r = ratio(C.surface["line-strong"], SURFACE[s]);
  check(r >= NON_TEXT, `line-strong on ${s}`, `${r.toFixed(2)}:1`);
}

console.log("\n⑤ 实底按钮上的白字（需 >= 4.5:1）\n");
for (const [name, hex] of Object.entries(FILL_WITH_WHITE)) {
  const r = ratio("#ffffff", hex);
  check(r >= AA, `white on ${name}`, `${r.toFixed(2)}:1  ${hex}`);
}

console.log(`\n⑥ 文字阶梯互相可分度（需 >= ${MIN_SEPARATION}%，与表面阶梯同一条判据）\n`);
console.log("    （① 只保证每档对背景够亮，不保证相邻两档**互相**能分辨 ——\n");
console.log("      2026-09-21 实测 ink-faint 与 ink-muted 只差 4.4%，\n");
console.log("      等于五档实际只有四档可用，这正是「整屏发灰」的成因之一）\n");
{
  /** `ink` 的 key 顺序即档位顺序（strong → faint），DEFAULT 在代码里读作 ink。 */
  const LADDER = ["strong", "DEFAULT", "soft", "muted", "faint"];
  const name = (k) => (k === "DEFAULT" ? "ink" : `ink-${k}`);
  for (let i = 1; i < LADDER.length; i += 1) {
    const a = LADDER[i - 1];
    const b = LADDER[i];
    const d = separation(INK[a], INK[b]);
    check(d >= MIN_SEPARATION, `${name(a)} → ${name(b)}`, `${d.toFixed(1)}%`);
  }
}

console.log("\n⑦ 反向断言：装饰性描边**不该**达到 3:1\n");
console.log("    （达到就说明它太抢眼，会和真正的交互边界混淆）\n");
{
  const r = ratio(C.surface.line, SURFACE.panel);
  check(r < NON_TEXT, `line on panel 保持装饰性`, `${r.toFixed(2)}:1`);
}

console.log(
  failures === 0
    ? "\n✅ 全部通过\n"
    : `\n❌ ${failures} 项不达标 —— 改色值前先读 tailwind.config.js 顶部的分层约定\n`
);
process.exit(failures === 0 ? 0 : 1);
