const COLORS = ["#E2773C", "#C45E28", "#F2A365", "#0084FF", "#0BAA60", "#7C6AE8", "#232323", "#0E7490", "#D4537E", "#717171"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function dayKey(value) {
  const raw = String(value ?? "");
  return /^\d{8}$/.test(raw) ? raw : "";
}

export function labelFromKey(key) {
  return `${Number(key.slice(6, 8))} ${MONTHS[Number(key.slice(4, 6)) - 1] || ""}`.trim();
}

export function eachDay(from, to) {
  const days = [];
  let cursor = Date.parse(`${from}T00:00:00Z`);
  const end = Date.parse(`${to}T00:00:00Z`);
  while (cursor < end) {
    days.push(new Date(cursor).toISOString().slice(0, 10).replaceAll("-", ""));
    cursor += 86400000;
  }
  return days;
}

function amount(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function round(value) {
  return Math.round(value * 100) / 100;
}

function costOf(row) {
  return amount(row.Cost ?? row.PreTaxCost ?? row.cost ?? row.totalCost);
}

export function rowsOf(payload) {
  const props = payload?.properties || payload || {};
  const columns = props.columns || [];
  const rows = props.rows || [];
  return rows.map((row) => {
    const item = {};
    columns.forEach((column, index) => {
      item[column.name] = row[index];
    });
    return item;
  });
}

export function foldCosts(serviceRows, days) {
  const byDay = new Map(days.map((key) => [key, 0]));
  const byService = new Map();
  let currency = "USD";
  for (const row of serviceRows) {
    const key = dayKey(row.UsageDate || row.BillingDate || row.Date);
    const cost = costOf(row);
    if (row.Currency || row.BillingCurrency) currency = row.Currency || row.BillingCurrency;
    if (byDay.has(key)) byDay.set(key, byDay.get(key) + cost);
    const name = row.ServiceName || row.MeterCategory || "Other";
    byService.set(name, (byService.get(name) || 0) + cost);
  }
  const points = days.map((key) => ({ label: labelFromKey(key), spend: round(byDay.get(key) || 0) }));
  const ranked = [...byService.entries()]
    .map(([name, cost]) => ({ name, cost: round(cost) }))
    .filter((item) => item.cost !== 0)
    .sort((a, b) => b.cost - a.cost);
  const services = ranked.slice(0, 8).map((item, index) => ({ ...item, color: COLORS[index % COLORS.length] }));
  const rest = ranked.slice(8).reduce((sum, item) => sum + item.cost, 0);
  if (rest > 0) services.push({ name: "Other", cost: round(rest), color: "#717171" });
  const total = round([...byDay.values()].reduce((sum, value) => sum + value, 0));
  return { currency, points, services, total };
}

export function foldGroups(rows) {
  const map = new Map();
  for (const row of rows) {
    const name = row.ResourceGroupName || row.ResourceGroup || "Ungrouped";
    map.set(name, (map.get(name) || 0) + costOf(row));
  }
  return [...map.entries()]
    .map(([name, cost], index) => ({ name, cost: round(cost), color: COLORS[index % COLORS.length] }))
    .filter((item) => item.cost !== 0)
    .sort((a, b) => b.cost - a.cost)
    .slice(0, 8);
}

export function foldMeters(rows, days) {
  const totals = new Map();
  for (const row of rows) {
    const name = row.Meter || row.MeterName || row.MeterSubCategory || "Usage";
    totals.set(name, (totals.get(name) || 0) + amount(row.UsageQuantity ?? row.qty ?? row.Quantity));
  }
  const chosen = [...totals.entries()].filter(([, qty]) => qty !== 0).sort((a, b) => b[1] - a[1]).slice(0, 4);
  const series = chosen.map(([name], index) => ({ key: `m${index}`, name, color: COLORS[index % COLORS.length] }));
  const keys = new Map(chosen.map(([name], index) => [name, `m${index}`]));
  const table = new Map(days.map((key) => [key, { day: labelFromKey(key) }]));
  for (const point of table.values()) {
    for (const item of series) point[item.key] = 0;
  }
  for (const row of rows) {
    const slot = table.get(dayKey(row.UsageDate || row.Date));
    const seriesKey = keys.get(row.Meter || row.MeterName || row.MeterSubCategory || "Usage");
    if (!slot || !seriesKey) continue;
    slot[seriesKey] = round(slot[seriesKey] + amount(row.UsageQuantity ?? row.qty ?? row.Quantity));
  }
  return { series, points: days.map((key) => table.get(key)) };
}

export function forecastMonth(total, elapsedDays, now) {
  if (!elapsedDays) return null;
  const daysInMonth = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 0)).getUTCDate();
  return round((total / elapsedDays) * daysInMonth);
}
