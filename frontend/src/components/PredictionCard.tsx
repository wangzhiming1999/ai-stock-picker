import { useCallback, useEffect, useState } from "react";
import { fetchIndexHistory, fetchPrediction, fetchPredictionHistory, fetchPredictionStats } from "../api/client";
import CollapsiblePanel from "./ui/CollapsiblePanel";
import KLineChart from "./KLineChart";
import { safeArray, safeObj } from "../lib/safe";
import { FORCE_ANALYSIS_HINT, confirmForceRefresh } from "../lib/spotGuard";
import type { IndexHistory, MarketPrediction, PredictionRecord, PredictionStats, StockHistory } from "../types";
import { dirTone, pctTone, pnlTone } from "../lib/tone";
import StatTile from "./ui/StatTile";
import Button from "./ui/Button";
import Table, { Th } from "./ui/Table";
import { CELL } from "../lib/ui";

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getMonth() + 1}-${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export default function PredictionCard() {
  const [data, setData] = useState<MarketPrediction | null>(null);
  const [stats, setStats] = useState<PredictionStats | null>(null);
  const [history, setHistory] = useState<PredictionRecord[]>([]);
  const [indexHist, setIndexHist] = useState<IndexHistory | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const load = useCallback(async (force = false) => {
    setLoading(true);
    setErr("");
    try {
      const [p, s, h] = await Promise.all([
        fetchPrediction(force),
        fetchPredictionStats().catch(() => null),
        fetchPredictionHistory(15).catch(() => []),
      ]);
      setData(p);
      setStats(s);
      setHistory(h);
      // 大盘走势图（只读行情，失败不影响主流程）
      fetchIndexHistory(120)
        .then(setIndexHist)
        .catch(() => setIndexHist(null));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  // 转成 KLineChart 需要的结构
  const chartHistory: StockHistory | undefined = indexHist
    ? { dates: indexHist.dates, closes: indexHist.closes, volumes: indexHist.volumes }
    : undefined;

  useEffect(() => {
    void load();
  }, [load]);

  const forceRefresh = async () => {
    // 推衍会真实调用模型（耗时且消耗额度），跳过当日缓存前先确认。
    if (!(await confirmForceRefresh(FORCE_ANALYSIS_HINT))) return;
    await load(true);
  };

  const hitColor = (hit: boolean | undefined) => (hit ? "bg-brand/15 text-brand-light" : "bg-surface-inset/40 text-ink-muted");

  return (
    <CollapsiblePanel
      id="prediction"
      title="明日大盘推衍"
      subtitle="上证指数技术信号 + AI 预测 · 附准确率追踪"
      action={
        <Button variant="outlineQuiet" size="sm" onClick={() => void forceRefresh()} disabled={loading} >
          {loading ? "分析中..." : "强制刷新"}
        </Button>
      }
    >

      {err && <div className="rounded-lg border border-state-danger-line bg-state-danger-surface px-3 py-2 text-body text-state-danger-soft">{err}</div>}

      {!data && !err && <div className="p-3 text-body text-ink-soft">正在基于上证指数技术信号推衍明日走势...</div>}

      {data && (
        <div className="space-y-3">
          {/* 方向 + 概率 */}
          <div className="flex items-center gap-4">
            <div>
              <div className="text-meta text-ink-muted">
                {data.technical?.target_date ? `${data.technical.target_date} 方向` : "下一个交易日方向"}
              </div>
              <div className={`text-hero font-bold ${dirTone(data.summary.direction).text}`}>
                {data.summary.direction ?? "-"}
                {data.summary.direction_score > 0 && (
                  <span className="ml-1 text-body font-semibold text-ink-muted">({data.summary.direction_score.toFixed(1)})</span>
                )}
              </div>
            </div>
            {data.summary.probability && (
              <div className="rounded-lg bg-surface-inset/70 px-3 py-2 text-meta text-ink-soft">
                {data.summary.probability}
              </div>
            )}
          </div>

          {/* 大盘走势图 */}
          {chartHistory && (
            <div className="rounded-xl border border-surface-line bg-surface-panel p-2">
              <div className="mb-1 flex items-center justify-between px-1">
                <span className="text-meta text-ink-muted">
                  {indexHist?.index ?? "上证指数"} · 近 {indexHist?.days ?? 0} 个交易日
                </span>
                {indexHist?.latest != null && (
                  <span className="flex items-baseline gap-1.5">
                    <span className="text-body font-semibold text-ink">{indexHist.latest.toFixed(2)}</span>
                    <span
                      className={`text-meta font-medium ${pnlTone(indexHist.change_pct)}`}
                    >
                      {(indexHist.change_pct ?? 0) >= 0 ? "+" : ""}
                      {indexHist.change_pct?.toFixed(2)}%
                    </span>
                  </span>
                )}
              </div>
              <KLineChart history={chartHistory} height={200} />
            </div>
          )}

          {/* 关键点位 */}
          {data.summary.key_levels && (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {Object.entries(safeObj<Record<string, string | number>>(data.summary.key_levels, {})).map(([k, v]) => (
                <div key={k} className="rounded-lg bg-surface-inset/70 px-2 py-1.5 text-center">
                  <div className="text-meta text-ink-muted">{k}</div>
                  <div className="text-body font-semibold text-ink">{v ?? "-"}</div>
                </div>
              ))}
            </div>
          )}

          {/* 研判 */}
          <p className="text-body leading-relaxed text-ink-soft">{data.summary.summary ?? ""}</p>

          {/* 驱动因素 */}
          {data.summary.drivers && data.summary.drivers.length > 0 && (
            <div>
              <div className="mb-1 text-meta font-semibold text-ink-muted">关键因素</div>
              <ul className="list-disc pl-4 text-meta text-ink-soft space-y-0.5">
                {safeArray<string>(data.summary.drivers).map((d, i) => (
                  <li key={i}>{d}</li>
                ))}
              </ul>
            </div>
          )}

          {/* 操作建议 */}
          {data.summary.trading_advice && (
            <div className="rounded-lg border border-state-warn-line bg-state-warn-surface p-3">
              <div className="mb-1 text-meta font-semibold text-amber-400">操作建议</div>
              <p className="text-meta leading-relaxed text-amber-200/80">{data.summary.trading_advice}</p>
            </div>
          )}

          {/* 技术基础数据 */}
          <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-surface-line pt-2 text-meta text-ink-muted">
            <span>收盘 {data.technical.price.toFixed(2)}</span>
            <span>当日 {data.technical.day_change > 0 ? "+" : ""}{data.technical.day_change}%</span>
            <span>量比 {data.technical.vol_ratio}</span>
            <span>近5日 {data.technical.ret5 > 0 ? "+" : ""}{data.technical.ret5}%</span>
            <span>近20日 {data.technical.ret20 > 0 ? "+" : ""}{data.technical.ret20}%</span>
            <span>60日区间 {data.technical.position_60d}%</span>
            {data.technical.signal && (
              <span>信号强度 {data.technical.signal.strength.toFixed(1)}</span>
            )}
          </div>
        </div>
      )}

      {/* 准确率统计 */}
      {stats && (stats.total > 0 || (stats.by_direction && Object.keys(stats.by_direction).length > 0)) && (
        <div className="mt-4 border-t border-surface-line pt-3">
          <div className="mb-2 text-meta font-semibold text-ink-muted">预测准确率</div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <StatTile value={stats.total} label="已记录" />
            <StatTile value={stats.settled} label="已结算" />
            <StatTile value={stats.hit} label="命中" />
            <StatTile
              value={stats.hit_rate != null ? `${stats.hit_rate}%` : "-"}
              label="命中率"
              valueClass={pctTone(stats.hit_rate)}
            />
          </div>
          {Object.entries(stats.by_direction).length > 0 && (
            <div className="mt-2 flex flex-wrap gap-2 text-meta">
              {Object.entries(stats.by_direction).map(([d, b]) => (
                <span key={d} className="rounded-md bg-surface-inset/70 px-2 py-1 text-ink-muted">
                  {d} {b.hit}/{b.total}（{b.hit_rate ?? "-"}%）
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 历史预测记录 */}
      {safeArray(history).length > 0 && (
        <div className="mt-4 border-t border-surface-line pt-3">
          <div className="mb-2 text-meta font-semibold text-ink-muted">历史预测</div>
          <Table label="历史预测记录" maxHeight="xs" head={
            <tr>
              <Th>时间</Th>
              <Th>预测</Th>
              <Th align="right">实际</Th>
              <Th align="center">结果</Th>
            </tr>
          }>
                {history.map((r) => (
                  <tr key={r.id} className="border-t border-surface-line-soft">
                    <td className={`${CELL} text-meta text-ink-muted`}>{fmtDate(r.created_at)}</td>
                    <td className={CELL}>
                      <span className={`text-meta font-medium ${dirTone(r.direction_raw || r.direction).text}`}>
                        {r.direction_raw || r.direction || "-"}
                      </span>
                    </td>
                    <td className={`${CELL} text-right text-meta`}>
                      {r.actual_direction ? (
                        <span className={pnlTone(r.actual_change)}>
                          {r.actual_direction} {r.actual_change != null ? `${r.actual_change > 0 ? "+" : ""}${r.actual_change}%` : ""}
                        </span>
                      ) : (
                        <span className="text-ink-muted">待结算</span>
                      )}
                    </td>
                    <td className={`${CELL} text-center`}>
                      {r.hit != null ? (
                        <span className={`rounded-md px-1.5 py-0.5 text-meta ${hitColor(r.hit)}`}>
                          {r.hit ? "命中" : "未中"}
                        </span>
                      ) : (
                        <span className="text-ink-faint">-</span>
                      )}
                    </td>
                  </tr>
                ))}
            </Table>
        </div>
      )}
    </CollapsiblePanel>
  );
}
