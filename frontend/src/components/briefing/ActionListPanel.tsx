import {
  BellRing,
  Coins,
  Layers,
  Target,
  TrendingDown,
} from "lucide-react";
import type { ActionList, ActionListItem } from "../../types";
import { TEXT } from "../../lib/ui";
import DecisionBadge from "../ui/DecisionBadge";

/**
 * 来源 → 图标与标签。图标只用于「这项是哪个链路说的」，**不参与排序**
 * （排序由后端 DECISION_ORDER 决定，前端不二次排）。
 */
const SOURCE_META: Record<ActionListItem["source"], { icon: typeof Target; label: string }> = {
  holding: { icon: TrendingDown, label: "持仓" },
  position: { icon: Coins, label: "仓位" },
  board: { icon: Layers, label: "板块" },
  morning: { icon: Target, label: "关注" },
  limitup: { icon: BellRing, label: "连板环境" },
};

function ActionRow({ item }: { item: ActionListItem }) {
  const meta = SOURCE_META[item.source] ?? SOURCE_META.morning;
  const Icon = meta.icon;
  return (
    <div className="flex gap-2.5 py-2">
      <div className="mt-0.5 flex w-14 shrink-0 items-center gap-1 text-meta text-ink-muted">
        <Icon className="h-3.5 w-3.5" aria-hidden />
        {meta.label}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <DecisionBadge decision={item.action} />
          <span className="text-body font-medium text-ink">{item.headline}</span>
        </div>
        <p className="mt-0.5 text-meta leading-relaxed text-ink-soft">{item.detail}</p>
        {item.trigger && (
          <p className="mt-0.5 text-meta leading-relaxed text-ink-muted">触发：{item.trigger}</p>
        )}
        {/* 口径随项展示：没有口径的并列展示会诱导用户跨项比较 */}
        <p className="mt-0.5 text-micro leading-relaxed text-ink-faint">{item.caliber}</p>
      </div>
    </div>
  );
}

/**
 * 今日总指令（C）：把方向 / 仓位 / 板块 / 持仓 / 连板环境汇成一张清单。
 *
 * ⚠️ **刻意不做加权合成分**：这些链路高度相关（同一轮行情的不同切面），
 * 相加等于把同一个信号放大 N 倍。所以本组件：
 *   · 不显示任何「综合分 / 今日评分 / 健康度」；
 *   · 各项并列，每项自带口径；
 *   · 显式展示不可比声明。
 *
 * 排序由后端按 DECISION_ORDER（风险处置先于开仓）给出，前端**不二次排序** ——
 * 同一份数据在两处排序必然有一处会漂。
 */
export default function ActionListPanel({ data }: { data?: ActionList | null }) {
  if (!data || data.items.length === 0) {
    return (
      <div className="rounded-lg bg-surface-inset/50 px-3 py-2">
        <p className="text-meta text-ink-soft">
          今日暂无可汇总的行动项。注意：某一链路取数失败时该项会**缺席**，
          这与「今天没事发生」不是同一件事 —— 可下拉刷新重试。
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      <div className="divide-y divide-surface-line-soft">
        {data.items.map((item, i) => (
          <ActionRow key={`${item.source}-${item.headline}-${i}`} item={item} />
        ))}
      </div>

      {/* 不可比声明：必须常驻，不能折叠、不能只放 tooltip */}
      <div className="rounded-lg border border-state-warn-line bg-state-warn-surface px-3 py-2">
        <p className="text-micro leading-relaxed text-state-warn-soft">{data.incomparable_note}</p>
        {data.caveats.length > 0 && (
          <ul className="mt-1 space-y-0.5 text-micro leading-relaxed text-state-warn-soft/90">
            {data.caveats.map((c) => (
              <li key={c}>· {c}</li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/** 决策复盘（A）：听建议后的实际收益。⚠️ 描述性读数，不是因果结论。 */
export function DecisionReviewPanel({ data }: { data?: import("../../types").DecisionReview | null }) {
  if (!data) return null;
  if (!data.available) {
    return (
      <div className="rounded-lg bg-surface-inset/50 px-3 py-2">
        <p className="text-meta text-ink-soft">
          决策复盘未启用：{data.note || "留痕表未配置"}。
        </p>
      </div>
    );
  }
  if (data.total_decided === 0) {
    return (
      <div className="rounded-lg bg-surface-inset/50 px-3 py-2">
        <p className="text-meta text-ink-soft">
          近 {data.window_days} 天没有持仓决策记录。决策从每日收盘 cron 开始留痕，
          积累几天后这里才能给出读数。
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <p className={TEXT.meta}>
        近 {data.window_days} 天共 <b className="text-ink-soft">{data.total_decided}</b> 条持仓决策，
        已回填成交 <b className="text-ink-soft">{data.total_settled}</b> 条
      </p>
      <div className="grid gap-2 sm:grid-cols-2">
        {data.groups.map((g) => (
          <div key={g.action} className="rounded-lg bg-surface-inset/50 px-2.5 py-2">
            <div className="flex items-center gap-1.5">
              <DecisionBadge decision={g.action as never} />
              <span className="text-meta text-ink-muted">
                {g.decided} 条 / 已成交 {g.settled}
              </span>
            </div>
            <div className="mt-1 text-meta text-ink-soft">
              {g.sample_sufficient && g.avg_gain_pct != null ? (
                <>
                  平均收益{" "}
                  <b className={g.avg_gain_pct >= 0 ? "text-red-400" : "text-green-400"}>
                    {g.avg_gain_pct >= 0 ? "+" : ""}
                    {g.avg_gain_pct}%
                  </b>
                  {g.median_gain_pct != null && (
                    <span className="ml-1.5 text-ink-muted">中位数 {g.median_gain_pct}%</span>
                  )}
                </>
              ) : (
                <span className="text-ink-muted">
                  样本不足（{g.settled} 条），不给平均值 —— 少量样本的均值是噪声
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
      {/* 自选择偏差免责：必须渲染，否则会被读成「本工具带来超额」 */}
      <div className="rounded-lg border border-state-warn-line bg-state-warn-surface px-3 py-2">
        <ul className="space-y-0.5 text-micro leading-relaxed text-state-warn-soft/90">
          {data.caveats.map((c) => (
            <li key={c}>· {c}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}
