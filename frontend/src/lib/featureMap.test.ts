import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { test } from "node:test";
import {
  DOMAINS,
  DOMAIN_TAB,
  FEATURES,
  filterFeatures,
  featuresOf,
  domainsWithoutFeatures,
  isSubFeature,
  type Domain,
  type FeatureEntry,
} from "./featureMap.ts";
import { SUB_NAV, type SubNavDef } from "./subnav.ts";
import type { Tab } from "./nav";

/**
 * 功能地图守卫。
 *
 * 这份测试存在的理由和 `tactic_evidence` 那套闸门一样：**登记表一旦和现实脱钩，
 * 它就从「地图」退化成「传说」**。
 *
 * ## 2026-09-20 重构后，守卫的重心变了
 * 上一版守的是「featureMap 声明的子页在 Panel 源码里存不存在」——靠字符串搜索对账。
 * 现在子页声明集中在 `subnav.ts`、`FeatureEntry.sub` 直接用它推导出的 `SubKey` 联合类型，
 * **拼错根本编译不过**，那条守卫已经没有存在意义了（写了也永远通过，等于假守卫）。
 *
 * 所以换成真正会失败的那条：**每个二级子页都必须至少有一条功能登记**。
 * 一个没有任何功能指向的子页，就是用户点进去发现"什么都没有"的那种黑洞 ——
 * 这个项目反复踩的坑正是「加了东西但没人知道」，而它反过来也成立：
 * 「导航里有入口但东西没登记」同样是脱钩，只是方向相反。
 */

type SubSource = [Tab, readonly SubNavDef[]];
const SUB_ENTRIES = Object.entries(SUB_NAV) as SubSource[];

test("key 唯一 —— 重复的 key 会让 React 列表错位、测试断言失效", () => {
  const keys = FEATURES.map((f) => f.key);
  assert.equal(new Set(keys).size, keys.length, `重复 key: ${keys.filter((k, i) => keys.indexOf(k) !== i)}`);
});

test("label 唯一 —— 两个功能同名等于没登记", () => {
  const labels = FEATURES.map((f) => f.label);
  assert.equal(new Set(labels).size, labels.length);
});

test("落点自洽：global 只能有 anchor，其余只能有 sub", () => {
  for (const f of FEATURES) {
    if (f.domain === "global") {
      assert.ok(f.anchor, `${f.key} 是 global 但没给 anchor，点了不会有任何反应`);
      assert.equal(f.sub, undefined, `${f.key} 是 global 却带了 sub（它不在任何 tab 里）`);
    } else {
      assert.ok(f.sub, `${f.key} 不在 global 却没给 sub，点了只会切 tab 落不到具体区块`);
      assert.equal(f.anchor, undefined, `${f.key} 有 sub 又带 anchor，落点语义冲突`);
    }
  }
});

test("每个二级子页都至少有一条功能登记（空子页 = 用户点进去发现什么都没有）", () => {
  const empty: string[] = [];
  for (const [tab, subs] of SUB_ENTRIES) {
    for (const s of subs) {
      if (!FEATURES.some((f) => f.domain === tab && f.sub === s.key)) {
        empty.push(`${tab}/${s.key}（${s.label}）`);
      }
    }
  }
  assert.deepEqual(empty, [], `这些子页没有任何功能登记：${empty.join("、")}`);
});

test("登记的 sub 必须属于同一个 domain（不能把研究的东西挂到选机会上）", () => {
  for (const f of FEATURES) {
    if (!isSubFeature(f)) continue;
    const allowed = (SUB_NAV[f.domain as Tab] as readonly SubNavDef[]).map((s) => s.key);
    assert.ok(
      allowed.includes(f.sub),
      `${f.key} 的 sub="${f.sub}" 不属于 ${f.domain}（该页只有 ${allowed.join(" / ")}）`,
    );
  }
});

