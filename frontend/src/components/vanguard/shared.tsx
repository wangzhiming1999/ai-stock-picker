import type { ReactNode } from "react";
import { AlertTriangle, ChevronDown } from "lucide-react";
import { CHIP, pnlTone, scoreChip } from "../../lib/tone";
import type { VanguardEvidence, VanguardExpectedPrice, VanguardLevels } from "../../types";

/**
 * 决策先锋 · 共享展示件
 *
 * ## 两条配色纪律（与 lib/tone.ts 一致，不要在这里破例）
 *
 * 1. **质量 ≠ 方向**。三维分、板块强度分、抱团档位回答的是「好不好」，
 *    走蓝—琥珀—灰阶梯（scoreChip / scoreTone），**不占红绿**；
 *    只有**有方向的量**（涨跌幅、主力净额 / 净占比）才用 pnlTone（红正绿负）。
 *    否则同一张表里「资金 +1.2 亿」是红、「强度 8.0」也是红，读者得为每个数字重建一次映射。
 *
 * 2. **null ≠ 0**。某一维没观测到（后端给 null）必须显示「—」，
 *    且不参与任何颜色判断 —— 否则「资金流端点不可用」会被读成「这些票资金都很差」。
 */

/** 三维短名。与后端 vanguard_service.DIM_KEYS 对应。 */
export const DIM_SHORT: Record<string, string> = {
  dark_money: "资金",
  trend: "趋势",
  activity: "活跃",
};

/** 三维分数芯片。null 显示「—」（未观测），与 0.0 分严格区分。 */
export function DimChip({ v, title }: { v: number | null | undefined; title?: string }) {
  if (v == null) {
    return (
      <span
        title="该维本次未观测到（不是 0 分）"
        className="inline-block min-w-[2.2rem] rounded-md bg-surface-raised px-1.5 py-0.5 text-center text-meta font-semibold text-ink-muted"
      >
        —
      </span>
    );
  }
  return (
    <span
      title={title}
      className={`inline-block min-w-[2.2rem] rounded-md px-1.5 py-0.5 text-center text-meta font-semibold ${scoreChip(v)}`}
    >
      {v.toFixed(1)}
    </span>
  );
}

/** 亿元金额文本（带符号）。资金净额是**有方向的量**，所以走 pnlTone。 */
export function YiText({ v, digits = 2 }: { v: number | null | undefined; digits?: number }) {
  if (v == null || !Number.isFinite(v)) {
    return <span className="text-ink-muted">—</span>;
  }
  return (
    <span className={pnlTone(v)}>
      {v >= 0 ? "+" : ""}
      {v.toFixed(digits)}亿
    </span>
  );
}

/** 百分数文本（带符号）。用于涨跌幅、主力净占比。 */
export function PctText({ v, digits = 2 }: { v: number | null | undefined; digits?: number }) {
  if (v == null || !Number.isFinite(v)) {
    return <span className="text-ink-muted">—</span>;
  }
  return (
    <span className={pnlTone(v)}>
      {v >= 0 ? "+" : ""}
      {v.toFixed(digits)}%
    </span>
  );
}

/**
 * 抱团档位配色。
 *
 * 抱团程度是**环境质量判断**（资金是否集中在少数板块），不是价格方向 ——
 * 所以不占红绿：明显抱团 = 主色（达标语义），中等 = 琥珀，分散 / 未知 = 中性。
 * 与 tone.ts 的 `playAdviceTone` 是同一套取向。
 */
export function herdingTone(level: string | null | undefined): string {
  if (level === "high") return "text-brand-light";
  if (level === "mid") return "text-amber-300";
  if (level === "low") return "text-ink-muted";
  return "text-ink-muted";
}

export const HERDING_LABEL: Record<string, string> = {
  high: "抱团明显",
  mid: "集中度中等",
  low: "分散",
  unknown: "无法判定",
};

