import { useState } from "react";
import { toast } from "sonner";
import { fetchAuctionOpportunity, fetchClosingOpportunity, importToWatchlist, scanMarket, strategyScan } from "../api/client";
import { requestAuth } from "./WatchStar";
import { useAuth } from "../auth/AuthContext";
import { fmtNum } from "../lib/safe";
import CollapsiblePanel from "./CollapsiblePanel";
import BacktestPanel from "./BacktestPanel";
import MonitorPanel from "./MonitorPanel";
import TacticPanel from "./TacticPanel";
import WinratePanel from "./WinratePanel";
import type { OpportunityResult, ScanStock, StrategyDef, StrategyName, StrategyStock } from "../types";
import { getScanViewAction } from "./scanPanelLogic";
import type { ScanView } from "./scanPanelLogic";

interface Props {
  onPick: (codes: string[]) => void;
}

const STRATEGIES: StrategyDef[] = [
  { name: "trend", label: "稳健趋势", desc: "找走势稳定、均线向上的候选" },
  { name: "volume", label: "放量启动", desc: "找成交活跃、刚开始走强的候选" },
  { name: "momentum", label: "强势延续", desc: "找近期较强但不过热的候选" },
  { name: "value", label: "估值观察", desc: "找估值克制、交投正常的候选" },
];