test("一级导航数量与子页宽度都受控 —— 深度超过 2 层就没人找得到", () => {
  // 这条不是风格偏好，是「找不到」的机械原因：一级 4 项 + 二级各自 ≤4 个，
  // 任意功能最多两步可达。超了就该考虑合并，而不是继续加。
  const tabs = Object.keys(DOMAIN_TAB) as Tab[];
  assert.ok(tabs.length <= 4, `一级导航 ${tabs.length} 项，超过 4 项就回到"按功能类型切 tab"了`);
  for (const [tab, subs] of SUB_ENTRIES) {
    assert.ok(subs.length >= 1, `${tab} 没有任何子页`);
    assert.ok(
      subs.length <= 6,
      `${tab} 有 ${subs.length} 个子页，二级导航会挤成一条看不清的带子`,
    );
  }
});

test("DOMAIN_TAB 与 nav.ts 的一级导航保持一致", () => {
  const navSrc = readFileSync(new URL("./nav.ts", import.meta.url), "utf8");
  const navKeys = [...navSrc.matchAll(/key:\s*"(\w+)"/g)].map((m) => m[1]);
  assert.ok(navKeys.length >= 3, "没能从 nav.ts 解析出一级导航 key，守卫本身失效了");
  assert.deepEqual(navKeys.sort(), (Object.keys(DOMAIN_TAB) as string[]).sort());
});

test("每个一级导航都至少有一条功能指向它", () => {
  assert.deepEqual(domainsWithoutFeatures(), []);
  for (const d of Object.keys(DOMAIN_TAB) as Domain[]) {
    assert.ok(featuresOf(d).length > 0, `${d} 下没有任何功能登记`);
  }
});

test("DOMAINS 覆盖全部 domain 且无重复", () => {
  const keys = DOMAINS.map((d) => d.key);
  assert.equal(new Set(keys).size, keys.length);
  const declared = [...(Object.keys(DOMAIN_TAB) as Domain[]), "global" as Domain].sort();
  assert.deepEqual(keys.slice().sort(), declared);
});

test("每条功能都得能靠关键词搜到（自己名字至少能搜出来）", () => {
  for (const f of FEATURES) {
    assert.ok(f.keywords.length > 0, `${f.key} 没有任何检索词`);
    assert.ok(filterFeatures(f.label).some((r) => r.key === f.key), `用 label「${f.label}」搜不到 ${f.key}`);
    for (const kw of f.keywords) {
      assert.equal(kw.trim(), kw, `${f.key} 的关键词「${kw}」有首尾空格，会搜不到`);
    }
  }
});

test("检索不区分大小写 —— keywords 里写 AI 还是 ai 都该命中", () => {
  // 这条守的是匹配行为本身，不是数据风格：曾经想用「keywords 必须全小写」来保证，
  // 但那是把实现细节当纪律（匹配时两边都已转小写），真正该验的是大写查询也能命中。
  for (const q of ["AI", "ai", "QuAd"]) {
    assert.ok(filterFeatures(q).length > 0, `「${q}」什么都没搜到`);
  }
});

test("口语化检索词能命中真实功能（用户不会按模块官方名字搜）", () => {
  const cases: [string, string][] = [
    ["炸板", "global.limitup"],
    ["买不进", "global.limitup"],
    ["靠谱吗", "rs.ledger"],
    ["抄底", "global.limitdown"],
    ["挂单", "today.monitor"],
    ["练手", "hold.sim"],
    ["自选", "hold.watch"],
    ["回测", "rs.backtest"],
    ["形态", "op.tactic"],
  ];
  for (const [q, key] of cases) {
    assert.ok(
      filterFeatures(q).some((f) => f.key === key),
      `搜「${q}」找不到 ${key} —— 用户的说法没被收进 keywords`,
    );
  }
});