/** 证据档位角标。不可执行档一律给琥珀 + 警示图标，避免被当成结论读。 */
export function EvidenceBadge({
  evidence,
  className = "",
}: {
  evidence?: VanguardEvidence | null;
  className?: string;
}) {
  if (!evidence) return null;
  const actionable = evidence.actionable;
  return (
    <span
      title={evidence.summary}
      className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-meta leading-none ${
        actionable ? "bg-brand/15 text-brand-light" : "bg-amber-500/15 text-amber-300"
      } ${className}`}
    >
      {!actionable && <AlertTriangle className="h-3 w-3 shrink-0" aria-hidden />}
      证据 · {evidence.label}
    </span>
  );
}

/**
 * 证据说明块：档位 + 结论摘要 + 出处 + 可选的补充口径提示。
 *
 * 这个块**不是装饰**。三维榜与买卖时机都是在给读数，不写清楚「这份读数凭什么」，
 * 界面就会把猜测包装成结论 —— 本项目对可信度的唯一解就是把它显式打出来。
 *
 * ## 2026-09-21 视觉降级（外观改了，⚠️ 文案一个字都没删）
 * 原实现是一整块 `border-state-warn-line bg-state-warn-surface` 的高饱和大色块，
 * 三行文字全部铺开，**比页面上的真实数字还抢眼**。问题是：
 *
 *   · 琥珀在全站承担「警戒 / 需要留意」的语义（见 tone.ts），而这块是**免责说明** ——
 *     它不是风险提示，只是「这个读数的可信度到哪」。用警戒色描述免责，
 *     等于每页都在喊狼来了；
 *   · 首页第一屏被它吃掉约 90px，而真正要看的数字被推到很下面。
 *
 * 所以改成：**一行摘要（中性色）+ 可展开的详情**。默认只给「档位 + 一句话」，
 * 出处与补充口径收进 `<details>`。这样合规信息一条不少，但视觉权重降到
 * 与「页脚注释」同级 —— 需要复核的人点开就能看到全部。
 *
 * ⚠️ 不要因为「不好看」把 `note` / `summary` / `provenance` 删掉任何一句。
 *    它们是这个项目可信度的载体，降级的是**字号与底色**，不是信息量。
 */
export function EvidenceNote({
  evidence,
  extra,
  tone = "quiet",
}: {
  evidence?: VanguardEvidence | null;
  extra?: ReactNode;
  tone?: "warn" | "quiet";
}) {
  if (!evidence) return null;

  // warn 档保留琥珀，但只用于「不可执行」这个事实本身；quiet 档走纯中性
  const dot = evidence.actionable
    ? "bg-brand-light"
    : tone === "warn"
      ? "bg-amber-400"
      : "bg-ink-muted";

  return (
    <details className="group rounded-lg border border-surface-line-soft bg-surface-inset/50 text-meta">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-1.5 text-ink-muted transition-colors hover:text-ink-soft">
        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${dot}`} aria-hidden />
        <span className="font-medium text-ink-soft">证据档位 {evidence.label}</span>
        {evidence.win_rate &&
          (evidence.win_rate.includes("不进操作路径") ? (
            <span className="shrink-0 rounded-md bg-amber-500/15 px-1.5 py-0.5 text-meta text-amber-300">
              不进操作路径
            </span>
          ) : (
            <span className="shrink-0 rounded-md bg-surface-line/60 px-1.5 py-0.5 text-meta text-ink-muted">
              赢面：{evidence.win_rate}
            </span>
          ))}
        <span className="min-w-0 flex-1 truncate text-ink-soft">{evidence.summary}</span>
        <ChevronDown
          className="h-3.5 w-3.5 shrink-0 text-ink-muted transition-transform group-open:rotate-180"
          aria-hidden
        />
      </summary>
      <div className="space-y-1 border-t border-surface-line-soft px-3 py-2 leading-relaxed text-ink-soft">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
          {evidence.key && <span>{evidence.key}</span>}
          {!evidence.actionable && <span>不进入买点位置</span>}
          {evidence.registered === false && <span>未登记进证据台账</span>}
        </div>
        <p className="text-ink-soft">{evidence.summary}</p>
        <p>出处：{evidence.provenance}</p>
        <p className="text-ink-faint">
          计划持有期：{evidence.plan_horizon ?? "—"} · 历史赢面：{evidence.win_rate ?? "—"}
        </p>
        {extra && <p>{extra}</p>}
      </div>
    </details>
  );
}

