import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

/**
 * 设计规范守卫 · 四组 token 不得被绕过
 *
 * ## 为什么需要这个测试
 * 这个项目此前**有**设计规范：`lib/ui.ts` 里写清了四层表面阶梯、五档字色、
 * WCAG 实测对比度。但它导出的全是**字符串常量**，靠每个作者记得用。
 * 实测结果是有漏的：
 *   · `CollapsiblePanel` 手写 `border-slate-800 bg-slate-900`（绕开 CARD_FLUSH）
 *   · `TapeShell` 手写 `border-slate-800/80 bg-slate-900/60` + 自带 `max-w-6xl`
 *     与页面的 `max-w-[1360px]` 相差 208px，温度带与正文左边界肉眼可见对不齐
 *   · 81 处把**填充色**当描边（`border-surface-inset`，在面板底上只有 1.09:1），
 *     等于卡片没有边框 —— 而 `<Panel>` 用的是 1.62:1 的 surface-line
 * 每一条单看都"差不多"，叠起来就是「界面像几个人拼的」。
 *
 * 结论：**规范必须能被机器检查，否则它只是注释。**
 * 2026-09-21 起全站已完成 token 化，所以本测试扫的是**整个 src/**，
 * 不再只扫已迁移目录 —— 「迁移完成」这件事本身也要有机械判据。
 *
 * ## 反例（历史上真实踩过，不要"修"掉这些断言）
 *   · 裸字号档位（`text-xs` / `text-sm` / `text-[13px]`）：2026-09-21 之前全站
 *     557 处 text-xs、183 处 text-sm，即八成文字是同一个 12px，且 0 处行高 ——
 *     一屏之内所有字一样大 + 中文行高过紧，这就是"界面很一般"的机械原因。
 *     现已在 tailwind.config.js 里把裸档位**移除出 theme**：写了不再生成 CSS，
 *     静默继承父级字号，肉眼几乎看不出，只有本测试能发现。
 *   · 写死表面色号：表面阶梯重定向过一次（slate-900 从 #0f172a 改成 #0d1424），
 *     写死色号的地方会在下次调色时静默漏改。
 *   · `border-surface-inset`：把填充色当描边用，视觉上等于无边框。
 */

/**
 * ⚠️ 必须用 `fileURLToPath` 而不是 `new URL(...).pathname`。
 *
 * 在 Windows 上后者会给出 `/D:/felo/...` 这种带前导斜杠的路径，`join()` 之后
 * 既不是合法盘符路径也不是有效相对路径 —— `readdirSync` 抛错，被下面的
 * try/catch 吞掉，于是**扫描到 0 个文件、断言全部空跑通过**。
 * 这正是这个测试要防的那类失效：守卫生效与否本身没有被守卫。
 * 所以下面专门有一条断言 files.length，就是用来钉死这种情况的。
 */
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");

const SCAN_ROOT = join(ROOT, "src");

/** 允许出现违规写法的地方 —— 每个都要有理由，不要靠改松断言解决。 */
const ALLOWLIST = new Map<string, string>([
  // 允许「写死字号」：无。字号阶梯是硬约束。
]);

/**
 * 允许「手写 table」的文件 —— 它天然是唯一合法的实现点。
 */
const TABLE_IMPL = new Set(["src/components/ui/Table.tsx"]);

/**
 * 卡片外观的**定义处** —— 这些文件里出现卡片类名是它们存在的理由。
 *   lib/ui.ts 里是 `CARD` / `CARD_FLUSH` / `CARD_MODAL` 三个常量本身。
 */
const CARD_DEFINITION = new Set(["src/lib/ui.ts"]);

/**
 * 允许「填充色当描边」的文件。
 *   AnalysisResults 的涨跌分布条：每段是实色填充，段间用 **面板底色** 画分隔线，
 *   借底色差造出"缝隙"。这里 border-surface-panel 是刻意的，不是笔误。
 */
const FILL_AS_BORDER_OK = new Set(["src/components/analysis/AnalysisResults.tsx"]);

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.tsx?$/.test(p) && !/\.test\.tsx?$/.test(p)) out.push(p);
  }
  return out;
}