export default function ScanPanel({ onPick }: Props) {
  const { user } = useAuth();
  const [scanView, setScanView] = useState<ScanView>("quick");

  // 批量加入自选（需登录）
  const importCodes = async (codes: string[]) => {
    if (!user) {
      requestAuth();
      return;
    }
    if (!codes.length) return;
    try {
      const r = await importToWatchlist(codes);
      toast.success(`已加入自选 ${r.added} 只${r.skipped ? `，跳过 ${r.skipped} 只` : ""}`);
    } catch (e) {
      toast.error("加入自选失败", { description: (e as Error).message });
    }
  };

  // 策略选股状态
  const [strategy, setStrategy] = useState<StrategyName>("momentum");
  const [strategyRunning, setStrategyRunning] = useState(false);
  const [strategyResult, setStrategyResult] = useState<StrategyStock[]>([]);
  const [strategySelected, setStrategySelected] = useState<Set<string>>(new Set());
  const [strategyAttempted, setStrategyAttempted] = useState(false);
  const [strategyError, setStrategyError] = useState("");

  // 全市场扫描状态
  const [scanning, setScanning] = useState(false);
  const [scanResult, setScanResult] = useState<ScanStock[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [minChange, setMinChange] = useState("0");
  const [minAmount, setMinAmount] = useState("10");
  const [minPrice, setMinPrice] = useState("0");
  const [maxPrice, setMaxPrice] = useState("500");
  const [limit, setLimit] = useState("50");
  const [err, setErr] = useState("");

  // 早盘竞价 / 尾盘机会状态
  const [auctionResult, setAuctionResult] = useState<OpportunityResult | null>(null);
  const [auctionLoading, setAuctionLoading] = useState(false);
  const [closingResult, setClosingResult] = useState<OpportunityResult | null>(null);
  const [closingLoading, setClosingLoading] = useState(false);
  const [opportunitySelected, setOpportunitySelected] = useState<Set<string>>(new Set());

  const runAuction = async (force = false) => {
    setAuctionLoading(true);
    setErr("");
    if (force) setAuctionResult(null);
    setOpportunitySelected(new Set());
    try {
      setAuctionResult(await fetchAuctionOpportunity(15, force));
    } catch (e) {
      toast.error("早盘竞价机会获取失败", { description: (e as Error).message });
    } finally {
      setAuctionLoading(false);
    }
  };

  const runClosing = async (force = false) => {
    setClosingLoading(true);
    setErr("");
    if (force) setClosingResult(null);
    setOpportunitySelected(new Set());
    try {
      setClosingResult(await fetchClosingOpportunity(15, force));
    } catch (e) {
      toast.error("尾盘机会获取失败", { description: (e as Error).message });
    } finally {
      setClosingLoading(false);
    }
  };

  const toggleOpportunity = (code: string) => {
    setOpportunitySelected((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  const pickOpportunitySelected = () => {
    if (opportunitySelected.size === 0) return;
    onPick(Array.from(opportunitySelected));
  };

  const runStrategy = async (s: StrategyName) => {
    setStrategy(s);
    setStrategyRunning(true);
    setStrategyAttempted(true);
    setStrategyError("");
    setErr("");
    setStrategyResult([]);
    setStrategySelected(new Set());
    try {
      // 用户手动点击 → 强制拉取最新行情，不走 5 分钟快照缓存
      setStrategyResult(await strategyScan(s, 20, 3, true));
    } catch (e) {
      const message = (e as Error).message || "行情服务暂时不可用，请稍后重试";
      setStrategyError(message);
      toast.error("策略选股失败", { description: message });
    } finally {
      setStrategyRunning(false);
    }
  };

  const selectScanView = (view: ScanView) => {
    setScanView(view);
    if (getScanViewAction(view, strategyResult.length > 0, strategyRunning) === "run-default") {
      void runStrategy("momentum");
    }
  };

  const toggleStrategy = (code: string) => {
    setStrategySelected((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  const pickStrategySelected = () => {
    if (strategySelected.size === 0) return;
    onPick(Array.from(strategySelected));
  };

  const doScan = async () => {
    setScanning(true);
    setErr("");
    setScanResult([]);
    setSelected(new Set());
    try {
      // 用户手动点击 → 强制拉取最新行情，不走 5 分钟快照缓存
      setScanResult(
        await scanMarket(
          {
            min_price: parseFloat(minPrice) || 0,
            max_price: parseFloat(maxPrice) || 10000,
            min_change: parseFloat(minChange) || -100,
            max_change: 100,
            min_amount_yi: parseFloat(minAmount) || 0,
            max_pe: 1000,
            limit: parseInt(limit) || 50,
          },
          true
        )
      );
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setScanning(false);
    }
  };

  const toggle = (code: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  const pickSelected = () => {
    if (selected.size === 0) return;
    onPick(Array.from(selected));
  };

  return (
    <div className="space-y-5">
      <section className="rounded-xl border border-slate-800 bg-gradient-to-br from-slate-900 to-slate-950 p-5">
        <p className="text-xs font-semibold text-brand">选股扫描</p>
        <h2 className="mt-1 text-xl font-bold text-white">你今天想找什么？</h2>
        <p className="mt-1 text-sm text-slate-400">先选一个目标。扫描结果只是候选池，进入深度分析确认后再决定是否操作。</p>
        <div className="mt-4 grid grid-cols-2 gap-2 lg:grid-cols-5">
          {([
            ["quick", "找今日候选", "新手建议从这里开始"],
            ["timing", "看早盘/尾盘", "只在对应时段使用"],
            ["monitor", "看我的盯盘", "检查已有关注标的"],
            ["tactics", "看实战形态", "按技巧找买卖点"],
            ["advanced", "自己设条件", "适合熟悉指标的用户"],
          ] as Array<[ScanView, string, string]>).map(([value, label, desc]) => (
            <button key={value} onClick={() => selectScanView(value)} disabled={value === "quick" && strategyRunning} aria-busy={value === "quick" && strategyRunning} className={`cursor-pointer rounded-lg border p-3 text-left transition disabled:cursor-wait disabled:opacity-70 ${scanView === value ? "border-brand bg-brand/10" : "border-slate-700 hover:border-slate-500"}`}>
              <div className="text-sm font-semibold text-slate-100">{label}</div>
              <div className="mt-0.5 text-[11px] text-slate-500">{value === "quick" && strategyRunning ? "正在筛选今日候选…" : desc}</div>
            </button>
          ))}
        </div>
      </section>

      {scanView === "monitor" && <MonitorPanel />}

      {scanView === "tactics" && <TacticPanel onPick={onPick} onImport={importCodes} />}

      {/* 早盘竞价机会（9:15-9:30） */}
      {scanView === "timing" && <>
      <CollapsiblePanel
        id="scan_auction"
        title="开盘前有哪些异动"
        subtitle="仅 9:15-9:30 使用 · 异动不等于可以买"
        action={
          auctionResult?.items?.length ? (
            <div className="flex items-center gap-2">
              <button
                onClick={() => void importCodes(auctionResult!.items.map((s) => s.code))}
                className="rounded-lg border border-slate-600 px-3 py-1 text-xs text-slate-300 hover:border-slate-400 hover:text-white"
              >
                全部加自选
              </button>
              <button
                onClick={pickOpportunitySelected}
                disabled={opportunitySelected.size === 0}
                className="rounded-lg bg-green-600 px-3 py-1 text-xs font-medium text-white hover:bg-green-500 disabled:opacity-40"
              >
                勾选 {opportunitySelected.size} 只去分析 →
              </button>
            </div>
          ) : undefined
        }
      >
        <button
          onClick={() => void runAuction(true)}
          disabled={auctionLoading}
          className="rounded-lg bg-amber-600 px-5 py-2 text-sm font-medium text-white hover:bg-amber-500 disabled:opacity-50"
        >
          {auctionLoading ? "扫描中..." : auctionResult?.cached ? "刷新缓存（强制重跑）" : "扫描早盘竞价（9:15-9:30）"}
        </button>
        {auctionResult?.cached && auctionResult.trade_date && (
          <div className="mt-2 text-[11px] text-slate-500">
            缓存 {auctionResult.trade_date} ·{" "}
            {auctionResult.generated_at ? new Date(auctionResult.generated_at).toLocaleTimeString() : "-"} 生成
          </div>
        )}
        {!auctionLoading && auctionResult?.needs_scan && (
          <div className="mt-3 rounded-lg border border-amber-800/60 bg-amber-950/20 p-3 text-xs text-amber-200">
            今日尚未生成早盘竞价机会。点击上方按钮生成（每交易日仅生成一次并缓存）。
          </div>
        )}
        {auctionResult?.items?.length ? (
          <div className="mt-4 max-h-96 overflow-y-auto rounded-lg border border-slate-800">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-slate-900 text-left text-xs text-slate-400">
                <tr>
                  <th className="px-3 py-2">勾选</th>
                  <th className="px-3 py-2">名称</th>
                  <th className="px-3 py-2">代码</th>
                  <th className="px-3 py-2 text-right">涨幅</th>
                  <th className="px-3 py-2 text-right">量比</th>
                  <th className="px-3 py-2 text-right">成交额(亿)</th>
                  <th className="px-3 py-2 text-right">评分</th>
                </tr>
              </thead>
              <tbody>
                {auctionResult.items.map((s) => (
                  <tr
                    key={s.code}
                    onClick={() => toggleOpportunity(s.code)}
                    className={`cursor-pointer border-t border-slate-800/60 hover:bg-slate-800/40 ${opportunitySelected.has(s.code) ? "bg-slate-800/70" : ""}`}
                  >
                    <td className="px-3 py-1.5">
                      <input type="checkbox" readOnly checked={opportunitySelected.has(s.code)} className="accent-brand" />
                    </td>
                    <td className="px-3 py-1.5 text-slate-200">{s.name}</td>
                    <td className="px-3 py-1.5 text-slate-500">{s.code}</td>
                    <td className={`px-3 py-1.5 text-right ${s.change_pct >= 0 ? "text-green-400" : "text-red-400"}`}>
                      {s.change_pct >= 0 ? "+" : ""}
                      {fmtNum(s.change_pct)}%
                    </td>
                    <td className="px-3 py-1.5 text-right text-amber-400 font-semibold">{fmtNum(s.volume_ratio)}</td>
                    <td className="px-3 py-1.5 text-right text-slate-400">{fmtNum(s.amount_yi)}</td>
                    <td className="px-3 py-1.5 text-right font-semibold text-brand">{fmtNum(s.score)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </CollapsiblePanel>

      {/* 尾盘机会（14:45-15:00） */}
      <CollapsiblePanel
        id="scan_closing"
        title="收盘前有哪些异动"
        subtitle="仅 14:45-15:00 使用 · 需防范尾盘诱多"
        action={
          closingResult?.items?.length ? (
            <div className="flex items-center gap-2">
              <button
                onClick={() => void importCodes(closingResult!.items.map((s) => s.code))}
                className="rounded-lg border border-slate-600 px-3 py-1 text-xs text-slate-300 hover:border-slate-400 hover:text-white"
              >
                全部加自选
              </button>
              <button
                onClick={pickOpportunitySelected}
                disabled={opportunitySelected.size === 0}
                className="rounded-lg bg-green-600 px-3 py-1 text-xs font-medium text-white hover:bg-green-500 disabled:opacity-40"
              >
                勾选 {opportunitySelected.size} 只去分析 →
              </button>
            </div>
          ) : undefined
        }
      >
        <button
          onClick={() => void runClosing(true)}
          disabled={closingLoading}
          className="rounded-lg bg-indigo-600 px-5 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
        >
          {closingLoading ? "扫描中..." : closingResult?.cached ? "刷新缓存（强制重跑）" : "扫描尾盘机会（14:45-15:00）"}
        </button>
        {closingResult?.cached && closingResult.trade_date && (
          <div className="mt-2 text-[11px] text-slate-500">
            缓存 {closingResult.trade_date} ·{" "}
            {closingResult.generated_at ? new Date(closingResult.generated_at).toLocaleTimeString() : "-"} 生成
          </div>
        )}
        {!closingLoading && closingResult?.needs_scan && (
          <div className="mt-3 rounded-lg border border-amber-800/60 bg-amber-950/20 p-3 text-xs text-amber-200">
            今日尚未生成尾盘机会。点击上方按钮生成（每交易日仅生成一次并缓存）。
          </div>
        )}
        {closingResult?.items?.length ? (
          <div className="mt-4 max-h-96 overflow-y-auto rounded-lg border border-slate-800">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-slate-900 text-left text-xs text-slate-400">
                <tr>
                  <th className="px-3 py-2">勾选</th>
                  <th className="px-3 py-2">名称</th>
                  <th className="px-3 py-2">代码</th>
                  <th className="px-3 py-2 text-right">涨幅</th>
                  <th className="px-3 py-2 text-right">5分</th>
                  <th className="px-3 py-2 text-right">量比</th>
                  <th className="px-3 py-2 text-right">换手%</th>
                  <th className="px-3 py-2 text-right">评分</th>
                </tr>
              </thead>
              <tbody>
                {closingResult.items.map((s) => (
                  <tr
                    key={s.code}
                    onClick={() => toggleOpportunity(s.code)}
                    className={`cursor-pointer border-t border-slate-800/60 hover:bg-slate-800/40 ${opportunitySelected.has(s.code) ? "bg-slate-800/70" : ""}`}
                  >
                    <td className="px-3 py-1.5">
                      <input type="checkbox" readOnly checked={opportunitySelected.has(s.code)} className="accent-brand" />
                    </td>
                    <td className="px-3 py-1.5 text-slate-200">{s.name}</td>
                    <td className="px-3 py-1.5 text-slate-500">{s.code}</td>
                    <td className={`px-3 py-1.5 text-right ${s.change_pct >= 0 ? "text-green-400" : "text-red-400"}`}>
                      {s.change_pct >= 0 ? "+" : ""}
                      {fmtNum(s.change_pct)}%
                    </td>
                    <td className="px-3 py-1.5 text-right text-emerald-400 font-semibold">
                      {s.change_5min >= 0 ? "+" : ""}
                      {fmtNum(s.change_5min)}%
                    </td>
                    <td className="px-3 py-1.5 text-right text-amber-400">{fmtNum(s.volume_ratio)}</td>
                    <td className="px-3 py-1.5 text-right text-slate-400">{fmtNum(s.turnover)}</td>
                    <td className="px-3 py-1.5 text-right font-semibold text-brand">{fmtNum(s.score)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </CollapsiblePanel>
      </>}

      {scanView === "quick" && (
      <CollapsiblePanel
        id="scan_strategy"
        title="一键找候选"
        subtitle="选择一种目标，系统会拉取最新行情并给出候选理由"
        action={
          strategyResult.length > 0 ? (
            <div className="flex items-center gap-2">
              <button
                onClick={() => void importCodes(strategyResult.map((s) => s.code))}
                className="rounded-lg border border-slate-600 px-3 py-1 text-xs text-slate-300 hover:border-slate-400 hover:text-white"
              >
                全部加自选
              </button>
              <button
                onClick={pickStrategySelected}
                disabled={strategySelected.size === 0}
                className="rounded-lg bg-green-600 px-3 py-1 text-xs font-medium text-white hover:bg-green-500 disabled:opacity-40"
              >
                勾选 {strategySelected.size} 只去分析 →
              </button>
            </div>
          ) : undefined
        }
      >
        <div className="mb-4 grid grid-cols-2 gap-2 lg:grid-cols-4">
          {STRATEGIES.map((s) => (
            <button
              key={s.name}
              onClick={() => void runStrategy(s.name)}
              disabled={strategyRunning}
              className={`rounded-lg border p-3 text-left transition-colors ${
                strategy === s.name && strategyResult.length > 0
                  ? "border-brand bg-brand/10"
                  : "border-slate-700 hover:border-slate-500"
              }`}
            >
              <div className="text-sm font-medium text-slate-200">{s.label}</div>
              <div className="mt-0.5 text-xs text-slate-500">{s.desc}</div>
            </button>
          ))}
        </div>
        {strategyRunning && <div className="rounded-lg bg-slate-800/50 px-3 py-2 text-sm text-slate-400">策略扫描中（拉取行情与K线计算指标）...</div>}
        {!strategyRunning && strategyError && (
          <div role="alert" className="rounded-lg border border-red-800 bg-red-950/40 px-3 py-2 text-sm text-red-300">
            今日候选筛选失败：{strategyError}
            <button onClick={() => void runStrategy(strategy)} className="ml-3 cursor-pointer font-medium text-red-200 underline">重新筛选</button>
          </div>
        )}
        {!strategyRunning && strategyAttempted && !strategyError && strategyResult.length === 0 && (
          <div role="status" className="rounded-lg border border-slate-700 bg-slate-800/40 px-3 py-3 text-sm text-slate-300">
            当前条件没有筛出候选。可以换一个策略，或稍后等行情更新后重试。
          </div>
        )}
        {!strategyRunning && strategyResult.length > 0 && (
          <div className="max-h-96 overflow-y-auto rounded-lg border border-slate-800">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-slate-900 text-left text-xs text-slate-400">
                <tr>
                  <th className="px-3 py-2">勾选</th>
                  <th className="px-3 py-2">名称</th>
                  <th className="px-3 py-2">代码</th>
                  <th className="px-3 py-2 text-right">价格</th>
                  <th className="px-3 py-2 text-right">涨跌幅</th>
                  <th className="px-3 py-2">策略分</th>
                  <th className="px-3 py-2">信号</th>
                </tr>
              </thead>
              <tbody>
                {strategyResult.map((s) => (
                  <tr
                    key={s.code}
                    className={`cursor-pointer border-t border-slate-800/60 hover:bg-slate-800/40 ${
                      strategySelected.has(s.code) ? "bg-slate-800/70" : ""
                    }`}
                    onClick={() => toggleStrategy(s.code)}
                  >
                    <td className="px-3 py-1.5">
                      <input type="checkbox" readOnly checked={strategySelected.has(s.code)} className="accent-brand" />
                    </td>
                    <td className="px-3 py-1.5 text-slate-200">{s.name}</td>
                    <td className="px-3 py-1.5 text-slate-500">{s.code}</td>
                    <td className="px-3 py-1.5 text-right text-slate-300">{fmtNum(s.price)}</td>
                    <td className={`px-3 py-1.5 text-right ${s.change_pct >= 0 ? "text-green-400" : "text-red-400"}`}>
                      {s.change_pct >= 0 ? "+" : ""}
                      {fmtNum(s.change_pct)}%
                    </td>
                    <td className="px-3 py-1.5 text-right font-semibold text-brand">{fmtNum(s.strategy_score, 1)}</td>
                    <td className="px-3 py-1.5">
                      <div className="flex flex-wrap gap-1">
                        {s.tags.map((t, i) => (
                          <span key={i} className="rounded bg-slate-800 px-1.5 py-0.5 text-[11px] text-slate-300">
                            {t}
                          </span>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CollapsiblePanel>
      )}

      {scanView === "advanced" && <>
      <CollapsiblePanel
        id="scan_market"
        title="按条件筛选"
        subtitle="这里只按价格、涨幅和成交额过滤，不代表技术形态已经确认"
      >
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          <label className="block">
            <span className="mb-1 block text-xs text-slate-500">最低涨幅 %</span>
            <input value={minChange} onChange={(e) => setMinChange(e.target.value)} className="w-full rounded-lg border border-slate-700 bg-slate-800/80 px-3 py-1.5 text-sm outline-none focus:border-brand" />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-slate-500">最低成交额(亿)</span>
            <input value={minAmount} onChange={(e) => setMinAmount(e.target.value)} className="w-full rounded-lg border border-slate-700 bg-slate-800/80 px-3 py-1.5 text-sm outline-none focus:border-brand" />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-slate-500">最低股价</span>
            <input value={minPrice} onChange={(e) => setMinPrice(e.target.value)} className="w-full rounded-lg border border-slate-700 bg-slate-800/80 px-3 py-1.5 text-sm outline-none focus:border-brand" />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-slate-500">最高股价</span>
            <input value={maxPrice} onChange={(e) => setMaxPrice(e.target.value)} className="w-full rounded-lg border border-slate-700 bg-slate-800/80 px-3 py-1.5 text-sm outline-none focus:border-brand" />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-slate-500">数量上限</span>
            <input value={limit} onChange={(e) => setLimit(e.target.value)} className="w-full rounded-lg border border-slate-700 bg-slate-800/80 px-3 py-1.5 text-sm outline-none focus:border-brand" />
          </label>
        </div>
        <button
          onClick={() => void doScan()}
          disabled={scanning}
          className="mt-4 rounded-lg bg-brand px-6 py-2 text-sm font-medium text-white hover:bg-brand-dark disabled:opacity-50"
        >
          {scanning ? "扫描中..." : "开始扫描"}
        </button>

        {err && <div className="mt-3 rounded-lg border border-red-800 bg-red-950/40 px-3 py-2 text-sm text-red-300">{err}</div>}

        {scanResult.length > 0 && (
          <div className="mt-4">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm text-slate-400">扫描结果 {scanResult.length} 只（按成交额排序）</span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => void importCodes(scanResult.map((s) => s.code))}
                  className="rounded-lg border border-slate-600 px-3 py-1 text-xs text-slate-300 hover:border-slate-400 hover:text-white"
                >
                  全部加自选
                </button>
                <button
                  onClick={pickSelected}
                  disabled={selected.size === 0}
                  className="rounded-lg bg-green-600 px-4 py-1.5 text-xs font-medium text-white hover:bg-green-500 disabled:opacity-40"
                >
                  勾选 {selected.size} 只去分析 →
                </button>
              </div>
            </div>
            <div className="max-h-96 overflow-y-auto rounded-lg border border-slate-800">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-slate-900 text-left text-xs text-slate-400">
                  <tr>
                    <th className="px-3 py-2">勾选</th>
                    <th className="px-3 py-2">名称</th>
                    <th className="px-3 py-2">代码</th>
                    <th className="px-3 py-2 text-right">价格</th>
                    <th className="px-3 py-2 text-right">涨跌幅</th>
                    <th className="px-3 py-2 text-right">成交额(亿)</th>
                  </tr>
                </thead>
                <tbody>
                  {scanResult.map((s) => (
                    <tr
                      key={s.code}
                      className={`cursor-pointer border-t border-slate-800/60 hover:bg-slate-800/40 ${selected.has(s.code) ? "bg-slate-800/70" : ""}`}
                      onClick={() => toggle(s.code)}
                    >
                      <td className="px-3 py-1.5">
                        <input type="checkbox" readOnly checked={selected.has(s.code)} className="accent-brand" />
                      </td>
                      <td className="px-3 py-1.5 text-slate-200">{s.name}</td>
                      <td className="px-3 py-1.5 text-slate-500">{s.code}</td>
                      <td className="px-3 py-1.5 text-right text-slate-300">{fmtNum(s.price)}</td>
                      <td className={`px-3 py-1.5 text-right ${s.change_pct >= 0 ? "text-green-400" : "text-red-400"}`}>
                        {s.change_pct >= 0 ? "+" : ""}
                        {fmtNum(s.change_pct)}%
                      </td>
                      <td className="px-3 py-1.5 text-right text-slate-400">{fmtNum(s.amount_yi)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </CollapsiblePanel>

      <WinratePanel />
      <BacktestPanel />
      </>}
    </div>
  );
}
