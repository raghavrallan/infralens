"use client";

import { useMemo, useState } from "react";
import type { MetricChart, MetricPoint } from "../lib/types";

const WIDTH = 760;
const HEIGHT = 250;
const PLOT = { left: 48, right: 14, top: 16, bottom: 36 };
// Keep every series visible against the light chart surface. The first series
// is intentionally near-black because it is the primary metric in most charts.
const COLORS = ["#17171a", "#4b4b55", "#72727b", "#8b5e3c", "#35637d"];

function formatValue(value: number) {
  if (Math.abs(value) >= 1000) return value.toLocaleString(undefined, { maximumFractionDigits: 1 });
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function formatTime(value?: string) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
}

function formatDetailedTime(value?: string) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false, timeZoneName: "short" });
}

function timestampOf(point?: MetricPoint) {
  if (!point?.t) return null;
  const value = Date.parse(point.t);
  return Number.isFinite(value) ? value : null;
}

function xFor(points: MetricPoint[], index: number, start: number | null, end: number | null) {
  const innerWidth = WIDTH - PLOT.left - PLOT.right;
  const timestamp = timestampOf(points[index]);
  const duration = start !== null && end !== null ? end - start : 0;
  const ratio = timestamp !== null && duration > 0 ? (timestamp - start!) / duration : points.length <= 1 ? 0.5 : index / (points.length - 1);
  return PLOT.left + Math.max(0, Math.min(1, ratio)) * innerWidth;
}

function pointFor(points: MetricPoint[], index: number, max: number, start: number | null, end: number | null) {
  const innerHeight = HEIGHT - PLOT.top - PLOT.bottom;
  const x = xFor(points, index, start, end);
  const y = PLOT.top + innerHeight - (points[index].v / max) * innerHeight;
  return { x, y };
}

function pathFor(points: MetricPoint[], max: number, start: number | null, end: number | null) {
  return points.map((_, index) => {
    const point = pointFor(points, index, max, start, end);
    return `${index === 0 ? "M" : "L"}${point.x.toFixed(2)} ${point.y.toFixed(2)}`;
  }).join(" ");
}

function nearestPoint(series: MetricPoint[], timestamp: number | null) {
  if (!series.length) return undefined;
  if (timestamp === null) return series[0];
  return series.reduce((nearest, point) => {
    const currentDistance = Math.abs((timestampOf(point) ?? timestamp) - timestamp);
    const nearestDistance = Math.abs((timestampOf(nearest) ?? timestamp) - timestamp);
    return currentDistance < nearestDistance ? point : nearest;
  });
}