function LevelChip({ label, value, tone }: { label: string; value: number; tone: { bg: string; text: string } }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-medium ${tone.bg} ${tone.text}`}>
      <span className="text-ink-muted">{label}</span>
      {Number.isFinite(value) ? value.toFixed(2) : "—"}
    </span>
  );
}

/**
 * 结构位。买卖点直接锚定主支撑 / 主压力，**不随现价漂移**。
 *
 * ⚠️ 买入侧（「回踩可买」）实测超额为负，因此这里只表达价位结构，
 * 不用「建议买入」一类措辞，也不把它渲染成按钮。
 */
export function LevelChips({ levels }: { levels: VanguardLevels | null }) {
  if (!levels) {
    return <span className="text-meta text-ink-soft">K 线不足 60 根，结构位不可用</span>;
  }
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-meta">
      <LevelChip label="支撑" value={levels.support} tone={CHIP.neutral} />
      <LevelChip label="压力" value={levels.resistance} tone={CHIP.neutral} />
      <LevelChip label="买点区" value={levels.buy_point} tone={CHIP.buy} />
      <LevelChip label="卖出区" value={levels.sell_point} tone={CHIP.sell} />
      <LevelChip label="止损" value={levels.stop_loss} tone={CHIP.risk} />
      <span className="text-ink-soft">
        风报比{" "}
        <b className="text-ink-soft">{levels.rr_ratio != null ? levels.rr_ratio.toFixed(2) : "—"}</b> · 信号强度{" "}
        <b className="text-ink-soft">{Number.isFinite(levels.strength) ? levels.strength.toFixed(1) : "—"}</b>
      </span>
    </div>
  );
}

/**
 * 预期价格（执行锚点）。回答「这笔动作打算在什么价位成交」。
 *
 * 与 `LevelChips` 的分工：LevelChips 摆出**全部**结构位供复核；这里只挑出计划真正用的
 * 那一个锚点，并给出「距现价多远」——用户要的是能直接挂出去的那个数。
 *
 * 缺数据必须区分两种原因，不能笼统写成「—」：
 *   null      —— K 线不足 60 根，结构位算不出来；
 *   undefined —— 当日榜单快照是本次上线前落库的（整份 JSONB 缓存到收盘）。
 * 两种都不折算成现价：折算出来的假锚点会被当成真价位用。
 * 也不做红绿着色 —— 锚点是**价位**不是方向，红绿在这个页面只表达涨跌。
 */
export function ExpectedPriceChip({
  ep,
  className = "",
}: {
  ep?: VanguardExpectedPrice | null;
  className?: string;
}) {
  if (ep === undefined) {
    return (
      <span className={`text-meta text-ink-muted ${className}`}>
        预期价格 <b className="text-ink-muted">—</b>
        <span className="ml-1">（当日榜单生成于本功能上线前，下一个交易日重算后可见）</span>
      </span>
    );
  }
  if (ep === null) {
    return (
      <span className={`text-meta text-ink-muted ${className}`}>
        预期价格 <b className="text-ink-muted">—</b>
        <span className="ml-1">（K 线不足 60 根，结构位算不出）</span>
      </span>
    );
  }
  const gap = ep?.gap_pct;
  return (
    <span className={`inline-flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-meta ${className}`}>
      <span className="text-ink-muted">预期价格</span>
      <span className="rounded-md bg-surface-raised px-1.5 py-0.5 font-semibold text-ink" title={ep?.note}>
        {Number.isFinite(ep.price) ? ep.price.toFixed(2) : "—"}
      </span>
      <span className="text-ink-muted">（{ep.setup === "breakout" ? "突破位" : "回踩位"}）</span>
      {gap != null && Number.isFinite(gap) && (
        <span className="text-ink-muted">
          距现价 {gap >= 0 ? "+" : ""}
          {gap.toFixed(2)}%
        </span>
      )}
    </span>
  );
}

/** 资金流端点状态提示。状态必须如实展示，否则「全维中性分」会被误读成「今天没人被资金青睐」。 */
export function FundFlowNotice({
  status,
  covered,
  note,
}: {
  status: string;
  covered: number;
  note?: string | null;
}) {
  // 正常态：一行低调口径说明，不占视觉权重
  if (status !== "cooldown" && status !== "unavailable") {
    return (
      <p className="text-meta text-ink-soft">
        资金维数据源：东财批量资金流排行 · 一次请求覆盖 {covered} 只（非逐股请求）
      </p>
    );
  }
  // 异常态：必须显眼，因为「资金维整体为 0 分」和「资金维不可用」是两回事
  return (
    <p className="flex items-start gap-1.5 rounded-lg border border-state-warn-line bg-state-warn-surface px-3 py-1.5 text-meta text-state-warn-soft">
      <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
      <span>
        资金维本次不可用（{status}
        {note ? `：${note}` : ""}）—— 综合分已按剩余维度重新归一化，
        <b>缺失维不是 0 分</b>。板块强度中的资金分位同样受影响。
      </span>
    </p>
  );
}
