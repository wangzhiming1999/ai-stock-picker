import type { StockAnalysis, StockInfo } from "../types";
import { motion } from "framer-motion";
import KLineChart from "./KLineChart";
import DebateBlock from "./DebateBlock";
import TradePlanBlock from "./TradePlanBlock";
import ScoreBar from "./ui/ScoreBar";
import { fmtNum, safeArray } from "../lib/safe";
import { CHIP, pnlTone, rrTone, scoreTone } from "../lib/tone";
import { CARD, SUB } from "../lib/ui";
import { TacticChip, tacticEvidenceLabel } from "./TacticHit";

interface Props {
  analysis: StockAnalysis;
  info?: StockInfo;
}

export default function StockCard({ analysis, info }: Props) {
  const quote = info?.quote;
  const rising = (quote?.change_pct ?? 0) >= 0;
  const dimensions = safeArray<{ name?: string; score?: number }>(analysis.dimensions);
  const risks = safeArray<string>(analysis.risks);
  const suggestions = safeArray<string>(analysis.suggestions);

  return (
    <motion.div
      whileHover={{ y: -3 }}
      transition={{ duration: 0.2 }}
      className={`${CARD} backdrop-blur hover:border-surface-line`}
    >
      {/* 头部 */}
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-num font-bold text-white">
            {analysis.name}
            <span className="ml-2 text-body font-normal text-ink-muted">{analysis.code}</span>
          </h3>
          {quote && (
            <div className="mt-1 flex items-baseline gap-2">
              <span className="text-hero font-semibold text-white">{quote.price.toFixed(2)}</span>
              <span className={`text-body font-medium ${pnlTone(quote.change_pct)}`}>
                {rising ? "+" : ""}
                {quote.change_pct.toFixed(2)}%
              </span>
            </div>
          )}
        </div>
        <div className="text-right">
          <div className="text-body text-ink-muted">综合评分</div>
          <div className="text-display font-bold text-brand-light">{fmtNum(analysis.overall_score, 1, "0")}</div>
          <div className="text-meta text-ink-muted">/ 10</div>
        </div>
      </div>

      {/* K线 */}
      <div className="mt-4">
        <KLineChart history={info?.history} />
      </div>

      {/* 综合点评 */}
      <p className="mt-4 text-body leading-relaxed text-ink-soft">{analysis.summary ?? ""}</p>

      {analysis.strategy && (
        <div className={`mt-4 ${SUB} p-3`}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-meta font-semibold text-white">趋势是否合格</div>
              <div className="mt-0.5 text-meta text-ink-soft">公开规则逐项检查，不由 AI 猜测</div>
            </div>
            <span className={`rounded-full px-2.5 py-1 text-meta font-semibold ${
              analysis.strategy.status === "passed"
                ? "bg-brand/15 text-brand-light"
                : analysis.strategy.status === "watch"
                  ? "bg-amber-500/15 text-amber-300"
                  : "bg-surface-line text-ink-soft"
            }`}>
              {analysis.strategy.passed}/{analysis.strategy.total} 项通过
            </span>
          </div>
          <p className="mt-2 text-body font-medium text-ink">{analysis.strategy.action}</p>
          {analysis.strategy.conditions.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {analysis.strategy.conditions.map((condition) => (
                <span
                  key={condition.label}
                  className={`rounded-lg px-2 py-1 text-meta ${
                    condition.passed ? "bg-brand/10 text-brand-light" : "bg-surface-inset/40 text-ink-muted"
                  }`}
                >
                  {condition.passed ? "✓" : "×"} {condition.label}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 实战形态命中：K 线量价条件逐条核对，全部成立才算命中 */}
      {analysis.tactics && analysis.tactics.length > 0 && (
        <div className={`mt-4 ${SUB} p-3`}>
          <div className="text-meta font-semibold text-white">形态命中</div>
          <div className="mt-0.5 text-meta text-ink-soft">
            K 线量价条件逐条核对，全部成立才算命中 · 未通过回测验证的形态只作观察 · 算法推导
          </div>
          <ul className="mt-2 space-y-2">
            {analysis.tactics.map((t) => (
              <li key={t.key}>
                <div className="flex flex-wrap items-center gap-2">
                  <TacticChip t={t} />
                  <span className="text-meta text-ink-soft">
                    {t.passed}/{t.total} 条件 · 证据 {tacticEvidenceLabel(t)}
                  </span>
                </div>
                <p className="mt-1 text-meta leading-relaxed text-ink-soft">
                  {t.executable ? t.action : t.gate_note || t.action}
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 多空研究员对辩：分歧与风险提示，不是买卖点（executable 恒 false） */}
      {analysis.debate && <DebateBlock debate={analysis.debate} />}

      {/* 交易员计划 + 风控终审（TradingAgents ③④层）：辩论成功才产出，旧缓存缺省隐藏。
          decisionId 有值时附「按计划建仓模拟盘」一键（执行闭环） */}
      {analysis.trade_plan && (
        <TradePlanBlock
          plan={analysis.trade_plan}
          verdict={analysis.fund_manager_verdict}
          decisionId={analysis.agent_decision_id}
        />
      )}

      {/* 技术信号（压力位/买卖点/止损） */}
      {analysis.signal && (
        <div className="mt-4 rounded-xl border border-state-warn-line bg-state-warn-surface p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-meta font-semibold text-amber-400">技术信号</span>
            <span className="flex items-center gap-1">
              <span className="text-meta text-ink-muted">强度</span>
              <span className={`text-body font-bold ${scoreTone(analysis.signal.strength)}`}>
                {fmtNum(analysis.signal.strength, 1)}
              </span>
              <span className="text-meta text-ink-muted">风报比</span>
              <span className={`text-body font-bold ${rrTone(analysis.signal.rr_ratio)}`}>
                {fmtNum(analysis.signal.rr_ratio, 2)}
              </span>
            </span>
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-meta sm:grid-cols-3">
            <div className="flex justify-between rounded-lg bg-surface-inset/70 px-2 py-1">
              <span className="text-ink-muted">支撑位</span>
              <span className="font-medium text-ink">{fmtNum(analysis.signal.support)}</span>
            </div>
            <div className="flex justify-between rounded-lg bg-surface-inset/70 px-2 py-1">
              <span className="text-ink-muted">压力位</span>
              <span className="font-medium text-ink">{fmtNum(analysis.signal.resistance)}</span>
            </div>
            <div className={`flex justify-between rounded-lg px-2 py-1 ${CHIP.buy.bg}`}>
              <span className="text-ink-muted">买入区</span>
              <span className={`font-medium ${CHIP.buy.text}`}>{fmtNum(analysis.signal.buy_point)}</span>
            </div>
            <div className={`flex justify-between rounded-lg px-2 py-1 ${CHIP.sell.bg}`}>
              <span className="text-ink-muted">卖出区</span>
              <span className={`font-medium ${CHIP.sell.text}`}>{fmtNum(analysis.signal.sell_point)}</span>
            </div>
            <div className={`flex justify-between rounded-lg px-2 py-1 ${CHIP.risk.bg}`}>
              <span className="text-ink-muted">止损位</span>
              <span className={`font-medium ${CHIP.risk.text}`}>{fmtNum(analysis.signal.stop_loss)}</span>
            </div>
            <div className="flex justify-between rounded-lg bg-surface-inset/70 px-2 py-1">
              <span className="text-ink-muted">现价</span>
              <span className="font-medium text-ink">{fmtNum(analysis.signal.price)}</span>
            </div>
          </div>
        </div>
      )}

      {/* 持有建议 */}
      {analysis.holding_advice && (
        <div className={`mt-3 ${SUB} p-3`}>
          <div className="mb-1 text-meta font-semibold text-ink-soft">持有建议</div>
          <p className="text-meta leading-relaxed text-ink-muted">{analysis.holding_advice}</p>
        </div>
      )}

      {/* 维度评分 */}
      <div className="mt-4 space-y-2">
        {dimensions.map((d) => (
          <ScoreBar key={d.name ?? String(d.score)} label={d.name ?? "-"} score={d.score ?? 0} />
        ))}
      </div>

      {/* 风险 */}
      {risks.length > 0 && (
        <div className="mt-4 rounded-xl border border-red-900/50 bg-state-danger-surface p-3">
          <div className="mb-1 text-meta font-semibold text-red-400">风险提示</div>
          <ul className="list-disc pl-4 text-meta text-red-300/80 space-y-0.5">
            {risks.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </div>
      )}

      {/* 建议 */}
      {suggestions.length > 0 && (
        <div className={`mt-3 ${SUB} p-3`}>
          <div className="mb-1 text-meta font-semibold text-ink-muted">操作建议</div>
          <ul className="list-disc pl-4 text-meta text-ink-soft space-y-0.5">
            {suggestions.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </div>
      )}
    </motion.div>
  );
}
