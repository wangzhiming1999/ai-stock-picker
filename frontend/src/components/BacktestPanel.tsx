import { useEffect, useRef, useState } from "react";
import * as echarts from "echarts";
import { runBacktest, fetchBacktestPool } from "../api/client";
import CollapsiblePanel from "./ui/CollapsiblePanel";
import { CaliberLine } from "./CaliberNote";
import { safeArray, safeNumber } from "../lib/safe";
import { pctTone, pnlTone } from "../lib/tone";
import type { BacktestResult } from "../types";
import Input from "./ui/Input";
import Button from "./ui/Button";

const STRATEGIES = [
  { name: "quality_momentum", label: "质量动量", desc: "动量排序 + 趋势确认" },
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
  const [poolCodes, setPoolCodes] = useState<string[] | null>(null);
  const [customCodes, setCustomCodes] = useState("");
  const [showPool, setShowPool] = useState(false);
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
    fetchBacktestPool()
      .then((p) => setPoolCodes(p.codes))
      .catch(() => setPoolCodes(null));
  }, []);

  useEffect(() => {
    if (!chart.current || !result) return;
    const equity = safeArray<{ date: string; value: number }>(result.equity_curve);
    const dates = equity.map((p) => p.date);
    const values = equity.map((p) => p.value);
    const base = safeNumber(result.initial_capital);
    // 基准曲线（按总收益线性近似）
    const bench = result.benchmark_return != null ? equity.map(() => base * (1 + result.benchmark_return! / 100)) : [];

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
      const codes = customCodes.trim()
        ? customCodes.split(/[\s,]+/).map((s) => s.trim()).filter(Boolean)
        : undefined;
      const res = await runBacktest({
        strategy,
        start_date: startDate,
        end_date: "",
        top_n: parseInt(topN) || 5,
        rebalance_days: parseInt(rebalance) || 5,
        codes,
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
    <CollapsiblePanel
      id="backtest"
      title="策略回测"
      subtitle="用历史数据验证策略表现 · 胜率口径为「调仓期」，与形态/推荐胜率不可比"
      onToggle={() => setTimeout(() => chart.current?.resize(), 80)}
      action={
        <Button variant="primary" size="lg"
          onClick={() => void run()}
          disabled={running}
          >
          {running ? "回测中..." : "开始回测"}
        </Button>
      }
    >

      {/* 参数区 */}
      <div className="mb-4 flex flex-wrap items-end gap-4">
        <div>
          <span className="mb-1 block text-meta text-ink-muted">策略</span>
          <div className="flex gap-1 rounded-lg border border-surface-line bg-surface-inset/70 p-1">
            {STRATEGIES.map((s) => (
              <button
                key={s.name}
                onClick={() => setStrategy(s.name)}
                title={s.desc}
                className={`rounded-md px-3 py-1 text-meta transition-colors ${strategy === s.name ? "bg-brand text-white" : "text-ink-muted hover:text-ink"}`}
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>
        <label className="block">
          <span className="mb-1 block text-meta text-ink-muted">开始日期</span>
          <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="rounded-lg bg-surface-inset/70 px-2 py-1.5 text-meta" />
        </label>
        <label className="block">
          <span className="mb-1 block text-meta text-ink-muted">每期持仓数</span>
          <Input value={topN} onChange={(e) => setTopN(e.target.value)} className="w-16 rounded-lg bg-surface-inset/70 px-2 py-1.5 text-meta" />
        </label>
        <label className="block">
          <span className="mb-1 block text-meta text-ink-muted">调仓周期(交易日)</span>
          <Input value={rebalance} onChange={(e) => setRebalance(e.target.value)} className="w-16 rounded-lg bg-surface-inset/70 px-2 py-1.5 text-meta" />
        </label>
      </div>

      {/* 股票池：默认 18 只行业代表标的（来自 /api/backtest/pool）。留空即用默认池，可自定义覆盖。 */}
      <div className="mb-4 rounded-lg border border-surface-line bg-surface-panel/40 px-3 py-2">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-meta">
          <span className="text-ink-muted">股票池</span>
          {poolCodes ? (
            <button
              onClick={() => setShowPool((v) => !v)}
              className="text-brand-light hover:underline"
              title="查看/收起默认池"
            >
              默认 {poolCodes.length} 只行业代表标的{showPool ? " ▲" : " ▼"}
            </button>
          ) : (
            <span className="text-ink-muted">默认 18 只行业代表标的</span>
          )}
          <span className="text-ink-muted">· 自定义覆盖：</span>
          <Input
            value={customCodes}
            onChange={(e) => setCustomCodes(e.target.value)}
            placeholder="留空用默认池，逗号/空格分隔"
            className="w-64 rounded-lg bg-surface-inset/70 px-2 py-1 text-meta"
          />
          {customCodes.trim() && (
            <button
              onClick={() => setCustomCodes("")}
              className="text-ink-muted transition-colors hover:text-ink"
              title="恢复默认池"
            >
              重置
            </button>
          )}
        </div>
        {showPool && poolCodes && (
          <div className="mt-2 flex flex-wrap gap-1">
            {poolCodes.map((c) => (
              <span key={c} className="rounded-md bg-surface-inset px-1.5 py-0.5 font-mono text-micro text-ink-muted">{c}</span>
            ))}
          </div>
        )}
      </div>

      {err && <div className="mb-3 rounded-lg border border-state-danger-line bg-state-danger-surface px-3 py-2 text-body text-state-danger-soft">{err}</div>}

      {running && <div className="rounded-lg bg-surface-inset/70 px-3 py-2 text-body text-ink-muted">回测运行中（拉取历史K线 + 模拟调仓）...</div>}

      {result && (
        <div className="space-y-4">
          {/* 指标卡片 */}
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
            <div className="rounded-lg bg-surface-inset/70 px-2 py-2 text-center">
              <div className={`text-head font-bold ${pnlTone(result.total_return)}`}>
                {result.total_return >= 0 ? "+" : ""}
                {result.total_return.toFixed(2)}%
              </div>
              <div className="text-meta text-ink-muted">总收益</div>
            </div>
            <div className="rounded-lg bg-surface-inset/70 px-2 py-2 text-center">
              <div className={`text-head font-bold ${pnlTone(result.annual_return)}`}>
                {result.annual_return >= 0 ? "+" : ""}
                {result.annual_return.toFixed(2)}%
              </div>
              <div className="text-meta text-ink-muted">年化</div>
            </div>
            <div className="rounded-lg bg-surface-inset/70 px-2 py-2 text-center">
              <div className="text-head font-bold text-amber-400">-{result.max_drawdown.toFixed(2)}%</div>
              <div className="text-meta text-ink-muted">最大回撤</div>
            </div>
            <div className="rounded-lg bg-surface-inset/70 px-2 py-2 text-center">
              <div className={`text-head font-bold ${result.sharpe >= 1 ? "text-brand-light" : "text-ink-muted"}`}>{fmt(result.sharpe)}</div>
              <div className="text-meta text-ink-muted">夏普</div>
            </div>
            <div className="rounded-lg bg-surface-inset/70 px-2 py-2 text-center">
              <div className={`text-head font-bold ${pctTone(result.win_rate)}`}>{result.win_rate.toFixed(1)}%</div>
              <div className="text-meta text-ink-muted">期胜率</div>
            </div>
            <div className="rounded-lg bg-surface-inset/70 px-2 py-2 text-center">
              <div className="text-head font-bold text-ink">{result.benchmark_return != null ? `${result.benchmark_return >= 0 ? "+" : ""}${result.benchmark_return.toFixed(2)}%` : "-"}</div>
              <div className="text-meta text-ink-muted">基准(沪深300)</div>
            </div>
          </div>

          {/* 收益曲线 */}
          <div ref={chartRef} style={{ height: 280 }} className="w-full" />

          <div className="flex flex-wrap gap-x-4 gap-y-1 text-meta text-ink-soft">
            <span>区间 {result.start} ~ {result.end}</span>
            <span>股票池 {result.pool_size} 只</span>
            <span>调仓 {result.periods} 期</span>
            <span>期末 {result.final_value.toLocaleString()}</span>
            <span>初始 {result.initial_capital.toLocaleString()}</span>
          </div>

          {/* 基准为空时说明原因：只显示「-」会把「基准取数失败」读成「基准是 0」，
              而基准正好是判断这套策略跑赢没有的那一半。 */}
          {result.benchmark_return == null && result.benchmark_note && (
            <p className="mt-1 text-meta leading-relaxed text-amber-300/90">{result.benchmark_note}</p>
          )}

          {/* 口径随数据下发：这里的「胜率」样本单位是调仓期，不是个股，不能和形态/推荐胜率混算。
              不可比声明统一在「研究 · 证据台账」子页顶部展示一次。 */}
          <div className="mt-2">
            <CaliberLine caliber={result.caliber} />
          </div>
        </div>
      )}
    </CollapsiblePanel>
  );
}
