"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { cash, money, num } from "@/lib/format";

const tip = {
  border: "none",
  borderRadius: 12,
  boxShadow: "0 8px 24px rgba(35,35,35,0.08)",
  fontSize: 12,
};

function axisLabel(value) {
  if (value >= 10000) return `${Math.round(value / 1000)}k`;
  if (value >= 1000) return `${Math.round(value / 100) / 10}k`;
  if (value >= 100) return `${Math.round(value)}`;
  return `${Math.round(value * 10) / 10}`;
}

function chartScale(peak) {
  const padded = Math.max(peak * 1.06, 1);
  const power = 10 ** Math.floor(Math.log10(padded / 4));
  const step = [1, 2, 2.5, 5, 10].map((n) => n * power).find((item) => Math.ceil(padded / item) <= 5) || power * 10;
  const max = Math.ceil((padded - 1e-6) / step) * step;
  const ticks = [];
  for (let value = 0; value <= max + step * 0.001; value += step) ticks.push(Math.round(value * 100) / 100);
  return { max, ticks };
}

function useChartWidth() {
  const ref = useRef(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const node = ref.current;
    if (!node) return undefined;
    const update = () => {
      const next = Math.floor(node.clientWidth);
      if (next > 0) setWidth(next);
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

function smoothPath(points) {
  const usable = points.filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y));
  if (!usable.length) return "";
  if (usable.length === 1) return `M${usable[0].x.toFixed(2)},${usable[0].y.toFixed(2)}`;
  points = usable;
  const slopes = [];
  for (let index = 0; index < points.length - 1; index += 1) {
    const run = points[index + 1].x - points[index].x || 1;
    slopes.push((points[index + 1].y - points[index].y) / run);
  }
  const tangent = points.map((_, index) => {
    if (index === 0) return slopes[0];
    if (index === points.length - 1) return slopes[slopes.length - 1];
    if (slopes[index - 1] * slopes[index] <= 0) return 0;
    return (slopes[index - 1] + slopes[index]) / 2;
  });
  for (let index = 0; index < slopes.length; index += 1) {
    if (Math.abs(slopes[index]) < 1e-6) {
      tangent[index] = 0;
      tangent[index + 1] = 0;
      continue;
    }
    const a = tangent[index] / slopes[index];
    const b = tangent[index + 1] / slopes[index];
    const scale = a * a + b * b;
    if (scale > 9) {
      const tau = 3 / Math.sqrt(scale);
      tangent[index] = tau * a * slopes[index];
      tangent[index + 1] = tau * b * slopes[index];
    }
  }
  let path = `M${points[0].x.toFixed(2)},${points[0].y.toFixed(2)}`;
  for (let index = 0; index < points.length - 1; index += 1) {
    const span = points[index + 1].x - points[index].x;
    const c1x = points[index].x + span / 3;
    const c1y = points[index].y + (tangent[index] * span) / 3;
    const c2x = points[index + 1].x - span / 3;
    const c2y = points[index + 1].y - (tangent[index + 1] * span) / 3;
    path += ` C${c1x.toFixed(2)},${c1y.toFixed(2)} ${c2x.toFixed(2)},${c2y.toFixed(2)} ${points[index + 1].x.toFixed(2)},${points[index + 1].y.toFixed(2)}`;
  }
  return path;
}

export function SpendArea({ data, xKey = "label", yKey = "spend", className = "h-52" }) {
  const [active, setActive] = useState(null);
  const fillId = useId().replace(/:/g, "");
  const [boxRef, measured] = useChartWidth();
  if (!data?.length) return null;
  const width = measured || 720;
  const height = 208;
  const pad = { l: 44, r: 8, t: 12, b: 28 };
  const peak = Math.max(...data.map((item) => Number(item[yKey]) || 0), 1);
  const scale = chartScale(peak);
  const max = scale.max;
  const innerW = width - pad.l - pad.r;
  const innerH = height - pad.t - pad.b;
  const xAt = (index) => pad.l + (data.length === 1 ? innerW / 2 : (index / (data.length - 1)) * innerW);
  const yAt = (value) => pad.t + innerH - (value / max) * innerH;
  const coords = data.map((item, index) => ({ x: xAt(index), y: yAt(Number(item[yKey]) || 0) }));
  const line = smoothPath(coords);
  const area = line ? `${line} L${coords.at(-1).x.toFixed(2)},${yAt(0).toFixed(2)} L${coords[0].x.toFixed(2)},${yAt(0).toFixed(2)} Z` : "";
  const step = data.length > 14 ? Math.ceil(data.length / 6) : 1;

  function move(event) {
    const bounds = event.currentTarget.getBoundingClientRect();
    const px = ((event.clientX - bounds.left) / bounds.width) * width;
    let nearest = 0;
    let best = Infinity;
    coords.forEach((point, index) => {
      const distance = Math.abs(point.x - px);
      if (distance < best) {
        best = distance;
        nearest = index;
      }
    });
    setActive(nearest);
  }

  return (
    <div ref={boxRef} className={`relative w-full min-w-0 ${className}`} onMouseLeave={() => setActive(null)}>
      <svg viewBox={`0 0 ${width} ${height}`} className={`block w-full ${className}`} preserveAspectRatio="none" onMouseMove={move}>
        <defs>
          <linearGradient id={fillId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#E2773C" stopOpacity="0.4" />
            <stop offset="62%" stopColor="#E2773C" stopOpacity="0.08" />
            <stop offset="100%" stopColor="#E2773C" stopOpacity="0" />
          </linearGradient>
        </defs>
        {scale.ticks.map((tick) => (
          <g key={tick}>
            <line x1={pad.l} x2={width - pad.r} y1={yAt(tick)} y2={yAt(tick)} stroke="#EFEDEA" />
            <text x={pad.l - 8} y={yAt(tick) + 4} textAnchor="end" fill="#717171" fontSize="12">
              {axisLabel(tick)}
            </text>
          </g>
        ))}
        {area ? <path d={area} fill={`url(#${fillId})`} stroke="none" /> : null}
        {line ? <path d={line} fill="none" stroke="#E2773C" strokeWidth="2.4" strokeLinejoin="round" strokeLinecap="round" /> : null}
        {data.length === 1 ? <circle cx={coords[0].x} cy={coords[0].y} r="4" fill="#E2773C" /> : null}
        {data.map((item, index) =>
          index % step === 0 || index === data.length - 1 ? (
            <text
              key={`${item[xKey]}-${index}`}
              x={xAt(index)}
              y={height - 8}
              textAnchor={index === 0 ? "start" : index === data.length - 1 ? "end" : "middle"}
              fill="#717171"
              fontSize="11"
            >
              {item[xKey]}
            </text>
          ) : null
        )}
        {active != null && (
          <circle cx={coords[active].x} cy={coords[active].y} r="4" fill="#E2773C" stroke="#fff" strokeWidth="2" />
        )}
      </svg>
      {active != null && (
        <div
          className="pointer-events-none absolute z-10 rounded-xl border border-line bg-white px-3 py-2 text-xs shadow-[0_8px_24px_rgba(35,35,35,0.08)]"
          style={{
            left: `${(coords[active].x / width) * 100}%`,
            top: `${(coords[active].y / height) * 100}%`,
            transform: "translate(-50%, -120%)",
          }}
        >
          <div className="font-semibold">{data[active][xKey]}</div>
          <div className="text-brand">{money(data[active][yKey])}</div>
        </div>
      )}
    </div>
  );
}

export function SplitDonut({ data, valueKey = "cost", format = money }) {
  return (
    <div className="mx-auto h-44 w-full max-w-[220px] min-w-0">
      <ResponsiveContainer width="100%" height="100%" minWidth={0}>
        <PieChart accessibilityLayer={false}>
          <Pie data={data} dataKey={valueKey} nameKey="name" innerRadius={46} outerRadius={68} paddingAngle={2} isAnimationActive={false}>
            {data.map((entry) => (
              <Cell key={entry.name} fill={entry.color} />
            ))}
          </Pie>
          <Tooltip formatter={(value) => format(value)} contentStyle={tip} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}

export function SpendColumns({ data, series, currency = "USD" }) {
  if (!data?.length || !series?.length) return null;
  return (
    <div className="h-64 w-full min-w-0">
      <ResponsiveContainer width="100%" height="100%" minWidth={0}>
        <BarChart data={data} barCategoryGap="18%">
          <CartesianGrid stroke="#EFEDEA" vertical={false} />
          <XAxis dataKey="label" tick={{ fontSize: 11, fill: "#717171" }} interval="preserveStartEnd" axisLine={false} tickLine={false} />
          <YAxis tick={{ fontSize: 11, fill: "#717171" }} width={48} axisLine={false} tickLine={false} />
          <Tooltip
            formatter={(value, name) => [cash(value, currency), name]}
            contentStyle={tip}
          />
          {series.map((item) => (
            <Bar key={item.key} dataKey={item.key} name={item.name} stackId="spend" fill={item.color} isAnimationActive={false} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function CostBars({ data, xKey = "name", fill = false }) {
  const max = Math.max(...data.map((item) => Number(item.cost) || 0), 1);
  return (
    <ul className={fill ? "flex h-full flex-col justify-evenly" : "space-y-3"}>
      {data.map((item) => {
        const label = item[xKey] || item.name;
        const width = Math.max(2, Math.round((Number(item.cost) / max) * 100));
        return (
          <li key={label} className="grid grid-cols-[minmax(5.5rem,8.5rem)_1fr_4.75rem] items-center gap-2">
            <span className="truncate text-xs text-muted" title={label}>
              {label}
            </span>
            <div className="h-2.5 rounded-full bg-canvas" title={money(item.cost)}>
              <div
                className="h-full rounded-full"
                style={{ width: `${width}%`, background: item.color || "#E2773C" }}
              />
            </div>
            <span className="text-right text-xs tabular-nums text-ink">{money(item.cost)}</span>
          </li>
        );
      })}
    </ul>
  );
}

export function RankBars({ data, valueKey = "value", fill = false, format = num }) {
  const max = Math.max(...data.map((item) => Number(item[valueKey]) || 0), 1);
  return (
    <ul className={fill ? "flex h-full flex-col justify-evenly" : "space-y-2.5"}>
      {data.map((item) => {
        const width = Math.max(2, Math.round(((Number(item[valueKey]) || 0) / max) * 100));
        const label = (
          <span className="truncate text-xs text-muted" title={item.name}>
            {item.name}
          </span>
        );
        return (
          <li key={item.name} className="grid grid-cols-[minmax(5.5rem,8.5rem)_1fr_2.5rem] items-center gap-2">
            {item.href ? <Link href={item.href} className="min-w-0 hover:text-brand">{label}</Link> : label}
            <div className="h-2.5 rounded-full bg-canvas">
              <div className="h-full rounded-full" style={{ width: `${width}%`, background: item.color || "#0084FF" }} />
            </div>
            <span className="text-right text-xs tabular-nums text-ink">{format(item[valueKey])}</span>
          </li>
        );
      })}
    </ul>
  );
}

export function LineBars({ data, xKey, yKey, color = "#0084FF" }) {
  return (
    <div className="h-56 w-full min-w-0">
      <ResponsiveContainer width="100%" height="100%" minWidth={0}>
        <BarChart accessibilityLayer={false} data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid stroke="#EFEDEA" vertical={false} />
          <XAxis dataKey={xKey} tick={{ fill: "#717171", fontSize: 12 }} axisLine={false} tickLine={false} />
          <YAxis tick={{ fill: "#717171", fontSize: 12 }} axisLine={false} tickLine={false} width={32} />
          <Tooltip contentStyle={tip} />
          <Bar dataKey={yKey} fill={color} radius={[6, 6, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

const DEFAULT_SERIES = [
  { key: "jobs", name: "Jobs", color: "#E2773C" },
  { key: "sql", name: "SQL", color: "#F2A365" },
  { key: "allPurpose", name: "All-purpose", color: "#0084FF" },
  { key: "serverless", name: "Serverless", color: "#0BAA60" },
];

export function UsageLines({ data, series = DEFAULT_SERIES, unit = "" }) {
  const [active, setActive] = useState(null);
  const [boxRef, measured] = useChartWidth();
  if (!data?.length || !series.length) return null;
  const width = measured || 720;
  const height = 224;
  const pad = { l: 4, r: 4, t: 10, b: 26 };
  const values = data.flatMap((row) => series.map((item) => Number(row[item.key]) || 0));
  const peak = Math.max(...values, 1);
  const floor = Math.min(...values);
  const span = Math.max(peak - floor, 1);
  const min = floor - span * 0.22;
  const max = peak + span * 0.12;
  const innerW = width - pad.l - pad.r;
  const innerH = height - pad.t - pad.b;
  const xAt = (index) => pad.l + (data.length === 1 ? innerW / 2 : (index / (data.length - 1)) * innerW);
  const yAt = (value) => pad.t + innerH - ((value - min) / (max - min)) * innerH;
  const grid = [0, 0.33, 0.66, 1].map((tick) => min + (max - min) * tick);
  const step = data.length > 10 ? Math.ceil(data.length / 6) : 1;
  const activeX = active == null ? 0 : xAt(active);
  const tipOnLeft = activeX > width * 0.62;

  function move(event) {
    const bounds = event.currentTarget.getBoundingClientRect();
    const px = ((event.clientX - bounds.left) / bounds.width) * width;
    let nearest = 0;
    let best = Infinity;
    data.forEach((_, index) => {
      const distance = Math.abs(xAt(index) - px);
      if (distance < best) {
        best = distance;
        nearest = index;
      }
    });
    setActive(nearest);
  }

  return (
    <div ref={boxRef} className="relative w-full min-w-0" onMouseLeave={() => setActive(null)}>
      <svg viewBox={`0 0 ${width} ${height}`} className="block h-56 w-full" onMouseMove={move}>
        {grid.map((tick) => (
          <line key={tick} x1={pad.l} x2={width - pad.r} y1={yAt(tick)} y2={yAt(tick)} stroke="#EFEDEA" />
        ))}
        {active != null && (
          <line x1={activeX} x2={activeX} y1={pad.t} y2={height - pad.b} stroke="#E4E1DC" strokeDasharray="3 3" />
        )}
        {series.map((item) => {
          const path = smoothPath(data.map((row, index) => ({ x: xAt(index), y: yAt(Number(row[item.key]) || 0) })));
          return (
            <path key={item.key} d={path} fill="none" stroke={item.color} strokeWidth="2.2" strokeLinejoin="round" strokeLinecap="round" />
          );
        })}
        {active != null &&
          series.map((item) => (
            <circle
              key={item.key}
              cx={activeX}
              cy={yAt(Number(data[active][item.key]) || 0)}
              r="3.5"
              fill={item.color}
              stroke="#fff"
              strokeWidth="2"
            />
          ))}
        {data.map((row, index) =>
          index % step === 0 || index === data.length - 1 ? (
            <text
              key={`${row.day}-${index}`}
              x={xAt(index)}
              y={height - 8}
              textAnchor={index === 0 ? "start" : index === data.length - 1 ? "end" : "middle"}
              fill="#717171"
              fontSize="11"
            >
              {row.day}
            </text>
          ) : null
        )}
      </svg>
      {active != null && (
        <div
          className="pointer-events-none absolute z-10 min-w-40 rounded-xl border border-line bg-white px-3 py-2 text-xs shadow-[0_8px_24px_rgba(35,35,35,0.08)]"
          style={{
            left: `${(activeX / width) * 100}%`,
            top: 4,
            transform: tipOnLeft ? "translate(calc(-100% - 12px), 0)" : "translate(12px, 0)",
          }}
        >
          <div className="font-semibold">{data[active].day}</div>
          <ul className="mt-1 space-y-1">
            {series.map((item) => (
              <li key={item.key} className="flex items-center justify-between gap-4">
                <span className="flex items-center gap-1.5 text-muted">
                  <span className="h-1.5 w-1.5 rounded-full" style={{ background: item.color }} />
                  {item.name}
                </span>
                <span className="tabular-nums font-semibold">
                  {num(data[active][item.key])}
                  {unit ? ` ${unit}` : ""}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <ul className="mt-1 flex flex-wrap justify-center gap-x-5 gap-y-1 text-xs text-muted">
        {series.map((item) => (
          <li key={item.key} className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full" style={{ background: item.color }} />
            {item.name}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function DonutLegend({ data, limit = 5, valueKey = "cost" }) {
  const total = data.reduce((sum, item) => sum + (Number(item[valueKey]) || 0), 0) || 1;
  const shown = data.slice(0, limit);
  const rest = data.slice(limit).reduce((sum, item) => sum + (Number(item[valueKey]) || 0), 0);
  return (
    <ul className="space-y-1.5">
      {shown.map((item) => (
        <li key={item.name} className="flex items-center justify-between gap-3 text-sm">
          <span className="flex min-w-0 items-center gap-2">
            <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: item.color }} />
            <span className="truncate">{item.name}</span>
          </span>
          <span className="tabular-nums text-muted">{Math.round(((Number(item[valueKey]) || 0) / total) * 100)}%</span>
        </li>
      ))}
      {rest > 0 && (
        <li className="flex items-center justify-between gap-3 text-sm text-muted">
          <span>Other</span>
          <span className="tabular-nums">{Math.round((rest / total) * 100)}%</span>
        </li>
      )}
    </ul>
  );
}
