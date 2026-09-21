import { useCallback } from "react";
import type { SimPerformance } from "../../types";

/** 收益折线（echarts，P1） */
export default function PerfChart({ data }: { data: SimPerformance }) {
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
            lineStyle: { color: "#2563eb", width: 2 },
            areaStyle: { color: "rgba(37,99,235,0.15)" },
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
  return <div ref={ref} className="mt-4 rounded-xl border border-surface-line bg-surface-panel p-2" />;
}
