// ⚠️ 只做类型导入：`nav.ts` 会连带引入 lucide-react 的图标组件，
// 而本文件被 node 环境下的守卫测试直接 import —— 拉进 React 会让测试变得又慢又不稳。
// 运行期需要的一级导航 key 由 `DOMAIN_TAB` 自己持有，一致性交给 `featureMap.test.ts` 核对。
// `SubKey` 来自 `subnav.ts`（纯数据、零运行期导入），所以那一条可以直接 import 类型。
import type { Tab } from "./nav";
import type { SubKey } from "./subnav";

/**
 * 全站功能地图 · 单一来源
 *
 * ## 为什么需要它
 * 一级导航有 4 项、二级子页有 11 个，加上两根常驻温度带和一个全局抽屉，
 * 真实功能有 20+ 个。用户打开首页时**看不到这个产品有多少东西** ——
 * 新加的功能（溢价读数、证据台账）加完就等于埋了，只有写过代码的人知道它在哪。
 *
 * 所以功能不该只靠「点进某个 tab 再找」被找到，需要一个**可枚举、可搜索、
 * 可直达**的清单。本文件就是那份清单，形状与 `nav.ts` / `subnav.ts` 一致：
 * 只放数据，不放 UI。
 *
 * ## 三条纪律
 * 1. **一处登记**。新增功能必须在这里加一条，否则 `featureMap.test.ts` 会失败
 *    ——它检查「每个二级子页都至少有一条功能指向它」。反过来，没被登记的功能
 *    等于不存在，这比"加了但找不到"更糟。
 * 2. **`sub` 的类型是 `SubKey`**（从 `subnav.ts` 推导），拼错或写了个已删除的子页
 *    **直接编译不过**。这比上一版的「守卫去源码里搜字符串」强：那时只能事后对账，
 *    现在是"非法状态根本写不出来"。
 * 3. **描述只讲「是什么」**，不写「值得买」「建议」一类的话术。这里全部是
 *    读数与工具，不是指令。
 *
 * ## domain vs anchor
 * - `domain` 决定「先切到哪一页」：today / opportunity / holdings / research。
 * - `global` 类功能不在任何 tab 里（两根常驻条 + 全局搜索），它们在任何页面都
 *   可见，所以跳转时**不切 tab**，只发一个全局事件把目标展开/聚焦（见 `bus.ts`）。
 */

export type Domain = Tab | "global";

/** global 类功能的落点：常驻条 / 抽屉 / 顶部搜索。 */
export type FeatureAnchor = "limitup" | "limitdown" | "search";

/**
 * 一次「跨页跳转」请求。
 *
 * `id` 必须自增：用户可能连着点两次同一个功能（比如先手动切走再点回来），
 * 只比 sub 值的话第二次不会有任何变化 —— 这与 `AnalysisDrawer` 的 requestId 是同一个坑。
 */
export interface NavJump {
  tab: Tab;
  sub?: SubKey;
  id: number;
}

export interface FeatureEntry {
  /** 稳定标识，用于 React key 与测试断言 */
  key: string;
  label: string;
  desc: string;
  domain: Domain;
  /** domain != "global" 时必填：切到该 domain 后要选中哪个子页 */
  sub?: SubKey;
  /** domain == "global" 时必填：要展开/聚焦哪个目标 */
  anchor?: FeatureAnchor;
  /** 检索词。中文全称、简称、英文标识都放进来，用户怎么叫都能搜到 */
  keywords: string[];
  /** 最近一轮新增或大改的功能，列表里打「新」标记，便于老用户发现 */
  isNew?: boolean;
}

/** domain → 一级导航 key（global 不参与切页） */
export const DOMAIN_TAB: Record<Exclude<Domain, "global">, Tab> = {
  today: "today",
  opportunity: "opportunity",
  holdings: "holdings",
  research: "research",
};

