import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import {
  fetchSimAccount,
  fetchSimPerformance,
  fetchSimPositions,
  fetchSimTrades,
  initSimAccount,
  resetSimAccount,
  simTrade,
} from "../api/client";
import type { SimAccount, SimPerformance, SimPosition, SimPositionsData, SimTradesData } from "../types";
import { useAuth } from "../auth/AuthContext";
import { fmtPct, safeNumber } from "../lib/safe";

/** 收益折线（echarts，P1） */
function PerfChart({ data }: { data: SimPerformance }) {
  if (!data.snapshots.length) return null;
  const el = document.createElement("div");
  el.style.width = "100%";
  el.style.height = "200px";
  const ref = useCallback((node: HTMLDivElement | null) => {
    if (!node) return;
    node.innerHTML = "";
    node.appendChild(el);
    void (async () => {
      const echarts = await import("echarts");
      const chart = echarts.init(el, undefined, { renderer: "canvas" });
      chart.setOption({
        grid: { left: 48, right: 12, top: 24, bottom: 24 },
        tooltip: { trigger: "axis" },
        xAxis: { type: "category", data: data.snapshots.map((s) => s.date), axisLabel: { color: "#94a3b8", fontSize: 10 } },
        yAxis: {
          type: "value",
          scale: true,
          axisLabel: { color: "#94a3b8", fontSize: 10, formatter: (v: number) => `${(v / 10000).toFixed(1)}万` },
          splitLine: { lineStyle: { color: "#1e293b" } },
        },
        series: [
          {
            name: "总资产",
            type: "line",
            data: data.snapshots.map((s) => s.total_value),
            smooth: true,
            showSymbol: false,
            lineStyle: { color: "#dc2626", width: 2 },
            areaStyle: { color: "rgba(220,38,38,0.15)" },
          },
        ],
      });
      const onResize = () => chart.resize();
      window.addEventListener("resize", onResize);
      return () => {
        window.removeEventListener("resize", onResize);
        chart.dispose();
      };
    })();
  }, [data]);
  return <div ref={ref} className="mt-4 rounded-lg border border-slate-800 bg-slate-900/40 p-2" />;
}

