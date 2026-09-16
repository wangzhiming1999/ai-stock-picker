import { useCallback, useEffect, useState } from "react";
import { fetchWinrate } from "../api/client";
import CollapsiblePanel from "./CollapsiblePanel";
import { safeObj } from "../lib/safe";
import { pctTone } from "../lib/tone";
import type { WinrateStats } from "../types";
import { CaliberIncomparabilityNote, CaliberLine } from "./CaliberNote";
import StatTile from "./StatTile";
import Button from "./Button";

export default function WinratePanel() {
  const [data, setData] = useState<WinrateStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setErr("");
    try {
      setData(await fetchWinrate());
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <CollapsiblePanel
      id="winrate"
      title="胜率看板"
      subtitle="预测与推荐的实际命中表现 · 每日自动结算"
      action={
        <Button variant="outlineQuiet" size="sm" onClick={() => void load()} disabled={loading} >
          {loading ? "加载中..." : "刷新"}
        </Button>
      }
    >

      {err && <div className="rounded-lg border border-red-800 bg-red-950/40 px-3 py-2 text-sm text-red-300">{err}</div>}
      {!data && !err && <div className="p-3 text-sm text-ink-faint">加载中...</div>}

      {data && (
        <div className="space-y-4">
          {/* 数据积累徽标：让用户看见闭环在跑 */}
          {(data.prediction?.total ?? 0) + (data.recommendation?.total ?? 0) > 0 ? (
            <div className="flex items-center gap-2 rounded-lg border border-brand/30 bg-brand/5 px-3 py-2 text-xs text-brand-light">
              <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-brand-light" />
              闭环运行中 · 已结算 {data.prediction?.total ?? 0} 次预测 + {data.recommendation?.total ?? 0} 只推荐
            </div>
          ) : (
            <div className="rounded-lg border border-slate-700 bg-slate-800/40 px-3 py-2 text-xs text-ink-muted">
              闭环待启动 · 首次结算将在今日收盘后自动执行
            </div>
          )}

          {/* 大盘预测胜率 */}
          <div>
            <div className="mb-1.5 text-xs font-semibold text-ink-muted">
              {data.prediction?.caliber?.name ?? "大盘推衍命中率"}
            </div>
            {data.prediction && data.prediction.total > 0 ? (
              <div className="grid grid-cols-3 gap-2">
                <StatTile value={data.prediction.total} label="已结算" />
                <StatTile value={data.prediction.hit} label="命中" />
                <StatTile
                  value={data.prediction.hit_rate != null ? `${data.prediction.hit_rate}%` : "-"}
                  label="命中率"
                  valueClass={pctTone(data.prediction.hit_rate)}
                />
              </div>
            ) : (
              <div className="rounded-lg bg-slate-800/40 px-3 py-2 text-xs text-ink-faint">
                暂无数据 · 每日收盘后自动结算（今日收盘后回来看第一批结果）
              </div>
            )}
            {data.prediction && Object.keys(data.prediction.by_direction || {}).length > 0 && (
              <div className="mt-2 flex flex-wrap gap-2 text-xs">
                {Object.entries(safeObj<Record<string, { hit?: number; total?: number; hit_rate?: number }>>(data.prediction.by_direction, {})).map(([d, b]) => (
                  <span key={d} className="rounded bg-slate-800/70 px-2 py-1 text-ink-muted">
                    {d} {b.hit}/{b.total}（{b.hit_rate ?? "-"}%）
                  </span>
                ))}
              </div>
            )}
            {data.prediction?.sample_status === "insufficient" && data.prediction.total > 0 && (
              <p className="mt-2 text-xs text-amber-400">样本不足 30 次，当前命中率只用于观察，不代表稳定能力。</p>
            )}
            {data.prediction && (
              <div className="mt-2">
                <CaliberLine caliber={data.prediction.caliber} />
              </div>
            )}
          </div>

          {/* 个股推荐胜率 */}
          <div>
            <div className="mb-1.5 text-xs font-semibold text-ink-muted">
              {data.recommendation?.caliber?.name ?? "每日推荐次日胜率"}
            </div>
            {data.recommendation && data.recommendation.total > 0 ? (
              <div className="grid grid-cols-3 gap-2">
                <StatTile value={data.recommendation.total} label="已结算" />
                <StatTile value={data.recommendation.hit} label="次日上涨" />
                <StatTile
                  value={data.recommendation.hit_rate != null ? `${data.recommendation.hit_rate}%` : "-"}
                  label="次日胜率"
                  valueClass={pctTone(data.recommendation.hit_rate)}
                />
              </div>
            ) : (
              <div className="rounded-lg bg-slate-800/40 px-3 py-2 text-xs text-ink-faint">
                暂无数据 · 每日收盘后自动结算（推荐生成后次日判定涨跌）
              </div>
            )}
            {data.recommendation?.sample_status === "insufficient" && data.recommendation.total > 0 && (
              <p className="mt-2 text-xs text-amber-400">样本不足 30 只，暂不据此判断策略有效性。</p>
            )}
            {data.recommendation && (
              <div className="mt-2">
                <CaliberLine caliber={data.recommendation.caliber} />
              </div>
            )}
          </div>

          <CaliberIncomparabilityNote note={data.caliber_note} />

          <p className="text-xs text-ink-faint">
            数据由每日收盘后的定时任务自动结算。数据积累越多，胜率越有参考价值；
            这里的两个数字与「策略回测」「形态回测」的胜率口径不同，不可横向比较。
          </p>
        </div>
      )}
    </CollapsiblePanel>
  );
}
