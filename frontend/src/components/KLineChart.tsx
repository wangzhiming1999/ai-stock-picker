import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import type { StockHistory } from "../types";

interface Props {
  history?: StockHistory;
  height?: number;
}

export default function KLineChart({ history, height = 220 }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

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
  }, [history]);

  return <div ref={ref} style={{ height }} className="w-full" />;
}
