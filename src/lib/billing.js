import { labelFromKey } from "./azure/fold.js";
import { rangeWindow } from "./ranges.js";

const COLORS = ["#E2773C", "#C45E28", "#F2A365", "#0084FF", "#0BAA60", "#7C6AE8", "#232323", "#0E7490", "#D4537E", "#717171"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export const BILLING_PRESETS = [
  { id: "7d", label: "Last 7 days" },
  { id: "30d", label: "Last 30 days" },
  { id: "mtd", label: "This month" },
  { id: "qtr", label: "This quarter" },
  { id: "last-qtr", label: "Last quarter" },
  { id: "custom", label: "Custom" },
];

export function billingWindow(preset, now = new Date()) {
  if (preset === "last-qtr") {
    const startMonth = Math.floor(now.getUTCMonth() / 3) * 3 - 3;
    const start = new Date(Date.UTC(now.getUTCFullYear(), startMonth, 1));
    const end = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + 3, 1));
    return { from: start.toISOString().slice(0, 10), to: end.toISOString().slice(0, 10) };
  }
  if (preset === "7d" || preset === "30d" || preset === "mtd" || preset === "qtr") return rangeWindow(preset, now);
  return null;
}

export function isoDay(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(value || ""))) return "";
  const time = Date.parse(`${value}T00:00:00Z`);
  if (!Number.isFinite(time)) return "";
  return new Date(time).toISOString().slice(0, 10) === value ? value : "";
}

export function inclusiveEnd(to) {
  const time = Date.parse(`${to}T00:00:00Z`) - 86400000;
  if (!Number.isFinite(time)) return "";
  return new Date(time).toISOString().slice(0, 10);
}

export function prettyDay(iso) {
  const [year, month, day] = String(iso || "").split("-").map(Number);
  if (!year || !month || !day) return "";
  return `${day} ${MONTHS[month - 1]} ${year}`;
}

function round(value) {
  return Math.round(value * 100) / 100;
}

function bucketLabel(key, grain) {
  if (grain === "month") return `${MONTHS[Number(key.slice(4, 6)) - 1] || ""} ${key.slice(0, 4)}`.trim();
  return labelFromKey(key);
}

export function billingChoices(rows) {
  const uniq = (key) => [...new Set((rows || []).map((row) => row[key]).filter(Boolean))].sort((a, b) => a.localeCompare(b));
  return { services: uniq("service"), groups: uniq("group"), subscriptions: uniq("subscription") };
}

export function buildChart(rows, { groupBy = "total", services = [], groups = [], subscriptions = [], grain = "day" } = {}) {
  const serviceSet = new Set(services);
  const groupSet = new Set(groups);
  const subSet = new Set(subscriptions);
  const filtered = (rows || []).filter((row) => {
    if (serviceSet.size && !serviceSet.has(row.service)) return false;
    if (groupSet.size && !groupSet.has(row.group)) return false;
    if (subSet.size && !subSet.has(row.subscription)) return false;
    return true;
  });
  const dim = groupBy === "ResourceGroupName" ? "group" : groupBy === "subscription" ? "subscription" : groupBy === "ServiceName" ? "service" : "";
  const totals = new Map();
  for (const row of filtered) {
    const name = dim ? (row[dim] || "Other") : "Spend";
    totals.set(name, (totals.get(name) || 0) + Number(row.cost) || 0);
  }
  const ranked = [...totals.entries()].filter(([, cost]) => cost !== 0).sort((a, b) => b[1] - a[1]);
  const top = dim ? ranked.slice(0, 6) : ranked.slice(0, 1);
  const series = top.map(([name], index) => ({ key: `s${index}`, name, color: COLORS[index % COLORS.length] }));
  const other = dim && ranked.length > top.length;
  if (other) series.push({ key: "other", name: "Other", color: "#717171" });
  const nameToKey = new Map(series.filter((item) => item.key !== "other").map((item) => [item.name, item.key]));
  const buckets = new Map();
  for (const row of filtered) {
    const key = grain === "month" ? String(row.date || "").slice(0, 6) : String(row.date || "");
    if (!/^\d{6,8}$/.test(key)) continue;
    if (!buckets.has(key)) {
      const point = { key, label: bucketLabel(key, grain), spend: 0 };
      for (const item of series) point[item.key] = 0;
      buckets.set(key, point);
    }
    const point = buckets.get(key);
    const name = dim ? (row[dim] || "Other") : "Spend";
    const seriesKey = nameToKey.get(name) || (other ? "other" : series[0]?.key);
    point.spend = round(point.spend + (Number(row.cost) || 0));
    if (seriesKey) point[seriesKey] = round((point[seriesKey] || 0) + (Number(row.cost) || 0));
  }
  const points = [...buckets.values()].sort((a, b) => a.key.localeCompare(b.key));
  const breakdown = ranked.map(([name, cost], index) => ({
    name,
    cost: round(cost),
    color: COLORS[index % COLORS.length],
  }));
  const total = round(filtered.reduce((sum, row) => sum + (Number(row.cost) || 0), 0));
  return { points, series, breakdown, total, filtered };
}

function csvCell(value) {
  const text = String(value ?? "");
  if (/[",\n]/.test(text)) return `"${text.replaceAll('"', '""')}"`;
  return text;
}

export function billingCsv(rows) {
  const lines = (rows || []).map((row) => [row.date, row.subscription, row.service, row.group, row.cost].map(csvCell).join(","));
  return ["Date,Subscription,Service,Resource group,Cost", ...lines].join("\n");
}
