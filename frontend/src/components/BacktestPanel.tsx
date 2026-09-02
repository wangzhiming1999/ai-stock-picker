import { useEffect, useRef, useState } from "react";
import * as echarts from "echarts";
import { runBacktest } from "../api/client";
import type { BacktestResult } from "../types";

const STRATEGIES = [
  { name: "momentum", label: "动量", desc: "近20日涨幅选股" },
  { name: "trend", label: "趋势", desc: "均线多头排列" },
  { name: "value", label: "低估值", desc: "60日区间低位" },
  { name: "volume", label: "放量", desc: "量能温和放大" },
  { name: "all", label: "综合", desc: "多信号加权" },
];

export default function BacktestPanel() {
  const [strategy, setStrategy] = useState("momentum");
  const [startDate, setStartDate] = useState("2025-01-01");
  const [topN, setTopN] = useState("5");
  const [rebalance, setRebalance] = useState("5");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [err, setErr] = useState("");
  const chartRef = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!chartRef.current) return;
    chart.current = echarts.init(chartRef.current);
    const onResize = () => chart.current?.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.current?.dispose();
    };
  }, []);

  useEffect(() => {
    if (!chart.current || !result) return;
    const dates = result.equity_curve.map((p) => p.date);
    const values = result.equity_curve.map((p) => p.value);
    const base = result.initial_capital;
    // 基准曲线（按总收益线性近似）
    const bench = result.benchmark_return != null ? result.equity_curve.map(() => base * (1 + result.benchmark_return! / 100)) : [];

    chart.current.setOption({
      tooltip: { trigger: "axis", backgroundColor: "rgba(15,23,42,0.95)", borderColor: "#334155", textStyle: { color: "#e2e8f0" } },
      legend: { data: ["策略", ...(bench.length ? ["基准"] : [])], textStyle: { color: "#94a3b8" }, top: 0 },
      grid: { left: 60, right: 20, top: 30, bottom: 30 },
      xAxis: { type: "category", data: dates, axisLabel: { color: "#94a3b8", fontSize: 10 }, axisLine: { lineStyle: { color: "#475569" } } },
      yAxis: { type: "value", scale: true, axisLabel: { color: "#94a3b8" }, splitLine: { lineStyle: { color: "#1e293b" } } },
      series: [
        {
          name: "策略",
          type: "line",
          data: values,
          smooth: true,
          symbol: "none",
          lineStyle: { color: "#f59e0b", width: 2 },
          areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: "rgba(245,158,11,0.3)" }, { offset: 1, color: "rgba(245,158,11,0)" }]) },
        },
        ...(bench.length
          ? [
              {
                name: "基准",
                type: "line",
                data: bench,
                smooth: true,
                symbol: "none",
                lineStyle: { color: "#64748b", width: 1.5, type: "dashed" },
              },
            ]
          : []),
      ],
    });
  }, [result]);

  const run = async () => {
    setRunning(true);
    setErr("");
    setResult(null);
    try {
      const res = await runBacktest({
        strategy,
        start_date: startDate,
        end_date: "",
        top_n: parseInt(topN) || 5,
        rebalance_days: parseInt(rebalance) || 5,
      });
      setResult(res);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setRunning(false);
    }
  };

  const fmt = (v: number | null | undefined) => (v == null ? "-" : v.toFixed(2));

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-200">策略回测</h3>
          <p className="mt-0.5 text-[11px] text-slate-500">用历史数据验证策略胜率（默认股票池 28 只）</p>
        </div>
        <button
          onClick={() => void run()}
          disabled={running}
          className="rounded-lg bg-brand px-5 py-2 text-sm font-medium text-white hover:bg-brand-dark disabled:opacity-50"
        >
          {running ? "回测中..." : "开始回测"}
        </button>
      </div>

      {/* 参数区 */}
      <div className="mb-4 flex flex-wrap items-end gap-4">
        <div>
          <span className="mb-1 block text-xs text-slate-500">策略</span>
          <div className="flex gap-1 rounded-lg border border-slate-700 bg-slate-800/60 p-1">
            {STRATEGIES.map((s) => (
              <button
                key={s.name}
                onClick={() => setStrategy(s.name)}
                title={s.desc}
                className={`rounded-md px-3 py-1 text-xs transition-colors ${strategy === s.name ? "bg-brand text-white" : "text-slate-400 hover:text-slate-200"}`}
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>
        <label className="block">
          <span className="mb-1 block text-xs text-slate-500">开始日期</span>
          <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="rounded-lg border border-slate-700 bg-slate-800/80 px-2 py-1.5 text-xs text-slate-200" />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs text-slate-500">每期持仓数</span>
          <input value={topN} onChange={(e) => setTopN(e.target.value)} className="w-16 rounded-lg border border-slate-700 bg-slate-800/80 px-2 py-1.5 text-xs text-slate-200" />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs text-slate-500">调仓周期(交易日)</span>
          <input value={rebalance} onChange={(e) => setRebalance(e.target.value)} className="w-16 rounded-lg border border-slate-700 bg-slate-800/80 px-2 py-1.5 text-xs text-slate-200" />
        </label>
      </div>

      {err && <div className="mb-3 rounded-lg border border-red-800 bg-red-950/40 px-3 py-2 text-sm text-red-300">{err}</div>}

      {running && <div className="rounded-lg bg-slate-800/50 px-3 py-2 text-sm text-slate-400">回测运行中（拉取历史K线 + 模拟调仓）...</div>}

      {result && (
        <div className="space-y-4">
          {/* 指标卡片 */}
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
            <div className="rounded-lg bg-slate-800/50 px-2 py-2 text-center">
              <div className={`text-base font-bold ${result.total_return >= 0 ? "text-green-400" : "text-red-400"}`}>
                {result.total_return >= 0 ? "+" : ""}
                {result.total_return.toFixed(2)}%
              </div>
              <div className="text-[10px] text-slate-500">总收益</div>
            </div>
            <div className="rounded-lg bg-slate-800/50 px-2 py-2 text-center">
              <div className={`text-base font-bold ${result.annual_return >= 0 ? "text-green-400" : "text-red-400"}`}>
                {result.annual_return >= 0 ? "+" : ""}
                {result.annual_return.toFixed(2)}%
              </div>
              <div className="text-[10px] text-slate-500">年化</div>
            </div>
            <div className="rounded-lg bg-slate-800/50 px-2 py-2 text-center">
              <div className="text-base font-bold text-red-400">-{result.max_drawdown.toFixed(2)}%</div>
              <div className="text-[10px] text-slate-500">最大回撤</div>
            </div>
            <div className="rounded-lg bg-slate-800/50 px-2 py-2 text-center">
              <div className={`text-base font-bold ${result.sharpe >= 1 ? "text-green-400" : "text-slate-200"}`}>{fmt(result.sharpe)}</div>
              <div className="text-[10px] text-slate-500">夏普</div>
            </div>
            <div className="rounded-lg bg-slate-800/50 px-2 py-2 text-center">
              <div className={`text-base font-bold ${result.win_rate >= 50 ? "text-green-400" : "text-slate-200"}`}>{result.win_rate.toFixed(1)}%</div>
              <div className="text-[10px] text-slate-500">胜率</div>
            </div>
            <div className="rounded-lg bg-slate-800/50 px-2 py-2 text-center">
              <div className="text-base font-bold text-slate-200">{result.benchmark_return != null ? `${result.benchmark_return >= 0 ? "+" : ""}${result.benchmark_return.toFixed(2)}%` : "-"}</div>
              <div className="text-[10px] text-slate-500">基准(沪深300)</div>
            </div>
          </div>

          {/* 收益曲线 */}
          <div ref={chartRef} style={{ height: 280 }} className="w-full" />

          <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500">
            <span>区间 {result.start} ~ {result.end}</span>
            <span>股票池 {result.pool_size} 只</span>
            <span>调仓 {result.periods} 期</span>
            <span>期末 {result.final_value.toLocaleString()}</span>
            <span>初始 {result.initial_capital.toLocaleString()}</span>
          </div>
        </div>
      )}
    </div>
  );
}