/** 去掉注释行 —— 注释里引用反例是正当的（比如本文件与各组件顶部的说明）。 */
function stripComments(src: string): string {
  return src
    .split("\n")
    .filter((l) => {
      const t = l.trim();
      return !t.startsWith("//") && !t.startsWith("*") && !t.startsWith("/*");
    })
    .join("\n");
}

/** 逐行扫描，返回 `${rel}:${line}  ${片段}` 形式的违规清单。 */
function scan(bad: RegExp, opts: { skip?: Set<string> } = {}): string[] {
  const offenders: string[] = [];
  for (const abs of files) {
    const rel = relative(ROOT, abs).replace(/\\/g, "/");
    if (ALLOWLIST.has(rel) || opts.skip?.has(rel)) continue;
    const src = stripComments(readFileSync(abs, "utf8"));
    src.split("\n").forEach((line, i) => {
      // 重置 lastIndex：带 /g 的正则复用时会从上一次位置继续
      bad.lastIndex = 0;
      if (bad.test(line)) offenders.push(`${rel}:${i + 1}  ${line.trim().slice(0, 110)}`);
    });
  }
  return offenders;
}

let files: string[] = [];
try {
  files = walk(SCAN_ROOT);
} catch {
  files = [];
}

test("全站至少被扫到（防止路径写错导致空跑）", () => {
  // 2026-09-21 实测 141 个源文件。取 100 作为下限：既能挡住"扫到 0 个"，
  // 又不会因为正常的文件增删而误报。
  assert.ok(files.length >= 100, `只扫到 ${files.length} 个文件，SCAN_ROOT 可能配错了`);
});

/* ── ① 字号 ────────────────────────────────────────────────────────────
 * 只认 tailwind.config.js 的 fontSize 阶梯：
 *   micro 10 / meta 12 / label 12 / body 14 / head 16 / num 18 / h1 20 / hero 24 / display 32
 * 裸档位已从 theme 移除，写了不生成 CSS → 静默继承父级字号，只能靠本测试发现。
 */
test("字号必须来自语义阶梯（禁止 text-xs / text-sm / text-[13px] 等裸档位）", () => {
  const BAD = /\btext-(?:xs|sm|base|lg|xl|2xl|3xl|4xl|5xl)\b|\btext-\[[0-9]+(?:\.[0-9]+)?(?:px|rem)\]/g;
  const offenders = scan(BAD);
  assert.deepEqual(
    offenders,
    [],
    `请用语义档位 text-micro / text-meta / text-label / text-body / text-head / text-num / text-h1 / text-hero / text-display：\n${offenders.join("\n")}`,
  );
});

/* ── ② 圆角 ────────────────────────────────────────────────────────────
 * 五档：md 6（徽章 · chip）/ lg 8（按钮 · 输入框）/ xl 12（面板内分区）/
 *       2xl 16（页面级面板）/ full（胶囊）
 * 裸 `rounded`(4px) 与 rounded-md(6px) 是同一个语义位，同一屏里两种小圆角
 * 摆在一起肉眼可见不齐。
 */
test("圆角必须来自五档（禁止裸 rounded / rounded-sm / rounded-[Npx]）", () => {
  const BAD = /\brounded(?!-?(?:md|lg|xl|2xl|full)\b)|rounded-\[[^\]]+\]/g;
  const offenders = scan(BAD);
  assert.deepEqual(
    offenders,
    [],
    `请用 rounded-md / rounded-lg / rounded-xl / rounded-2xl / rounded-full：\n${offenders.join("\n")}`,
  );
});

/* ── ③ 字色与表面色 ────────────────────────────────────────────────────
 * 文字色一律 ink-*（五档，全部在四层表面上实测 >= 4.5:1）。
 * 表面色一律 surface-*（四层阶梯 + 三分描边）。
 */
test("禁止把 slate 色号当作表面色（700/800/900/950 已被重定向到表面阶梯）", () => {
  const BAD = /\b(?:bg|border|from|to|via)-slate-(?:700|800|900|950)\b/g;
  const offenders = scan(BAD);
  assert.deepEqual(
    offenders,
    [],
    `请用 surface-canvas / surface-panel / surface-inset / surface-line / surface-line-soft / surface-line-strong：\n${offenders.join("\n")}`,
  );
});

