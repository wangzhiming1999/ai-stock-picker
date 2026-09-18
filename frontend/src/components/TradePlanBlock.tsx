import { CheckCircle2, ShieldAlert, XCircle, MinusCircle } from "lucide-react";
import { actionBadge } from "../lib/tone";
import { SUB_QUIET, TEXT } from "../lib/ui";
import type { FundManagerVerdict, TradePlan } from "../types";

/**
 * 交易员计划 + 基金经理终审（TradingAgents ③④层）。
 *
 * 证据纪律（§8）：辩论与计划都是 LLM 推理、无回测支撑 —— 因此这块永远渲染在
 * 「参考」位置：动作徽章只用 actionBadge（方向语义），终审结论是**质量判定**
 * （批准=蓝 / 降级=琥珀 / 否决=中性灰），不占红绿。
 * 终审否决时计划仍然展示 —— 让用户看到「为什么被否」比藏起来更有教育意义。
 */

function VerdictBadge({ verdict }: { verdict: FundManagerVerdict }) {
  const map = {
    approved: { icon: CheckCircle2, cls: "text-brand-light", label: "终审通过" },
    demoted: { icon: MinusCircle, cls: "text-amber-300", label: "终审降级" },
    rejected: { icon: XCircle, cls: "text-ink-muted", label: "终审否决" },
  } as const;
  const { icon: Icon, cls, label } = map[verdict.decision] ?? map.rejected;
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-semibold ${cls}`}>
      <Icon className="h-3.5 w-3.5" aria-hidden />
      {label}
    </span>
  );
}

/** 交易计划动作 → actionBadge 入参（中文动作词走 tone 库的方向语义收口）。 */
const ACTION_LABELS: Record<string, string> = {
  buy: "买入",
  add: "加仓",
  hold: "持有",
  reduce: "减仓",
  avoid: "回避",
};

export default function TradePlanBlock({
  plan,
  verdict,
}: {
  plan: TradePlan;
  verdict?: FundManagerVerdict;
}) {
  const badge = actionBadge(ACTION_LABELS[plan.action] ?? plan.action);
  const isRejected = verdict?.decision === "rejected";
  // 终审否决时仓位/止损以终审为准（为 0 / 无效），展示终审值避免误导
  const pct = isRejected ? 0 : (verdict?.final_position_pct ?? plan.position_pct);
  const stop = verdict?.final_stop_price ?? plan.stop_price;
  const entry = plan.entry_price;

  return (
    <div className="mt-4 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      {/* 头部：标题 + 动作徽章 + 终审结论 */}
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="text-sm font-semibold text-ink">交易员计划</h4>
        <span className={`rounded-md px-1.5 py-0.5 text-xs font-semibold ${badge.text} ${badge.bg}`}>
          {badge.label}
        </span>
        {verdict && <span className="ml-auto"><VerdictBadge verdict={verdict} /></span>}
      </div>

      {/* 关键价位：入场 / 止损 / 目标 / 仓位 */}
      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {entry != null && (
          <div className={`${SUB_QUIET} px-2.5 py-2`}>
            <p className={`text-xs ${TEXT.meta}`}>入场触发</p>
            <p className="mt-0.5 text-sm font-semibold tabular-nums text-ink">{entry}</p>
          </div>
        )}
        {stop != null && (
          <div className={`${SUB_QUIET} px-2.5 py-2`}>
            <p className={`text-xs ${TEXT.meta}`}>止损</p>
            <p className="mt-0.5 text-sm font-semibold tabular-nums text-amber-300">{stop}</p>
          </div>
        )}
        {plan.target_price != null && !isRejected && (
          <div className={`${SUB_QUIET} px-2.5 py-2`}>
            <p className={`text-xs ${TEXT.meta}`}>目标</p>
            <p className="mt-0.5 text-sm font-semibold tabular-nums text-ink">{plan.target_price}</p>
          </div>
        )}
        <div className={`${SUB_QUIET} px-2.5 py-2`}>
          <p className={`text-xs ${TEXT.meta}`}>仓位</p>
          <p className="mt-0.5 text-sm font-semibold tabular-nums text-ink">{pct}%</p>
        </div>
      </div>

      {/* 分批方案 */}
      {plan.batches.length > 0 && !isRejected && (
        <ul className={`mt-2.5 space-y-1 text-xs leading-relaxed ${TEXT.meta}`}>
          {plan.batches.map((b, i) => (
            <li key={i} className="flex gap-1.5">
              <span className="text-ink-faint">·</span>
              <span>{b}</span>
            </li>
          ))}
        </ul>
      )}

      {/* 计划依据 */}
      {plan.rationale && (
        <p className={`mt-2.5 text-xs leading-relaxed ${TEXT.meta}`}>
          <span className="font-medium text-ink-muted">依据：</span>
          {plan.rationale}
        </p>
      )}

      {/* 失效条件 */}
      {plan.invalidation && !isRejected && (
        <p className={`mt-1.5 text-xs leading-relaxed ${TEXT.meta}`}>
          <span className="font-medium text-ink-muted">失效条件：</span>
          {plan.invalidation}
        </p>
      )}

      {/* 终审裁决理由：逐条展示（approved 也展示，让用户知道过了哪些关） */}
      {verdict && verdict.verdict_notes.length > 0 && (
        <div className="mt-2.5 border-t border-slate-800/60 pt-2.5">
          <p className="text-xs font-medium text-ink-muted">风控终审</p>
          <ul className={`mt-1 space-y-1 text-xs leading-relaxed ${TEXT.meta}`}>
            {verdict.verdict_notes.map((n, i) => (
              <li key={i} className="flex gap-1.5">
                <ShieldAlert className="mt-0.5 h-3 w-3 shrink-0 text-ink-faint" aria-hidden />
                <span>{n}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className={`mt-2.5 flex items-start gap-1.5 text-xs leading-relaxed ${TEXT.meta}`}>
        <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-400" aria-hidden />
        <span>
          计划来自 LLM 推理（无回测支撑），风控终审只核对纪律不保证收益；
          {(isRejected && " 本计划已被否决，仅作演示。") || " 参考前请对照自己的持仓成本与风险承受能力。"}
        </span>
      </p>
    </div>
  );
}