test("空查询返回全部，查不到返回空数组（不静默退化成全量）", () => {
  assert.equal(filterFeatures("").length, FEATURES.length);
  assert.equal(filterFeatures("   ").length, FEATURES.length);
  assert.deepEqual(filterFeatures("绝不可能存在的词zzz"), []);
});

test("描述里不得出现荐股话术 —— 这里全是读数与工具，不是指令", () => {
  const banned = ["建议买", "赶紧买", "果断买", "必涨", "稳赚", "包赚", "无风险"];
  for (const f of FEATURES) {
    const text = `${f.label} ${f.desc}`;
    for (const b of banned) {
      assert.ok(!text.includes(b), `${f.key} 的描述出现了「${b}」`);
    }
  }
});

test("「新」标记不能全员都是 —— 满屏新等于没有新", () => {
  const fresh = FEATURES.filter((f) => f.isNew);
  assert.ok(fresh.length > 0, "一条 isNew 都没有，用户发现不了最近加的东西");
  assert.ok(fresh.length < FEATURES.length, "全部标成新，标记失去含义");
});

test("global 类功能的 anchor 必须被真正监听到（否则点了没反应）", () => {
  const busSrc = readFileSync(new URL("./bus.ts", import.meta.url), "utf8");
  const anchors = new Set(FEATURES.filter((f) => f.domain === "global").map((f) => f.anchor));
  for (const a of anchors) {
    assert.ok(a, "出现了空 anchor");
    assert.ok(busSrc.includes(`${a}:`), `anchor「${a}」在 bus.ts 的 BUS 里没有对应的事件常量`);
  }
});

test("featuresOf 只返回该域的条目", () => {
  for (const d of Object.keys(DOMAIN_TAB) as Domain[]) {
    assert.ok(featuresOf(d).every((f: FeatureEntry) => f.domain === d));
  }
  assert.equal(featuresOf("global").every((f) => f.domain === "global"), true);
});

/**
 * 下面两条守的是 `block`（区块级落点）。
 *
 * 为什么这里可以「扫源码对账」，而上面那条 sub 的守卫被废掉了：
 * `sub` 是 `SubKey` 推导出来的编译期类型，拼错根本写不出来；
 * 但 `CollapsiblePanel` 的 `id` 按设计就是个裸字符串（它还要当 localStorage key），
 * 类型系统接不上这一环。所以「登记了一个不存在的区块」是**唯一**能静默发生、
 * 且后果是「点了没反应 / 只切页不滚动」的脱钩 —— 只能靠扫源码兜住。
 */
test("block 落点必须真的挂在某个折叠面板上（否则跳过去只切页、不滚动）", () => {
  const componentsDir = new URL("../components/", import.meta.url);
  const ids = new Set<string>();
  const walk = (dir: URL): void => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (entry.isDirectory()) {
        walk(new URL(`${entry.name}/`, dir));
      } else if (entry.name.endsWith(".tsx")) {
        const src = readFileSync(new URL(entry.name, dir), "utf8");
        for (const m of src.matchAll(/\bid="([A-Za-z_][\w-]*)"/g)) ids.add(m[1]);
      }
    }
  };
  walk(componentsDir);

  // 守卫自检：解析不出 id 说明扫描本身坏了，这条测试就会变成永远通过的假守卫
  assert.ok(ids.size > 10, `只从组件里解析出 ${ids.size} 个 id，扫描逻辑可能失效了`);

  for (const f of FEATURES) {
    if (!f.block) continue;
    assert.ok(ids.has(f.block), `${f.key} 的 block="${f.block}" 在任何组件里都不存在，点了不会滚过去`);
  }
});

test("block 只能和 sub 一起出现（global 靠 anchor，不靠滚动）", () => {
  for (const f of FEATURES) {
    if (!f.block) continue;
    assert.ok(f.sub, `${f.key} 有 block 却没给 sub，跳转时连页面都切不过去`);
    assert.equal(f.anchor, undefined, `${f.key} 同时有 block 和 anchor，落点语义冲突`);
  }
});