test("禁止 text-slate-* 当文字色（实测 slate-500/600 只有 3.07 / 1.93:1）", () => {
  const BAD = /\btext-slate-[0-9]+\b/g;
  const offenders = scan(BAD);
  assert.deepEqual(
    offenders,
    [],
    `文字色请用 ink-strong / ink / ink-soft / ink-muted / ink-faint：\n${offenders.join("\n")}`,
  );
});

/* ── ③b 字色的用量分布 ─────────────────────────────────────────────────
 * token 存在不代表用得对。2026-09-21 之前 `ink-faint`（最弱档）用了 375 处、
 * `ink-soft`（正文档）只有 141 处 —— 正文、读数、字段名全挤在最弱一档，
 * 一屏看下来就是「整屏发灰」。当时**没有任何一条断言能发现这件事**，
 * 因为每处写法单独看都合法。所以这里守的是**分布**，不是写法。
 *
 * 判据：faint 必须保持在 soft 的一半以下（实测 69 : 253）。
 * 这不是审美偏好 —— faint 的设计语义是「可以完全忽略也不影响判断」，
 * 一屏里「可以忽略」的东西比正文还多，说明档位用错了。
 *
 * 分流纪律见 lib/ui.ts 的「四类内容的分界」。
 */
test("ink-faint 必须保持少数档（用量 < ink-soft 的一半）", () => {
  const count = (token: string) => {
    // 用 String.match + /g（无 lastIndex 状态），不要复用带 /g 的 RegExp.test
    const re = new RegExp(`\\b${token}\\b`, "g");
    let n = 0;
    for (const abs of files) {
      n += (stripComments(readFileSync(abs, "utf8")).match(re) ?? []).length;
    }
    return n;
  };
  const faint = count("ink-faint");
  const soft = count("ink-soft");
  assert.ok(
    faint * 2 <= soft,
    `ink-faint 用了 ${faint} 处、ink-soft 只有 ${soft} 处 —— faint 已不是少数档。\n` +
      `请按 lib/ui.ts 的「四类内容的分界」重判：正文/读数/空态 → ink-soft，` +
      `字段名/表头/统计标签/代码/名次/单位 → ink-muted，只有口径/免责/时间戳/装饰留在 ink-faint。`,
  );
});

/* ── ④ 边距：填充色不得当描边 ──────────────────────────────────────────
 * 这是 2026-09-21 找到的最隐蔽的一处：`border-surface-inset` 用了**填充色**，
 * 在面板底 #0d1424 上只有 1.09:1 —— 等于卡片没有边框，是"界面没有落点"的
 * 主要原因之一。而且当时 `<Panel>` 用的是 1.62:1 的 surface-line，
 * 于是两套卡片长得不一样。
 */
test("描边不得使用填充色（border-surface-canvas / inset / panel / raised）", () => {
  const BAD = /\bborder-surface-(?:canvas|inset|raised)\b/g;
  const offenders = scan(BAD, { skip: FILL_AS_BORDER_OK });
  assert.deepEqual(
    offenders,
    [],
    `描边请用 surface-line（装饰性外框）/ surface-line-soft（表内分隔线）/ surface-line-strong（交互元素，需 >= 3:1）：\n${offenders.join("\n")}`,
  );
});

/* ── ④ 边距 ────────────────────────────────────────────────────────────
 * 实测全站 0 处任意间距值，这条守卫是用来**锁住这个性质**的。
 * 边距的语义槽位（CELL / PANEL_* / CARD_* / STACK*）定义在 lib/ui.ts，
 * 不在这里逐值管 —— 「所有卡片都是 p-5」这种全局替换会同时改掉弹窗与常驻条。
 *
 * 只查**间距类**的任意值：`max-w-[1360px]` / `max-h-[560px]` / `h-[calc(...)]`
 * 是尺寸约束，不属于节奏，不在此列。
 */
