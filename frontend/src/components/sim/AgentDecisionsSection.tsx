import { useCallback, useEffect, useState } from "react";
import { fetchAgentDecisions } from "../../api/client";
import type { AgentDecisionsData } from "../../types";
import StatTile from "../ui/StatTile";
import { pnlTone } from "../../lib/tone";

/** Agent 决策闭环区块：track record 列表 + 采纳/未采纳对照读数（口径 agent_plan 随数据下发）。
 *
 * 措辞纪律（§8）：命中率是质量信息 —— 读数用 scoreTone 语义（达标蓝/一般琥珀），不占红绿；
 * pnl 列是收益方向，走 pnlTone。状态徽章：adopted=蓝、ignored=中性、rejected=中性。
 * 样本 <5 时后端不下发命中率，前端只显示样本数 —— 不自己算（自己算就是绕过口径纪律）。
 */
export default function AgentDecisionsSection() {
  const [data, setData] = useState<AgentDecisionsData | null>(null);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setErr("");
    try {
      setData(await fetchAgentDecisions(30));
    } catch (e) {
      // 表未启用（v9 未迁移）等情况：显示一行说明而不是报错红屏
      setErr((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return null;
  if (err && !data) {
    return (
      <div className="mt-4 border-t border-slate-800 pt-3 text-xs text-ink-faint">
        Agent 决策记录暂不可用：{err}
      </div>
    );
  }
  if (!data || data.decisions.length === 0) {
    return (
      <div className="mt-4 border-t border-slate-800 pt-3">
        <div className="mb-1.5 text-xs font-semibold text-ink-muted">Agent 决策记录</div>
        <p className="text-xs leading-relaxed text-ink-faint">
          还没有记录。在「深度分析」勾选多空对辩并跑出终审计划后，这里会出现 agent 的每条计划与实际结算结果 ——
          这就是 agent 自己的战绩单。
        </p>
      </div>
    );
  }

  const { decisions, stats } = data;
  const pending = decisions.filter((d) => d.settled_at == null);

  return (
    <div className="mt-4 border-t border-slate-800 pt-3">
      <div className="mb-2 flex flex-wrap items-baseline gap-2">
        <span className="text-xs font-semibold text-ink-muted">Agent 决策记录</span>
        <span className="text-xs text-ink-faint">交易员计划 → 终审 → 实际结算 · agent 的战绩单</span>
      </div>

      {stats && (
        <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <StatTile
            value={stats.adopted.hit_rate != null ? `${stats.adopted.hit_rate}%` : "—"}
            label="已采纳命中率"
          />
          <StatTile
            value={
              stats.adopted.avg_pnl_pct != null
                ? `${stats.adopted.avg_pnl_pct >= 0 ? "+" : ""}${stats.adopted.avg_pnl_pct}%`
                : "—"
            }
            label="已采纳平均收益"
          />
          <StatTile
            value={stats.ignored_control.hit_rate != null ? `${stats.ignored_control.hit_rate}%` : "—"}
            label="未采纳对照命中率"
          />
          <StatTile value={`${stats.adopted.settled + stats.ignored_control.settled}`} label="已结算样本" />
        </div>
      )}
      {stats && (
        <p className="mb-3 text-xs leading-relaxed text-ink-faint">
          口径：{stats.caliber.name} · {stats.caliber.window} · {stats.caliber.rule}
          {stats.caliber.pitfall ? `。注意：${stats.caliber.pitfall}` : ""}
        </p>
      )}

      <div className="max-h-64 space-y-1.5 overflow-y-auto">
        {decisions.map((d) => {
          const settledRow = d.settled_at != null;
          return (
            <div key={d.id} className="rounded bg-slate-800/40 px-3 py-2 text-xs">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-ink">{d.name || d.code}</span>
                <span className="text-ink-faint">{d.code}</span>
                <span className="text-ink-faint">· {d.data_date}</span>
                <span
                  className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                    d.status === "adopted"
                      ? "bg-blue-900/40 text-blue-300"
                      : d.status === "rejected"
                        ? "bg-slate-700/50 text-ink-faint"
                        : "bg-slate-700/40 text-ink-soft"
                  }`}
                  title={
                    d.status === "adopted"
                      ? "已按计划建仓模拟盘"
                      : d.status === "rejected"
                        ? "终审否决（对照样本）"
                        : "未采纳（到期后作为对照组结算）"
                  }
                >
                  {d.status === "adopted" ? "已采纳" : d.status === "rejected" ? "已否决" : "未采纳"}
                </span>
                <span className="text-ink-faint">
                  {d.action} · 终审 {d.verdict} · 仓位 {d.position_pct}%
                </span>
                <span className="ml-auto">
                  {settledRow ? (
                    d.pnl_pct != null ? (
                      <span className={pnlTone(d.pnl_pct)}>
                        {d.pnl_pct >= 0 ? "+" : ""}
                        {d.pnl_pct.toFixed(1)}%{d.hit ? " · 命中" : " · 未命中"}
                      </span>
                    ) : (
                      <span className="text-ink-faint">已结算（无方向基准）</span>
                    )
                  ) : (
                    <span className="text-ink-faint">待结算（{d.horizon_days} 个交易日后）</span>
                  )}
                </span>
              </div>
              {d.reflection && (
                <p className="mt-1 leading-relaxed text-ink-faint">{d.reflection}</p>
              )}
            </div>
          );
        })}
      </div>
      {pending.length > 0 && (
        <p className="mt-1.5 text-xs text-ink-faint">
          {pending.length} 条待结算 —— 每日收盘 cron 自动按到期日收盘价回写。
        </p>
      )}
    </div>
  );
}