/** 分组的展示顺序与标题。顺序 = 用户一天里的使用顺序，不是功能多少。 */
export const DOMAINS: { key: Domain; label: string; desc: string }[] = [
  { key: "today", label: "今日作战", desc: "今天该做什么：盯盘 · 简报" },
  { key: "opportunity", label: "选机会", desc: "今天买什么：推荐 · 决策 · 扫描 · 形态" },
  { key: "holdings", label: "持仓", desc: "我手里有什么：持仓 · 模拟盘 · 自选 · 历史" },
  { key: "research", label: "研究", desc: "这些方法靠不靠谱：台账 · 胜率 · 回测" },
  { key: "global", label: "全局读数", desc: "常驻在每一页顶部，不进任何 tab" },
];

/**
 * 全部功能。
 *
 * 排序原则：同一个 domain 内按「用户一天里会先看到哪个」排，不按实现先后。
 * 标 `isNew` 的只保留最近一轮的成果，过期要摘掉 —— 挂太久就变成噪音，
 * 「新」的含义会失效（这条与 CHANGELOG 的维护规则一致）。
 */
export const FEATURES: FeatureEntry[] = [
  /* ── 今日作战 ─────────────────────────────────────────────── */
  {
    key: "today.monitor",
    label: "盘中监控台",
    desc: "日线 / 15 分 / 5 分多周期，每行给出买卖点与挂单价",
    domain: "today",
    sub: "monitor",
    keywords: ["盯盘", "监控", "买卖点", "挂单", "止损", "支撑", "压力", "monitor"],
    isNew: true,
  },
  {
    key: "today.briefing",
    label: "今日作战简报",
    desc: "早盘方向 · 尾盘动作 · 盘前预读 · 当日复盘 · 形态命中 · 连板梯队",
    domain: "today",
    sub: "briefing",
    keywords: ["简报", "早盘", "方向", "尾盘", "复盘", "预读", "仓位", "briefing"],
  },

  /* ── 选机会 · 推荐 ───────────────────────────────────────── */
  {
    key: "op.recommend",
    label: "AI 每日推荐",
    desc: "模型筛出的今日关注标的，带买点 / 止损 / 手数",
    domain: "opportunity",
    sub: "recommend",
    keywords: ["推荐", "选股", "每日", "AI", "买点", "手数", "recommend"],
  },
  {
    key: "op.quad",
    label: "四维综合排名",
    desc: "基本面 / 技术面 / 资金面 / 情绪面打分排序",
    domain: "opportunity",
    sub: "recommend",
    keywords: ["四维", "排名", "打分", "评分", "quad"],
  },
  {
    key: "op.prediction",
    label: "大盘推衍",
    desc: "指数场景推演与对应应对，不是点位预测",
    domain: "opportunity",
    sub: "recommend",
    keywords: ["大盘", "推衍", "指数", "场景", "prediction"],
  },
  {
    key: "op.sector",
    label: "行业板块热榜",
    desc: "新浪行业板块涨跌幅排序，用来识别当前热点方向",
    domain: "opportunity",
    sub: "recommend",
    keywords: ["板块", "热榜", "行业", "热点", "主线", "sector"],
  },

  /* ── 选机会 · 决策（决策先锋） ────────────────────────────── */
  {
    key: "op.vanguard",
    label: "决策先锋三维榜",
    desc: "暗盘资金 / 趋势 / 活跃度 三维打分排序；三维分是当日读数，不是买入信号",
    domain: "opportunity",
    sub: "vanguard",
    keywords: ["决策先锋", "三维", "选股", "打分", "暗盘", "资金", "vanguard"],
    isNew: true,
  },
  {
    key: "op.vanguard.diagnose",
    label: "三维诊股",
    desc: "单只票的三维分数 + 结构位 + 所属板块强度（量化读数，不给多空结论）",
    domain: "opportunity",
    sub: "vanguard",
    keywords: ["诊股", "体检", "单票", "打分", "diagnose", "个股诊断"],
  },
  {
    key: "op.vanguard.sector",
    label: "板块强度",
    desc: "按当日横截面分位合成的板块强弱（资金 / 动量 / 广度 / 情绪；分位换日即换基准）",
    domain: "opportunity",
    sub: "vanguard",
    keywords: ["板块强度", "强度", "板块", "热点", "核心热点", "strength"],
  },
  {
    key: "op.vanguard.herding",
    label: "主力抱团监测",
    desc: "涨停板块集中度与板块资金净流入占比的合读，用来判断有没有抱团主线",
    domain: "opportunity",
    sub: "vanguard",
    keywords: ["抱团", "主力抱团", "集中度", "主线", "herding"],
  },
  {
    key: "op.vanguard.leader",
    label: "潜力龙头",
    desc: "资金已进场、趋势成立且尚未被拉到买不进的候选（涨幅 ≥9% 的已剔除）",
    domain: "opportunity",
    sub: "vanguard",
    keywords: ["龙头", "潜力龙头", "领涨", "leader"],
  },
  {
    key: "op.vanguard.timing",
    label: "买卖时机结构位",
    desc: "支撑 / 压力 / 止损锚定结构位，不随现价漂移；买入侧实测为负，只作价位参考",
    domain: "opportunity",
    sub: "vanguard",
    keywords: ["买卖时机", "买卖点", "支撑", "压力", "止损", "时机", "timing"],
  },

  /* ── 选机会 · 扫描 ───────────────────────────────────────── */
  {
    key: "op.scan.pick",
    label: "一键找候选",
    desc: "按策略从缓存行情筛候选；要最新数据得先强制刷新",
    domain: "opportunity",
    sub: "scan",
    keywords: ["候选", "找票", "筛选", "一键", "策略选股"],
  },
  {
    key: "op.scan.pre",
    label: "开盘前异动",
    desc: "仅 9:15–9:30 使用；异动不等于可以买",
    domain: "opportunity",
    sub: "scan",
    keywords: ["异动", "竞价", "开盘前", "早盘"],
  },
  {
    key: "op.scan.post",
    label: "收盘前异动",
    desc: "仅 14:45–15:00 使用；需防范尾盘诱多",
    domain: "opportunity",
    sub: "scan",
    keywords: ["异动", "尾盘", "诱多", "收盘前"],
  },
  {
    key: "op.scan.filter",
    label: "按条件筛选",
    desc: "按价格 / 涨幅 / 成交额过滤，不含任何形态确认",
    domain: "opportunity",
    sub: "scan",
    keywords: ["筛选", "条件", "价格", "涨幅", "成交额", "filter"],
  },

  /* ── 选机会 · 形态 ───────────────────────────────────────── */
  {
    key: "op.tactic",
    label: "实战形态命中",
    desc: "K 线量价条件全部成立的只数；条件成立不等于形态被回测验证",
    domain: "opportunity",
    sub: "tactic",
    keywords: ["形态", "技巧", "命中", "tactic", "K线"],
  },

  /* ── 研究 ────────────────────────────────────────────────── */
  {
    key: "rs.ledger",
    label: "证据台账",
    desc: "N 条口径里几条能动手 —— 目前 0 条达到可执行档",
    domain: "research",
    sub: "ledger",
    keywords: ["证据", "台账", "口径", "verified", "能动手", "靠谱吗", "ledger"],
    isNew: true,
  },
  {
    key: "rs.winrate",
    label: "策略胜率",
    desc: "各策略历史胜率；不同口径不可比较、不可相加",
    domain: "research",
    sub: "winrate",
    keywords: ["胜率", "winrate", "统计", "准确率"],
  },
  {
    key: "rs.backtest",
    label: "组合回测",
    desc: "18 只样本池的组合回测（含幸存者偏差说明）",
    domain: "research",
    sub: "backtest",
    keywords: ["回测", "组合", "backtest", "收益率"],
  },
  {
    key: "rs.tacticbt",
    label: "形态回测",
    desc: "K 线形态逐条的独立回测与证据档次",
    domain: "research",
    sub: "backtest",
    keywords: ["回测", "形态", "技巧", "回测验证"],
  },

  /* ── 持仓 ────────────────────────────────────────────────── */
  {
    key: "hold.position",
    label: "持仓总览",
    desc: "成本 / 浮盈浮亏 / 风险等级建议",
    domain: "holdings",
    sub: "position",
    keywords: ["持仓", "成本", "浮盈", "盈亏", "仓位"],
  },
  {
    key: "hold.alert",
    label: "预警规则",
    desc: "到价 / 涨跌幅触发，触发后进顶部报警中心",
    domain: "holdings",
    sub: "position",
    keywords: ["预警", "提醒", "到价", "报警", "alert"],
  },
  {
    key: "hold.sim",
    label: "模拟盘",
    desc: "虚拟资金记账；一字板会自动标注「买不进」",
    domain: "holdings",
    sub: "sim",
    keywords: ["模拟盘", "虚拟", "记账", "paper", "练手"],
  },
  {
    key: "hold.watch",
    label: "自选股",
    desc: "关注列表，可一键整批加入盯盘",
    domain: "holdings",
    sub: "watch",
    keywords: ["自选", "关注", "watchlist", "收藏"],
  },
  {
    key: "hold.history",
    label: "分析历史",
    desc: "历次 AI 分析的批次与结论留档",
    domain: "holdings",
    sub: "history",
    keywords: ["历史", "记录", "批次", "留档"],
  },

  /* ── 全局读数 ────────────────────────────────────────────── */
  {
    key: "global.limitup",
    label: "涨停梯队 · 次日溢价读数",
    desc: "涨停 / 连板 / 炸板率 + 打板次日溢价的统计读数（tradable 与买不进分档报）",
    domain: "global",
    anchor: "limitup",
    keywords: ["涨停", "连板", "梯队", "溢价", "打板", "炸板", "接力", "limitup"],
    isNew: true,
  },
  {
    key: "global.limitdown",
    label: "跌停观察层",
    desc: "跌停家数 / 封单额 + 次日竞价卖出实测；结论是负期望，只读不推",
    domain: "global",
    anchor: "limitdown",
    keywords: ["跌停", "抄底", "封单", "风险", "limitdown"],
  },
  {
    key: "global.search",
    label: "全局搜索 · 深度分析",
    desc: "顶部输入代码或名称直接开分析；在任意列表勾选股票也能进",
    domain: "global",
    anchor: "search",
    keywords: ["搜索", "查股票", "代码", "分析", "深度分析", "辩论", "search"],
  },
];