test("间距不得使用任意值（p-[13px] / gap-[7px] / space-y-[9px] 等）", () => {
  /**
   * ⚠️ 必须带负向后视 `(?<![\w-])`。
   * 用 `\b` 是错的：`-` 是非单词字符，于是 `scroll-mt-[calc(...)]` 里的
   * `mt-[...]` 会被当成独立前缀命中 —— 而 `scroll-mt` 是**锚点偏移**，
   * 与垂直节奏无关。（本条误报就是这个守卫自己抓出来的。）
   */
  const BAD =
    /(?<![\w-])(?:m|mx|my|mt|mb|ml|mr|p|px|py|pt|pb|pl|pr|gap|gap-x|gap-y|space-x|space-y)-\[[^\]]+\]/g;
  const offenders = scan(BAD);
  assert.deepEqual(
    offenders,
    [],
    `间距请用 Tailwind 的 scale（1 = 4px）；语义槽位见 lib/ui.ts 的 CELL / PANEL_* / CARD_* / STACK*：\n${offenders.join("\n")}`,
  );
});

/* ── ⑤ 卡片组合 ────────────────────────────────────────────────────────
 * 判据不是「手写卡片一律禁止」（弹窗、分段条等确有不同形状），而是
 * **不得在同一个 className 里同时手拼 border + bg 的表面色** ——
 * 那正是上一版「12+ 种卡片写法」的来源。
 */
test("不得手拼「圆角 + 描边 + 底色」的完整卡片组合（请用 <Panel> / CARD_* / panelShellVariants）", () => {
  const offenders: string[] = [];
  for (const abs of files) {
    const rel = relative(ROOT, abs).replace(/\\/g, "/");
    if (ALLOWLIST.has(rel) || CARD_DEFINITION.has(rel)) continue;
    // 面板与表格外壳天然是这些类名唯一合法的落点
    if (/components\/ui\/(Panel|CollapsiblePanel|Table|PanelSkeleton)\.tsx$/.test(rel)) continue;
    const src = stripComments(readFileSync(abs, "utf8"));
    src.split("\n").forEach((line, i) => {
      const hasCard =
        line.includes("rounded-2xl") &&
        /border-surface-(?:line|line-soft|line-strong)\b/.test(line) &&
        /bg-surface-(?:panel|canvas)\b/.test(line);
      if (hasCard) offenders.push(`${rel}:${i + 1}  ${line.trim().slice(0, 110)}`);
    });
  }
  assert.deepEqual(
    offenders,
    [],
    `卡片外观应该在 <Panel> / CARD_* / panelShellVariants 里定义一次：\n${offenders.join("\n")}`,
  );
});

/* ── ⑥ 表格外壳 ────────────────────────────────────────────────────────
 * `ui/Table.tsx` 是**唯一**允许出现 `<table>` 的地方。
 *
 * ⚠️ 这条断言被改过，改的原因值得记下来：
 *    旧判据是「`<table` 后 6 行内出现 `sticky`」—— 只认「手写表头且吸顶」的写法。
 *    结果 2026-09-21 收编 11 张表之后，又翻出 5 张**根本没写 sticky** 的表
 *    （HistoryPanel / PortfolioPanel / WatchlistPanel / PositionsTable /
 *    TacticBacktestPanel）。它们既没有吸顶表头，也不在豁免清单里 ——
 *    守卫对它们**完全静默**：判据选窄了，等于给「漏网」留了正好一条缝。
 *
 *    现在的判据是「除了实现文件，任何地方都不许出现 `<table`」——
 *    它不关心表头有没有吸顶，只关心「外壳是不是被复制了」。
 *    这也说明一件事：**豁免清单（TABLE_MIGRATION_PENDING）是债，不是资产** ——
 *    清单存在期间，守卫只对清单外的文件生效；清单清空的那一刻，判据才真正闭环。
 */
