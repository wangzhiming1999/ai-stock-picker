import { useCallback, useEffect, useState } from "react";
import { fetchDailyRecommend, fetchWatchlist, importToWatchlist, removeFromWatchlist } from "../api/client";
import { fmtNum, fmtPct } from "../lib/safe";
import type { DailyRecommendResult, WatchlistData } from "../types";
import { useAuth } from "../auth/AuthContext";

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

  const remove = async (id: number) => {
    try {
      await removeFromWatchlist(id);
      await load();
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  const pnlColor = (v: number | null | undefined) => (v == null ? "text-slate-500" : v >= 0 ? "text-green-400" : "text-red-400");
  const s = data?.summary;

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-200">我的自选</h3>
          <p className="mt-0.5 text-[11px] text-slate-500">从推荐/扫描一键导入，跟踪自选股实时涨跌</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => void doImportDaily()}
            disabled={importing}
            className="rounded-lg bg-brand px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-dark disabled:opacity-50"
          >
            {importing ? "导入中..." : "+ 导入今日推荐"}
          </button>
          <button onClick={() => void load()} className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-400 hover:text-slate-200">
            刷新
          </button>
        </div>
      </div>

      {err && <div className="mb-3 rounded-lg border border-red-800 bg-red-950/40 px-3 py-2 text-sm text-red-300">{err}</div>}
      {importMsg && <div className="mb-3 rounded-lg border border-green-800 bg-green-950/40 px-3 py-2 text-sm text-green-300">{importMsg}</div>}
      {loading && <div className="p-3 text-sm text-slate-500">加载中...</div>}

      {/* 汇总 */}
      {s && s.total > 0 && (
        <div className="mb-4 grid grid-cols-4 gap-2">
          <div className="rounded-lg bg-slate-800/50 px-2 py-2 text-center">
            <div className="text-lg font-bold text-slate-200">{s.total}</div>
            <div className="text-[11px] text-slate-500">自选</div>
          </div>
          <div className="rounded-lg bg-slate-800/50 px-2 py-2 text-center">
            <div className="text-lg font-bold text-green-400">{s.up}</div>
            <div className="text-[11px] text-slate-500">上涨</div>
          </div>
          <div className="rounded-lg bg-slate-800/50 px-2 py-2 text-center">
            <div className="text-lg font-bold text-red-400">{s.down}</div>
            <div className="text-[11px] text-slate-500">下跌</div>
          </div>
          <div className="rounded-lg bg-slate-800/50 px-2 py-2 text-center">
            <div className={`text-lg font-bold ${s.avg_change != null && s.avg_change >= 0 ? "text-green-400" : "text-red-400"}`}>
              {s.avg_change != null ? fmtPct(s.avg_change) : "-"}
            </div>
            <div className="text-[11px] text-slate-500">平均涨跌</div>
          </div>
        </div>
      )}

      {/* 列表 */}
      {data && data.watchlist.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-slate-400">
              <tr>
                <th className="px-2 py-2">名称</th>
                <th className="px-2 py-2 text-right">现价</th>
                <th className="px-2 py-2 text-right">涨跌幅</th>
                <th className="px-2 py-2 text-right">换手率</th>
                <th className="px-2 py-2">状态</th>
                <th className="px-2 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {data.watchlist.map((w) => (
                <tr key={w.id} className="border-t border-slate-800/60 hover:bg-slate-800/30">
                  <td className="px-2 py-2">
                    <button onClick={() => onAnalyze(w.code)} className="text-left hover:text-brand">
                      <div className="font-medium text-slate-200">{w.name || w.code}</div>
                      <div className="text-[11px] text-slate-500">{w.code}</div>
                    </button>
                  </td>
                  <td className={`px-2 py-2 text-right ${pnlColor(w.change_pct)}`}>{fmtNum(w.price)}</td>
                  <td className={`px-2 py-2 text-right font-medium ${pnlColor(w.change_pct)}`}>
                    {w.change_pct != null ? (w.change_pct >= 0 ? "+" : "") + w.change_pct.toFixed(2) + "%" : "-"}
                  </td>
                  <td className="px-2 py-2 text-right text-slate-400">
                    {w.turnover != null ? `${w.turnover.toFixed(2)}%` : "-"}
                  </td>
                  <td className="px-2 py-2">
                    {w.offline ? (
                      <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[11px] text-slate-500">停牌/无数据</span>
                    ) : w.change_pct != null && w.change_pct > 5 ? (
                      <span className="rounded bg-red-900/40 px-1.5 py-0.5 text-[11px] text-red-300">大涨</span>
                    ) : w.change_pct != null && w.change_pct < -5 ? (
                      <span className="rounded bg-green-900/40 px-1.5 py-0.5 text-[11px] text-green-300">大跌</span>
                    ) : (
                      <span className="text-slate-600">-</span>
                    )}
                  </td>
                  <td className="px-2 py-2">
                    <button onClick={() => void remove(w.id)} className="text-xs text-slate-500 hover:text-red-400" title="删除">
                      移除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="rounded-lg bg-slate-800/40 p-4 text-center text-sm text-slate-500">
          暂无自选股。点击"导入今日推荐"一键添加，或在下方扫描结果中加星。
        </div>
      )}
      <p className="mt-2 text-right text-[11px] text-slate-600">行情为实时快照，仅供研究参考</p>
    </div>
  );
}
