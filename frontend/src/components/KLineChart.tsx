import { useEffect, useMemo, useRef } from "react";
import * as echarts from "echarts";
import type { StockHistory } from "../types";
import { waveMarkTooltip, clampMarksToDates } from "./prediction/waveLogic";

interface Props {
  history?: StockHistory;
  height?: number;
  /**
   * 可选：图上标注点（波浪浪位等）。
   *
   * 坐标日期必须存在于 `history.dates` 中，否则会被忽略 —— 调用方的分析窗口
   * 可能比图上画的长（比如波浪用 180 根、图上只画 120 根），
   * 不对齐的话 ECharts 会把点画到坐标轴外或直接报错。
   */
  marks?: { date: string; price: number; label: string }[];
}

export default function KLineChart({ history, height = 220, marks }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  const alignedMarks = useMemo(
    () => (marks && history ? clampMarksToDates(marks, history.dates) : []),
    [marks, history],
  );

  useEffect(() => {
    if (!ref.current) return;
    chartRef.current = echarts.init(ref.current);
    const onResize = () => chartRef.current?.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chartRef.current?.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!chartRef.current) return;
    if (!history || history.closes.length === 0) {
      chartRef.current.clear();
      return;
    }

    const dates = history.dates;
    const closes = history.closes;
    const volumes = history.volumes ?? [];

    chartRef.current.setOption({
      tooltip: {
        trigger: "axis",
        backgroundColor: "rgba(15,23,42,0.95)",
        borderColor: "#334155",
        textStyle: { color: "#e2e8f0" },
      },
      grid: [
        { left: 50, right: 20, top: 10, height: "62%" },
        { left: 50, right: 20, top: "76%", height: "16%" },
      ],
      xAxis: [
        { type: "category", data: dates, boundaryGap: false, axisLine: { lineStyle: { color: "#475569" } }, axisLabel: { color: "#94a3b8" } },
        { type: "category", data: dates, boundaryGap: false, axisLine: { lineStyle: { color: "#475569" } }, axisLabel: { show: false }, splitLine: { show: false } },
      ],
      yAxis: [
        { type: "value", scale: true, axisLabel: { color: "#94a3b8" }, splitLine: { lineStyle: { color: "#1e293b" } } },
        { type: "value", axisLabel: { color: "#94a3b8" }, splitLine: { show: false } },
      ],
      series: [
        {
          name: "收盘价",
          type: "line",
          data: closes,
          smooth: true,
          symbol: "none",
          lineStyle: { color: "#f59e0b", width: 2 },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: "rgba(245,158,11,0.35)" },
              { offset: 1, color: "rgba(245,158,11,0)" },
            ]),
          },
          // 波浪浪位标注：标签落在每一浪的**终点**（波浪派的标准画法）
          markPoint: alignedMarks.length
            ? {
                symbol: "circle",
                symbolSize: 5,
                itemStyle: { color: "#f59e0b" },
                label: {
                  formatter: (p: { data?: { name?: string } }) => p.data?.name ?? "",
                  color: "#e2e8f0",
                  fontSize: 11,
                  position: "top",
                  distance: 6,
                },
                tooltip: { formatter: (p: { data?: { name?: string } }) => waveMarkTooltip(p.data?.name ?? "") },
                data: alignedMarks.map((m) => ({ name: m.label, coord: [m.date, m.price] })),
              }
            : undefined,
        },
        {
          name: "成交量",
          type: "bar",
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: volumes,
          itemStyle: { color: "#475569" },
        },
      ],
      dataZoom: [{ type: "inside", xAxisIndex: [0, 1], start: 40, end: 100 }],
    });
  }, [history, alignedMarks]);

  return <div ref={ref} style={{ height }} className="w-full" />;
}