/** 买卖弹窗 */
function TradeModal({
  side,
  initialCode,
  onClose,
  onDone,
  cash,
}: {
  side: "buy" | "sell";
  initialCode: string;
  onClose: () => void;
  onDone: () => void;
  cash: number;
}) {
  const [code, setCode] = useState(initialCode);
  const [shares, setShares] = useState("");
  const [price, setPrice] = useState("");
  const [priceAuto, setPriceAuto] = useState(true);
  const [busy, setBusy] = useState(false);
  const isBuy = side === "buy";
  const sharesNum = parseInt(shares) || 0;
  const priceNum = parseFloat(price) || null;
  // 预估费用：佣金 max(0.025%,5) + 过户 0.001% +（卖）印花 0.05%
  const estFee = (() => {
    if (!sharesNum || !priceNum) return null;
    const notional = sharesNum * priceNum;
    const fee = Math.max(notional * 0.00025, 5) + notional * 0.00001 + (isBuy ? 0 : notional * 0.0005);
    return Math.round(fee * 100) / 100;
  })();

  const submit = async () => {
    if (!code || code.length !== 6 || !sharesNum) {
      toast.error("请填写代码与数量");
      return;
    }
    setBusy(true);
    try {
      const r = await simTrade({
        code,
        side,
        shares: sharesNum,
        price: priceAuto ? undefined : (priceNum ?? undefined),
        source: "manual",
      });
      toast.success(isBuy ? "模拟买入已成交" : "模拟卖出已成交", {
        description: `${code} ${sharesNum}股 @${(r.trade as { price?: number }).price ?? "-"}`,
      });
      onDone();
      onClose();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div className="w-full max-w-sm rounded-xl border border-slate-700 bg-slate-900 p-5" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <span className={`text-sm font-bold ${isBuy ? "text-red-400" : "text-green-400"}`}>
            {isBuy ? "模拟买入" : "模拟卖出"}
          </span>
          <button onClick={onClose} className="text-xs text-slate-500 hover:text-slate-300">关闭</button>
        </div>
        <div className="space-y-3">
          <label className="block">
            <span className="mb-1 block text-xs text-slate-500">股票代码</span>
            <input value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))} placeholder="6 位代码" disabled={!!initialCode} className="w-full rounded-lg border border-slate-700 bg-slate-800/80 px-3 py-1.5 text-sm disabled:opacity-60" />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-slate-500">数量（股，100 的整数倍）{!isBuy && <span className="ml-1 text-slate-600">· 可用现金 ¥{safeNumber(cash).toLocaleString()}</span>}</span>
            <input value={shares} onChange={(e) => setShares(e.target.value.replace(/\D/g, ""))} type="number" placeholder="如 100" className="w-full rounded-lg border border-slate-700 bg-slate-800/80 px-3 py-1.5 text-sm" />
          </label>
          <label className="block">
            <span className="mb-1 flex items-center justify-between text-xs text-slate-500">
              成交价
              <label className="flex items-center gap-1 text-slate-500">
                <input type="checkbox" checked={priceAuto} onChange={(e) => setPriceAuto(e.target.checked)} className="h-3 w-3 accent-brand" />
                用实时价
              </label>
            </span>
            <input value={price} onChange={(e) => setPrice(e.target.value)} type="number" step="0.01" disabled={priceAuto} placeholder={priceAuto ? "自动取实时行情" : "如 12.50"} className="w-full rounded-lg border border-slate-700 bg-slate-800/80 px-3 py-1.5 text-sm disabled:opacity-50" />
          </label>
          {estFee != null && (
            <p className="text-[11px] text-slate-500">
              预估费用 ¥{estFee.toFixed(2)} · 预计{isBuy ? "占用" : "回收"} ¥{((sharesNum * (priceNum ?? 0)) + (isBuy ? estFee : -estFee)).toFixed(2)}
            </p>
          )}
          {isBuy && estFee != null && priceNum && sharesNum * priceNum + estFee > cash && (
            <p className="text-[11px] text-red-400">现金不足</p>
          )}
          <div className="flex gap-2 pt-1">
            <button onClick={() => void submit()} disabled={busy} className={`flex-1 rounded-lg px-4 py-2 text-sm font-medium text-white disabled:opacity-50 ${isBuy ? "bg-red-600 hover:bg-red-500" : "bg-green-600 hover:bg-green-500"}`}>
              {busy ? "处理中..." : isBuy ? "买入" : "卖出"}
            </button>
            <button onClick={onClose} className="rounded-lg border border-slate-600 px-4 py-2 text-sm text-slate-400 hover:text-slate-200">取消</button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function SimPanel() {
  const { user } = useAuth();
  const [account, setAccount] = useState<SimAccount | null>(null);
  const [positions, setPositions] = useState<SimPositionsData | null>(null);
  const [trades, setTrades] = useState<SimTradesData | null>(null);
  const [perf, setPerf] = useState<SimPerformance | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [modal, setModal] = useState<{ side: "buy" | "sell"; code: string } | null>(null);
  const [initCapital, setInitCapital] = useState("100000");

  const load = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    setErr("");
    try {
      const [a, p, t, pf] = await Promise.all([
        fetchSimAccount(),
        fetchSimPositions().catch(() => null),
        fetchSimTrades(30).catch(() => null),
        fetchSimPerformance().catch(() => null),
      ]);
      setAccount(a);
      setPositions(p);
      setTrades(t);
      setPerf(pf);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    if (user) void load();
  }, [user, load]);

  if (!user) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 text-sm text-slate-400">
        请先登录后使用模拟盘（虚拟资金，按用户隔离）。
      </div>
    );
  }

  const doInit = async () => {
    const v = parseFloat(initCapital) || 100000;
    try {
      await initSimAccount(v);
      toast.success("模拟账户已初始化", { description: `本金 ¥${v.toLocaleString()} 已入账` });
      await load();
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  const doReset = async () => {
    if (!window.confirm("确认清零模拟账户？将删除全部模拟成交流水与收益快照，此操作不可恢复。")) return;
    if (!window.confirm("再次确认：真的要清零重来吗？")) return;
    try {
      await resetSimAccount();
      toast.success("模拟账户已重置");
      await load();
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  const pnlColor = (v: number | null | undefined) => (v == null ? "text-slate-500" : v >= 0 ? "text-red-400" : "text-green-400");
  const hasData = account && (account.positions_cnt > 0 || account.cash > 0 || (trades?.total ?? 0) > 0);

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-200">模拟盘</h3>
          <p className="mt-0.5 text-[11px] text-slate-500">虚拟资金实操验证 · A 股费用规则 · T+1</p>
        </div>
        <div className="flex items-center gap-2">
          {hasData && (
            <button onClick={() => void doReset()} className="rounded-lg border border-slate-600 px-3 py-1.5 text-xs font-medium text-slate-400 hover:border-red-400 hover:text-red-300" title="清零重来">
              重置
            </button>
          )}
          <button onClick={() => setModal({ side: "buy", code: "" })} className="rounded-lg bg-brand px-4 py-1.5 text-xs font-medium text-white hover:bg-brand-dark" disabled={!account}>
            + 模拟买入
          </button>
        </div>
      </div>

      {err && <div className="mb-3 rounded-lg border border-red-800 bg-red-950/40 px-3 py-2 text-sm text-red-300">{err}</div>}
      {loading && <div className="p-3 text-sm text-slate-500">加载中...</div>}

      {/* 未初始化 */}
      {account && !account.initialized && (
        <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4">
          <div className="text-sm font-medium text-slate-200">初始化模拟账户</div>
          <p className="mt-1 text-xs text-slate-500">设定虚拟本金开始模拟交易，建议 10 万（A 股一手 100 股）</p>
          <div className="mt-3 flex items-center gap-2">
            <input value={initCapital} onChange={(e) => setInitCapital(e.target.value.replace(/\D/g, ""))} className="w-32 rounded-lg border border-slate-700 bg-slate-800/80 px-3 py-1.5 text-sm" placeholder="100000" />
            <button onClick={() => void doInit()} className="rounded-lg bg-brand px-4 py-1.5 text-xs font-medium text-white hover:bg-brand-dark">开始模拟</button>
          </div>
        </div>
      )}

      {/* 账户四卡 */}
      {account && account.initialized && (
        <>
          <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
            <div className="rounded-lg bg-slate-800/50 px-3 py-2 text-center">
              <div className="text-lg font-bold text-slate-200">{safeNumber(account.total_value).toLocaleString()}</div>
              <div className="text-[11px] text-slate-500">总资产</div>
            </div>
            <div className="rounded-lg bg-slate-800/50 px-3 py-2 text-center">
              <div className="text-lg font-bold text-slate-200">{safeNumber(account.cash).toLocaleString()}</div>
              <div className="text-[11px] text-slate-500">可用现金</div>
            </div>
            <div className="rounded-lg bg-slate-800/50 px-3 py-2 text-center">
              <div className={`text-lg font-bold ${pnlColor(account.total_pnl)}`}>
                {account.total_pnl != null ? `${account.total_pnl >= 0 ? "+" : ""}${safeNumber(account.total_pnl).toLocaleString()}` : "-"}
              </div>
              <div className="text-[11px] text-slate-500">总盈亏</div>
            </div>
            <div className="rounded-lg bg-slate-800/50 px-3 py-2 text-center">
              <div className={`text-lg font-bold ${pnlColor(account.total_pnl_pct)}`}>{fmtPct(account.total_pnl_pct)}</div>
              <div className="text-[11px] text-slate-500">盈亏率</div>
            </div>
          </div>
          <div className="mb-3 flex gap-4 text-[11px] text-slate-500">
            <span>已实现盈亏 <span className={pnlColor(account.realized_pnl)}>{account.realized_pnl >= 0 ? "+" : ""}{safeNumber(account.realized_pnl)}</span></span>
            <span>未实现盈亏 <span className={pnlColor(account.unrealized_pnl)}>{account.unrealized_pnl >= 0 ? "+" : ""}{safeNumber(account.unrealized_pnl)}</span></span>
          </div>

          {/* 持仓列表 */}
          {positions && positions.positions.length > 0 && (
            <div className="mb-4 overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-slate-400">
                  <tr>
                    <th className="px-2 py-2">股票</th>
                    <th className="px-2 py-2 text-right">现价</th>
                    <th className="px-2 py-2 text-right">成本</th>
                    <th className="px-2 py-2 text-right">数量</th>
                    <th className="px-2 py-2 text-right">浮盈</th>
                    <th className="px-2 py-2 text-right"></th>
                  </tr>
                </thead>
                <tbody>
                  {positions.positions.map((p: SimPosition) => (
                    <tr key={p.code} className="border-t border-slate-800/60">
                      <td className="px-2 py-2">
                        <div className="font-medium text-slate-200">{p.name || p.code}</div>
                        <div className="text-[11px] text-slate-500">{p.code}</div>
                      </td>
                      <td className="px-2 py-2 text-right text-slate-300">{p.current_price?.toFixed(2) ?? "-"}</td>
                      <td className="px-2 py-2 text-right text-slate-400">{p.avg_cost?.toFixed(2)}</td>
                      <td className="px-2 py-2 text-right text-slate-400">{p.shares}</td>
                      <td className={`px-2 py-2 text-right ${pnlColor(p.pnl_pct)}`}>
                        {p.pnl_pct != null ? `${p.pnl_pct >= 0 ? "+" : ""}${p.pnl_pct.toFixed(2)}%` : "-"}
                      </td>
                      <td className="px-2 py-2 text-right">
                        <button onClick={() => setModal({ side: "sell", code: p.code })} className="rounded border border-slate-600 px-2 py-1 text-xs text-slate-300 hover:border-green-400 hover:text-green-300" title="模拟卖出">
                          卖出
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* 收益曲线（P1：有快照时展示） */}
          {perf && perf.snapshots.length > 1 && <PerfChart data={perf} />}

          {/* 成交记录 */}
          {trades && trades.trades.length > 0 && (
            <div className="mt-4 border-t border-slate-800 pt-3">
              <div className="mb-2 text-xs font-semibold text-slate-400">最近成交（{trades.total}）</div>
              <div className="max-h-48 space-y-1 overflow-y-auto">
                {trades.trades.map((t) => (
                  <div key={t.id} className="flex items-center justify-between rounded bg-slate-800/40 px-3 py-1.5 text-xs">
                    <span className="flex items-center gap-2">
                      <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${t.side === "buy" ? "bg-red-900/40 text-red-300" : "bg-green-900/40 text-green-300"}`}>
                        {t.side === "buy" ? "买" : "卖"}
                      </span>
                      <span className="text-slate-200">{t.name || t.code}</span>
                      <span className="text-slate-500">{t.shares}股 @ {t.price}</span>
                    </span>
                    <span className="text-slate-500">{(t.executed_at || "").slice(0, 16).replace("T", " ")}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {modal && (
        <TradeModal
          side={modal.side}
          initialCode={modal.code}
          cash={account?.cash ?? 0}
          onClose={() => setModal(null)}
          onDone={() => void load()}
        />
      )}
    </div>
  );
}
