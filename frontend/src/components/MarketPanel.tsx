import { useCallback, useEffect, useState } from "react";
import { fetchIndustries, scanMarket, strategyScan } from "../api/client";
import DailyRecommendCard from "./DailyRecommendCard";
import PredictionCard from "./PredictionCard";
import WinratePanel from "./WinratePanel";
import type { Industry, ScanStock, StrategyDef, StrategyName, StrategyStock } from "../types";

interface Props {
  onPick: (codes: string[]) => void;
}

const STRATEGIES: StrategyDef[] = [
  { name: "momentum", label: "动量", desc: "站上MA5 + MACD多头 + RSI健康" },
  { name: "trend", label: "趋势", desc: "均线多头排列，顺势上行" },
  { name: "value", label: "低估值", desc: "PE/PB 合理，交投健康" },
  { name: "volume", label: "放量", desc: "量能活跃，温和上涨" },
];

export default function MarketPanel({ onPick }: Props) {
  const [industries, setIndustries] = useState<Industry[]>([]);
  const [indLoading, setIndLoading] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [scanResult, setScanResult] = useState<ScanStock[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [minChange, setMinChange] = useState("0");
  const [minAmount, setMinAmount] = useState("10");
  const [minPrice, setMinPrice] = useState("0");
  const [maxPrice, setMaxPrice] = useState("500");
  const [limit, setLimit] = useState("50");
  const [err, setErr] = useState("");

  // 策略选股状态
  const [strategy, setStrategy] = useState<StrategyName>("momentum");
  const [strategyRunning, setStrategyRunning] = useState(false);
  const [strategyResult, setStrategyResult] = useState<StrategyStock[]>([]);
  const [strategySelected, setStrategySelected] = useState<Set<string>>(new Set());

  const loadIndustries = useCallback(async () => {
    setIndLoading(true);
    setErr("");
    try {
      const list = await fetchIndustries();
      setIndustries(list);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setIndLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadIndustries();
  }, [loadIndustries]);

  const doScan = async () => {
    setScanning(true);
    setErr("");
    setScanResult([]);
    setSelected(new Set());
    try {
      const list = await scanMarket({
        min_price: parseFloat(minPrice) || 0,
        max_price: parseFloat(maxPrice) || 10000,
        min_change: parseFloat(minChange) || -100,
        max_change: 100,
        min_amount_yi: parseFloat(minAmount) || 0,
        max_pe: 1000,
        limit: parseInt(limit) || 50,
      });
      setScanResult(list);
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

  const runStrategy = async (s: StrategyName) => {
    setStrategy(s);
    setStrategyRunning(true);
    setErr("");
    setStrategyResult([]);
    setStrategySelected(new Set());
    try {
      const list = await strategyScan(s, 20, 3);
      setStrategyResult(list);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setStrategyRunning(false);
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

  return (
    <div className="space-y-5">
      {/* 每日收盘推荐 */}
      <DailyRecommendCard onPick={onPick} />

      {/* 明日大盘推衍 */}
      <PredictionCard />

      {/* 胜率看板 */}
      <WinratePanel />

      {/* 策略选股 */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-slate-200">策略选股</h3>
          {strategyResult.length > 0 && (
            <button
              onClick={pickStrategySelected}
              disabled={strategySelected.size === 0}
              className="rounded-lg bg-green-600 px-3 py-1 text-xs font-medium text-white hover:bg-green-500 disabled:opacity-40"
            >
              勾选 {strategySelected.size} 只去分析 →
            </button>
          )}
        </div>
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
                    <td className="px-3 py-1.5 text-right text-slate-300">{s.price.toFixed(2)}</td>
                    <td className={`px-3 py-1.5 text-right ${s.change_pct >= 0 ? "text-green-400" : "text-red-400"}`}>
                      {s.change_pct >= 0 ? "+" : ""}
                      {s.change_pct.toFixed(2)}%
                    </td>
                    <td className="px-3 py-1.5 text-right font-semibold text-brand">{s.strategy_score.toFixed(1)}</td>
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
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
        <h3 className="mb-3 text-sm font-semibold text-slate-200">行业板块（新浪行业）</h3>
        <div className="max-h-64 overflow-y-auto rounded-lg border border-slate-800">
          {indLoading && <div className="p-4 text-sm text-slate-500">加载中...</div>}
          {!indLoading && industries.length === 0 && (
            <div className="p-4 text-sm text-slate-500">暂无数据，点击下方按钮重新加载</div>
          )}
          {!indLoading && industries.length > 0 && (
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-slate-900 text-left text-xs text-slate-400">
                <tr>
                  <th className="px-3 py-2">板块</th>
                  <th className="px-3 py-2 text-right">家数</th>
                  <th className="px-3 py-2 text-right">涨跌幅</th>
                  <th className="px-3 py-2 text-right">平均价</th>
                </tr>
              </thead>
              <tbody>
                {industries.map((ind) => (
                  <tr key={ind.label} className="border-t border-slate-800/60 hover:bg-slate-800/40">
                    <td className="px-3 py-1.5 text-slate-200">{ind.name}</td>
                    <td className="px-3 py-1.5 text-right text-slate-400">{ind.company_count}</td>
                    <td className={`px-3 py-1.5 text-right ${ind.change_pct >= 0 ? "text-green-400" : "text-red-400"}`}>
                      {ind.change_pct >= 0 ? "+" : ""}
                      {ind.change_pct.toFixed(2)}%
                    </td>
                    <td className="px-3 py-1.5 text-right text-slate-400">{ind.avg_price.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div className="mt-2 flex gap-2">
          <button onClick={() => void loadIndustries()} className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-400 hover:text-slate-200">
            刷新板块
          </button>
          <span className="text-xs text-slate-600 self-center">板块成分可配合下方扫描使用</span>
        </div>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
        <h3 className="mb-3 text-sm font-semibold text-slate-200">全市场扫描选股</h3>
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
                      <td className="px-3 py-1.5 text-right text-slate-300">{s.price.toFixed(2)}</td>
                      <td className={`px-3 py-1.5 text-right ${s.change_pct >= 0 ? "text-green-400" : "text-red-400"}`}>
                        {s.change_pct >= 0 ? "+" : ""}
                        {s.change_pct.toFixed(2)}%
                      </td>
                      <td className="px-3 py-1.5 text-right text-slate-400">{s.amount_yi.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