function ChartCard({ chart }: { chart: MetricChart }) {
  const [kind, setKind] = useState<"line" | "bar">(chart.type === "bar" ? "bar" : "line");
  const [hoverRatio, setHoverRatio] = useState<number | null>(null);
  const series = chart.series.filter((item) => item.points.length > 0);
  const pointCount = Math.max(...series.map((item) => item.points.length), 0);
  const max = Math.max(...series.flatMap((item) => item.points.map((point) => point.v)), 0, 1);
  const innerWidth = WIDTH - PLOT.left - PLOT.right;
  const innerHeight = HEIGHT - PLOT.top - PLOT.bottom;
  const timestamps = series.flatMap((item) => item.points.map(timestampOf)).filter((value): value is number => value !== null);
  const start = timestamps.length ? Math.min(...timestamps) : null;
  const end = timestamps.length ? Math.max(...timestamps) : null;
  const hoverTimestamp = hoverRatio === null || start === null || end === null ? null : start + hoverRatio * (end - start);
  const tooltipPosition = hoverRatio !== null && hoverRatio < 0.18 ? "left" : hoverRatio !== null && hoverRatio > 0.82 ? "right" : "center";
  const yTicks = useMemo(() => [0, 0.25, 0.5, 0.75, 1].map((ratio) => ({ ratio, value: max * ratio })), [max]);

  if (!series.length) return null;

  return (
    <section className="chart" aria-label={chart.title}>
      <div className="chart-head">
        <div><div className="chart-title">{chart.title} <span className="chart-unit">{chart.unit || ""}</span></div><div className="chart-range">{start !== null && end !== null ? `${formatTime(new Date(start).toISOString())} – ${formatTime(new Date(end).toISOString())}` : "Timestamp unavailable"} · {Intl.DateTimeFormat().resolvedOptions().timeZone}</div></div>
        <div className="chart-toggle" role="group" aria-label="Chart type">
          <button type="button" className={`chart-btn${kind === "line" ? " active" : ""}`} onClick={() => setKind("line")}>Line</button>
          <button type="button" className={`chart-btn${kind === "bar" ? " active" : ""}`} onClick={() => setKind("bar")}>Bar</button>
        </div>
      </div>
      <div className="chart-plot" onMouseLeave={() => setHoverRatio(null)}>
        <svg className="chart-svg" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={`${chart.title} chart`} onMouseMove={(event) => {
          if (pointCount <= 1) return;
          const rect = event.currentTarget.getBoundingClientRect();
          const x = ((event.clientX - rect.left) / rect.width) * WIDTH;
          setHoverRatio(Math.max(0, Math.min(1, (x - PLOT.left) / innerWidth)));
        }}>
          {yTicks.map((tick) => {
            const y = PLOT.top + innerHeight - tick.ratio * innerHeight;
            return <g key={tick.ratio}><line className="chart-grid" x1={PLOT.left} x2={WIDTH - PLOT.right} y1={y} y2={y} /><text className="chart-ylabel" x={PLOT.left - 8} y={y + 3}>{formatValue(tick.value)}</text></g>;
          })}
          {kind === "line" ? series.map((item, seriesIndex) => <path key={item.name} d={pathFor(item.points, max, start, end)} fill="none" stroke={COLORS[seriesIndex % COLORS.length]} strokeWidth="2" vectorEffect="non-scaling-stroke" />) : series.map((item, seriesIndex) => item.points.map((point, index) => {
            const width = Math.max(2, innerWidth / Math.max(pointCount, 1) / series.length - 3);
            const groupWidth = innerWidth / Math.max(pointCount, 1);
            const x = xFor(item.points, index, start, end) - groupWidth / 2 + seriesIndex * (width + 2) + 2;
            const y = PLOT.top + innerHeight - (point.v / max) * innerHeight;
            return <rect key={`${item.name}-${index}`} x={x} y={y} width={width} height={PLOT.top + innerHeight - y} fill={COLORS[seriesIndex % COLORS.length]} />;
          }))}
          {hoverRatio !== null && <line className="chart-cursor" x1={PLOT.left + hoverRatio * innerWidth} x2={PLOT.left + hoverRatio * innerWidth} y1={PLOT.top} y2={PLOT.top + innerHeight} />}
          {Array.from({ length: Math.min(pointCount, 5) }).map((_, index, labels) => {
            const ratio = labels.length === 1 ? 0.5 : index / (labels.length - 1);
            const timestamp = start !== null && end !== null ? new Date(start + ratio * (end - start)).toISOString() : series[0]?.points[Math.round(ratio * (pointCount - 1))]?.t;
            return <text className="chart-xlabel" key={timestamp || index} x={PLOT.left + ratio * innerWidth} y={HEIGHT - 12}>{formatTime(timestamp)}</text>;
          })}
        </svg>
        {hoverRatio !== null && <div className={`chart-tooltip ${tooltipPosition}`} style={{ left: `${(PLOT.left + hoverRatio * innerWidth) / WIDTH * 100}%` }}><div className="tt-time">{hoverTimestamp !== null ? formatDetailedTime(new Date(hoverTimestamp).toISOString()) : "Timestamp unavailable"}</div>{series.map((item, index) => <div className="tt-row" key={item.name}><i style={{ background: COLORS[index % COLORS.length] }} /><span className="tt-name">{item.name}</span><span className="tt-val">{formatValue(nearestPoint(item.points, hoverTimestamp)?.v ?? 0)}{chart.unit || ""}</span></div>)}</div>}
      </div>
      <div className="chart-legend">{series.map((item, index) => <span className="chart-key" key={item.name}><i style={{ background: COLORS[index % COLORS.length] }} />{item.name}</span>)}</div>
    </section>
  );
}

export function MetricCharts({ charts }: { charts?: MetricChart[] }) {
  if (!charts?.length) return null;
  return <div className="metric-charts">{charts.map((chart, index) => <ChartCard chart={chart} key={`${chart.title}-${index}`} />)}</div>;
}