test("不得手写 <table>（唯一实现点是 ui/Table.tsx）", () => {
  const offenders: string[] = [];
  for (const abs of files) {
    const rel = relative(ROOT, abs).replace(/\\/g, "/");
    if (TABLE_IMPL.has(rel) || ALLOWLIST.has(rel)) continue;
    stripComments(readFileSync(abs, "utf8"))
      .split("\n")
      .forEach((line, i) => {
        if (/<table\b/.test(line)) offenders.push(`${rel}:${i + 1}  ${line.trim().slice(0, 90)}`);
      });
  }
  assert.deepEqual(
    offenders,
    [],
    `表格外壳请用 <Table>（它负责 sticky 表头、表头底色、圆角描边、滚动高度、minWidth）：\n${offenders.join("\n")}`,
  );
});

/**
 * 允许 `<td>` 使用非 CELL 内边距的文件。
 *   BoardTable 的展开详情行（`<td colSpan>` 里塞了一整块嵌套内容）刻意用 py-3
 *   留出呼吸，那不是"数据格"，所以不受表格节奏约束。
 */
const TD_PADDING_OK = new Set(["src/components/vanguard/BoardTable.tsx"]);

/**
 * `<td>` 内边距必须走 CELL。
 *
 * `lib/ui.ts` 的 CELL 注释里记过这件事：此前 td 混用 `px-2 py-2` 与
 * `px-3 py-1.5` 两套节奏，同一行里有的格子宽一点、有的高一点 ——
 * 单看没问题，并排就"没对齐"。2026-09-21 全站归一之后加这条锁住它。
 */
test("表格单元格内边距必须走 CELL（禁止手写 px-3 py-2 / px-2 py-2 / px-3 py-1.5）", () => {
  /**
   * 取出一段 JSX 开标签里 **它自己那个** className 的取值。
   *
   * 上一版这里踩了坑：用「`<td` 往后看 4 行」的正则去抓 className，
   * 而 `className={CELL}` / `` className={`${CELL} …`} `` 都不是字符串字面量，
   * 正则抓不到，就一路滑到**下一个元素**的 className 上，把已经 token 化
   * 的格子报成违规（6 个误报，全部是 `<td className={CELL}>` 后面跟着
   * 带 `px-1` 的子元素）。判据必须只看这个标签本身。
   */
  const classOf = (tag: string): string => {
    const at = tag.indexOf("className=");
    if (at < 0) return "";
    const rest = tag.slice(at + "className=".length).trimStart();
    const quote = rest[0];
    if (quote === '"' || quote === "'") {
      const end = rest.indexOf(quote, 1);
      return end < 0 ? rest.slice(1) : rest.slice(1, end);
    }
    if (quote === "{") {
      // 花括号配对，兜住 cn(a, b) / 三元 / 模板串
      let depth = 0;
      for (let k = 0; k < rest.length; k += 1) {
        if (rest[k] === "{") depth += 1;
        else if (rest[k] === "}") {
          depth -= 1;
          if (depth === 0) return rest.slice(1, k);
        }
      }
      return rest.slice(1);
    }
    return "";
  };

  const offenders: string[] = [];
  for (const abs of files) {
    const rel = relative(ROOT, abs).replace(/\\/g, "/");
    if (ALLOWLIST.has(rel) || TD_PADDING_OK.has(rel)) continue;
    const lines = stripComments(readFileSync(abs, "utf8")).split("\n");
    lines.forEach((line, i) => {
      const at = line.search(/<td\b/);
      if (at < 0) return;
      // `<td` 与它的 `>` 可能不在同一行 —— 只取到这个开标签结束为止
      let tag = line.slice(at);
      for (let k = i + 1; k < lines.length && !tag.includes(">"); k += 1) tag += ` ${lines[k]}`;
      const cls = classOf(tag.slice(0, tag.indexOf(">") + 1));
      if (/\bCELL\b/.test(cls)) return; // 已 token 化
      if (!/(?:^|\s)p[xy]?-/.test(cls)) return; // 本来就没有内边距 → 不在此列
      offenders.push(`${rel}:${i + 1}  ${line.trim().slice(0, 90)}`);
    });
  }
  assert.deepEqual(
    offenders,
    [],
    `请用 CELL（= px-3 py-2，定义在 lib/ui.ts）：\n${offenders.join("\n")}`,
  );
});
