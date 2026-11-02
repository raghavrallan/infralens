export const RANGES = [
  { id: "7d", label: "Last 7 days", spendLabel: "7-day spend" },
  { id: "30d", label: "Last 30 days", spendLabel: "30-day spend" },
  { id: "mtd", label: "This month", spendLabel: "Month spend" },
  { id: "qtr", label: "This quarter", spendLabel: "Quarter spend" },
];

export function rangeById(id) {
  return RANGES.find((item) => item.id === id) || RANGES[2];
}

export function rangeWindow(rangeId, now = new Date()) {
  const end = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1));
  let start;
  if (rangeId === "7d") start = new Date(end.getTime() - 7 * 86400000);
  else if (rangeId === "30d") start = new Date(end.getTime() - 30 * 86400000);
  else if (rangeId === "qtr") start = new Date(Date.UTC(now.getUTCFullYear(), Math.floor(now.getUTCMonth() / 3) * 3, 1));
  else start = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1));
  return { from: start.toISOString().slice(0, 10), to: end.toISOString().slice(0, 10) };
}