/** 域名 → 该域下的功能（保持 FEATURES 里的相对顺序）。 */
export function featuresOf(domain: Domain): FeatureEntry[] {
  return FEATURES.filter((f) => f.domain === domain);
}

/**
 * 即时过滤：命中 label / desc / keywords 任意一处即可。
 *
 * 刻意不做拼音首字母匹配 —— 那需要一张额外的码表，维护成本远高于收益，
 * 而 keywords 里已经放了用户实际会打的中文说法（"炸板" / "买不进" / "靠谱吗"）。
 */
export function filterFeatures(query: string): FeatureEntry[] {
  const q = query.trim().toLowerCase();
  if (!q) return FEATURES;
  return FEATURES.filter((f) => {
    const hay = `${f.label} ${f.desc} ${f.keywords.join(" ")}`.toLowerCase();
    return hay.includes(q);
  });
}

/** 该功能是否落在某一级导航的子页里（global 类不算）。 */
export function isSubFeature(f: FeatureEntry): f is FeatureEntry & { sub: SubKey } {
  return f.domain !== "global" && !!f.sub;
}

/** 供测试与 UI 复用的自检：每个一级导航都至少有一条功能指向它。 */
export function domainsWithoutFeatures(): Domain[] {
  return (Object.keys(DOMAIN_TAB) as Domain[]).filter((d) => featuresOf(d).length === 0);
}
