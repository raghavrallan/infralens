"use client";

import { useMemo, useState } from "react";
import type { MetricChart, MetricPoint } from "../lib/types";

const WIDTH = 760;
const HEIGHT = 250;
const PLOT = { left: 48, right: 14, top: 16, bottom: 36 };
const COLORS = ["#f4f4f4", "#b5b5b5", "#8a8a8a", "#d99162", "#6fa8dc"];

function formatValue(value: number) {
  if (Math.abs(value) >= 1000) return value.toLocaleString(undefined, { maximumFractionDigits: 1 });
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function formatTime(value?: string) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function pointFor(points: MetricPoint[], index: number, max: number) {
  const innerWidth = WIDTH - PLOT.left - PLOT.right;
  const innerHeight = HEIGHT - PLOT.top - PLOT.bottom;
  const x = PLOT.left + (points.length <= 1 ? innerWidth / 2 : (index / (points.length - 1)) * innerWidth);
  const y = PLOT.top + innerHeight - (points[index].v / max) * innerHeight;
  return { x, y };
}

function pathFor(points: MetricPoint[], max: number) {
  return points.map((_, index) => {
    const point = pointFor(points, index, max);
    return `${index === 0 ? "M" : "L"}${point.x.toFixed(2)} ${point.y.toFixed(2)}`;
  }).join(" ");
}

function ChartCard({ chart }: { chart: MetricChart }) {
  const [kind, setKind] = useState<"line" | "bar">(chart.type === "bar" ? "bar" : "line");
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const series = chart.series.filter((item) => item.points.length > 0);
  const pointCount = Math.max(...series.map((item) => item.points.length), 0);
  const max = Math.max(...series.flatMap((item) => item.points.map((point) => point.v)), 0, 1);
  const innerWidth = WIDTH - PLOT.left - PLOT.right;
  const innerHeight = HEIGHT - PLOT.top - PLOT.bottom;
  const hoverPoint = hoverIndex === null ? null : series[0]?.points[Math.min(hoverIndex, (series[0]?.points.length || 1) - 1)];
  const tooltipLeft = hoverIndex === null || pointCount <= 1 ? 0 : `${(PLOT.left + (hoverIndex / (pointCount - 1)) * innerWidth) / WIDTH * 100}%`;
  const yTicks = useMemo(() => [0, 0.25, 0.5, 0.75, 1].map((ratio) => ({ ratio, value: max * ratio })), [max]);

  if (!series.length) return null;

  return (
    <section className="chart" aria-label={chart.title}>
      <div className="chart-head">
        <div className="chart-title">{chart.title} <span className="chart-unit">{chart.unit || ""}</span></div>
        <div className="chart-toggle" role="group" aria-label="Chart type">
          <button type="button" className={`chart-btn${kind === "line" ? " active" : ""}`} onClick={() => setKind("line")}>Line</button>
          <button type="button" className={`chart-btn${kind === "bar" ? " active" : ""}`} onClick={() => setKind("bar")}>Bar</button>
        </div>
      </div>
      <div className="chart-plot" onMouseLeave={() => setHoverIndex(null)}>
        <svg className="chart-svg" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={`${chart.title} chart`} onMouseMove={(event) => {
          if (pointCount <= 1) return;
          const rect = event.currentTarget.getBoundingClientRect();
          const x = ((event.clientX - rect.left) / rect.width) * WIDTH;
          const next = Math.round(((x - PLOT.left) / innerWidth) * (pointCount - 1));
          setHoverIndex(Math.max(0, Math.min(pointCount - 1, next)));
        }}>
          {yTicks.map((tick) => {
            const y = PLOT.top + innerHeight - tick.ratio * innerHeight;
            return <g key={tick.ratio}><line className="chart-grid" x1={PLOT.left} x2={WIDTH - PLOT.right} y1={y} y2={y} /><text className="chart-ylabel" x={PLOT.left - 8} y={y + 3}>{formatValue(tick.value)}</text></g>;
          })}
          {kind === "line" ? series.map((item, seriesIndex) => <path key={item.name} d={pathFor(item.points, max)} fill="none" stroke={COLORS[seriesIndex % COLORS.length]} strokeWidth="2" vectorEffect="non-scaling-stroke" />) : series.map((item, seriesIndex) => item.points.map((point, index) => {
            const width = Math.max(2, innerWidth / Math.max(pointCount, 1) / series.length - 3);
            const groupWidth = innerWidth / Math.max(pointCount, 1);
            const x = PLOT.left + index * groupWidth + seriesIndex * (width + 2) + 2;
            const y = PLOT.top + innerHeight - (point.v / max) * innerHeight;
            return <rect key={`${item.name}-${index}`} x={x} y={y} width={width} height={PLOT.top + innerHeight - y} fill={COLORS[seriesIndex % COLORS.length]} />;
          }))}
          {hoverIndex !== null && pointCount > 1 && <line className="chart-cursor" x1={PLOT.left + (hoverIndex / (pointCount - 1)) * innerWidth} x2={PLOT.left + (hoverIndex / (pointCount - 1)) * innerWidth} y1={PLOT.top} y2={PLOT.top + innerHeight} />}
          {Array.from({ length: Math.min(pointCount, 5) }).map((_, index, labels) => {
            const pointIndex = labels.length === 1 ? 0 : Math.round(index * (pointCount - 1) / (labels.length - 1));
            const x = PLOT.left + (pointIndex / Math.max(pointCount - 1, 1)) * innerWidth;
            return <text className="chart-xlabel" key={pointIndex} x={x} y={HEIGHT - 12}>{formatTime(series[0]?.points[pointIndex]?.t)}</text>;
          })}
        </svg>
        {hoverIndex !== null && hoverPoint && <div className="chart-tooltip" style={{ left: tooltipLeft }}><div className="tt-time">{formatTime(hoverPoint.t)}</div>{series.map((item, index) => <div className="tt-row" key={item.name}><i style={{ background: COLORS[index % COLORS.length] }} /><span className="tt-name">{item.name}</span><span className="tt-val">{formatValue(item.points[Math.min(hoverIndex, item.points.length - 1)]?.v ?? 0)}</span></div>)}</div>}
      </div>
      <div className="chart-legend">{series.map((item, index) => <span className="chart-key" key={item.name}><i style={{ background: COLORS[index % COLORS.length] }} />{item.name}</span>)}</div>
    </section>
  );
}

export function MetricCharts({ charts }: { charts?: MetricChart[] }) {
  if (!charts?.length) return null;
  return <div className="metric-charts">{charts.map((chart, index) => <ChartCard chart={chart} key={`${chart.title}-${index}`} />)}</div>;
}
