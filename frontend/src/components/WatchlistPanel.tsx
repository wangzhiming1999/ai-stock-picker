import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { CalendarDays } from "lucide-react";
import { fetchDailyRecommend, fetchWatchlist, importToWatchlist, removeFromWatchlist } from "../api/client";
import { fmtDayLabel, isTodayCN } from "../lib/dates";
import { fmtNum, fmtPct } from "../lib/safe";
import { downTone, pnlTone, upTone } from "../lib/tone";
import type { DailyRecommendResult, WatchlistData } from "../types";
import { useAuth } from "../auth/AuthContext";
import Table, { Th } from "./ui/Table";
import Panel from "./ui/Panel";
import { CELL } from "../lib/ui";

interface Props {
  /** 触发分析：选中某只股票去深度分析 */
  onAnalyze: (code: string) => void;
}

export default function WatchlistPanel({ onAnalyze }: Props) {
  const { user } = useAuth();
  const [data, setData] = useState<WatchlistData | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [importing, setImporting] = useState(false);
  const [daily, setDaily] = useState<DailyRecommendResult | null>(null);
  const [importMsg, setImportMsg] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setErr("");
    try {
      setData(await fetchWatchlist());
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (user) void load();
  }, [user, load]);

  // 拉取每日推荐（带日期），用于"导入每日推荐"的日期提示；失败静默不影响自选展示
  const loadDaily = useCallback(async () => {
    try {
      const d = await fetchDailyRecommend();
      if (d?.recommendations?.length) setDaily(d);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    if (user) void loadDaily();
  }, [user, loadDaily]);

  const doImportDaily = async () => {
    setImporting(true);
    setErr("");
    setImportMsg("");
    try {
      let recs = daily?.recommendations ?? [];
      if (!recs.length) {
        const d = await fetchDailyRecommend();
        setDaily(d);
        recs = d?.recommendations ?? [];
      }
      const codes = recs.map((r) => r.code).filter(Boolean);
      if (!codes.length) {
        setImportMsg("暂无推荐数据，请先刷新每日推荐");
        return;
      }
      const r = await importToWatchlist(codes);
      setImportMsg(`导入成功：新增 ${r.added} 只${r.skipped ? `，跳过 ${r.skipped} 只（已在自选/无效）` : ""}`);
      await load();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setImporting(false);
    }
  };

  const remove = async (id: number, name: string) => {
    if (!window.confirm(`确认将「${name || id}」移出自选？`)) return;
    try {
      await removeFromWatchlist(id);
      toast.success(`已移出自选 ${name || id}`);
      await load();
    } catch (e) {
      setErr((e as Error).message);
      toast.error("移除失败", { description: (e as Error).message });
    }
  };

  const s = data?.summary;

  return (
    <Panel
      title="我的自选"
      actions={
        <>
          <button
            onClick={() => void doImportDaily()}
            disabled={importing}
            className="rounded-lg bg-brand px-3 py-1.5 text-meta font-medium text-white hover:bg-brand-dark"
          >
            {importing ? "导入中..." : "+ 导入每日推荐"}
          </button>
          <button onClick={() => void load()} className="rounded-lg border border-surface-line px-3 py-1.5 text-meta text-ink-muted hover:text-ink">
            刷新
          </button>
        </>
      }
    >
      {daily?.date && daily.recommendations.length > 0 && (
        <div className="mb-3 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-xl border border-surface-line bg-surface-inset/40 px-3 py-2 text-meta text-ink-muted">
          <CalendarDays className="h-3.5 w-3.5 shrink-0 text-ink-faint" aria-hidden />
          <span>
            可导入推荐基于 <span className="font-medium text-ink">{fmtDayLabel(daily.date)}</span> 收盘
            {daily.target_date && (
              <>
                <span className="mx-1.5 text-ink-faint">→</span>
                目标关注 <span className="font-medium text-amber-300">{fmtDayLabel(daily.target_date)}</span>
              </>
            )}
          </span>
          {isTodayCN(daily.date) ? (
            <span className="rounded-md bg-brand/10 px-1.5 py-0.5 text-meta text-brand-light">当日收盘</span>
          ) : (
            <span className="rounded-md bg-amber-500/10 px-1.5 py-0.5 text-meta text-amber-400">最近交易日</span>
          )}
        </div>
      )}
      {err && <div className="mb-3 rounded-lg border border-state-danger-line bg-state-danger-surface px-3 py-2 text-body text-state-danger-soft">{err}</div>}
      {importMsg && <div className="mb-3 rounded-lg border border-green-800 bg-green-950/40 px-3 py-2 text-body text-green-300">{importMsg}</div>}
      {loading && <div className="p-3 text-body text-ink-soft">加载中...</div>}

      {/* 汇总 */}
      {s && s.total > 0 && (
        <div className="mb-4 grid grid-cols-4 gap-2">
          <div className="rounded-lg bg-surface-inset/70 px-2 py-2 text-center">
            <div className="text-num font-bold text-ink">{s.total}</div>
            <div className="text-meta text-ink-muted">自选</div>
          </div>
          <div className="rounded-lg bg-surface-inset/70 px-2 py-2 text-center">
            <div className={`text-num font-bold ${upTone()}`}>{s.up}</div>
            <div className="text-meta text-ink-muted">上涨</div>
          </div>
          <div className="rounded-lg bg-surface-inset/70 px-2 py-2 text-center">
            <div className={`text-num font-bold ${downTone()}`}>{s.down}</div>
            <div className="text-meta text-ink-muted">下跌</div>
          </div>
          <div className="rounded-lg bg-surface-inset/70 px-2 py-2 text-center">
            <div className={`text-num font-bold ${pnlTone(s.avg_change)}`}>
              {s.avg_change != null ? fmtPct(s.avg_change) : "-"}
            </div>
            <div className="text-meta text-ink-muted">平均涨跌</div>
          </div>
        </div>
      )}

      {/* 列表 */}
      {data && data.watchlist.length > 0 ? (
        <Table label="自选股列表" maxHeight="none" head={
          <tr>
            <Th>名称</Th>
            <Th align="right">现价</Th>
            <Th align="right">涨跌幅</Th>
            <Th align="right">换手率</Th>
            <Th>状态</Th>
            <Th />
          </tr>
        }>
              {data.watchlist.map((w) => (
                <tr key={w.id} className="border-t border-surface-line-soft hover:bg-surface-inset/30">
                  <td className={CELL}>
                    <button onClick={() => onAnalyze(w.code)} className="text-left hover:text-brand-light">
                      <div className="font-medium text-ink">{w.name || w.code}</div>
                      <div className="text-meta text-ink-muted">{w.code}</div>
                    </button>
                  </td>
                  <td className={`${CELL} text-right ${pnlTone(w.change_pct)}`}>{fmtNum(w.price)}</td>
                  <td className={`${CELL} text-right font-medium ${pnlTone(w.change_pct)}`}>
                    {w.change_pct != null ? (w.change_pct >= 0 ? "+" : "") + w.change_pct.toFixed(2) + "%" : "-"}
                  </td>
                  <td className={`${CELL} text-right text-ink-muted`}>
                    {w.turnover != null ? `${w.turnover.toFixed(2)}%` : "-"}
                  </td>
                  <td className={CELL}>
                    {w.offline ? (
                      <span className="rounded-md bg-surface-inset px-1.5 py-0.5 text-meta text-ink-muted">停牌/无数据</span>
                    ) : w.change_pct != null && w.change_pct > 5 ? (
                      <span className="rounded-md bg-red-900/40 px-1.5 py-0.5 text-meta text-red-300">大涨</span>
                    ) : w.change_pct != null && w.change_pct < -5 ? (
                      <span className="rounded-md bg-green-900/40 px-1.5 py-0.5 text-meta text-green-300">大跌</span>
                    ) : (
                      <span className="text-ink-faint">-</span>
                    )}
                  </td>
                  <td className={CELL}>
                    <button onClick={() => void remove(w.id, w.name)} className="text-meta text-ink-muted hover:text-red-400" title="删除">
                      移除
                    </button>
                  </td>
                </tr>
              ))}
          </Table>
      ) : (
        <div className="rounded-lg bg-surface-inset/40 p-4 text-center text-body text-ink-soft">
          暂无自选股。点击"导入每日推荐"一键添加，或在下方扫描结果中加星。
        </div>
      )}
      <p className="mt-2 text-right text-meta text-ink-faint">行情为实时快照，仅供研究参考</p>
    </Panel>
  );
}
