import { HttpError, connectionSecrets, subscriptionsForProject } from "./access.js";
import { withLock } from "./azure/cli.js";
import { billingProperty, costSandbox, invoiceGet, openSandbox, profileInvoice, profileInvoices } from "./azure/sandbox.js";
import { dayKey, eachDay, foldCosts, foldGroups, rowsOf } from "./azure/fold.js";
import { billingWindow, inclusiveEnd } from "./billing.js";
import { keepInvoicePdf } from "./invoice-store.js";
import { one, run } from "./db.js";

function costOf(row) {
  const number = Number(row.Cost ?? row.PreTaxCost ?? row.cost ?? row.totalCost);
  return Number.isFinite(number) ? number : 0;
}

function costQuery(from, to, names, grain = "Daily") {
  const body = {
    type: "ActualCost",
    timeframe: "Custom",
    timePeriod: { from: `${from}T00:00:00Z`, to: `${to}T00:00:00Z` },
    dataset: {
      granularity: grain,
      aggregation: { totalCost: { name: "Cost", function: "Sum" } },
      grouping: names.map((name) => ({ type: "Dimension", name })),
    },
  };
  return body;
}

function dateKey(value) {
  const raw = String(value ?? "");
  if (/^\d{8}$/.test(raw)) return raw;
  if (/^\d{6}$/.test(raw)) return `${raw}01`;
  return dayKey(raw);
}

function shapeRows(parsed, subscription) {
  return parsed.map((row) => ({
    date: dateKey(row.UsageDate || row.BillingDate || row.Date),
    service: String(row.ServiceName || "Other"),
    group: String(row.ResourceGroupName || row.ResourceGroup || ""),
    subscription,
    cost: Math.round(costOf(row) * 100) / 100,
    currency: row.Currency || row.BillingCurrency || "",
  })).filter((row) => row.date);
}

async function querySubscription(profile, subscription, from, to) {
  const attempts = [
    ["Daily", ["ServiceName", "ResourceGroupName"]],
    ["Daily", ["ServiceName"]],
    ["Monthly", ["ServiceName", "ResourceGroupName"]],
  ];
  let last;
  for (const [grain, names] of attempts) {
    try {
      const payload = await costSandbox(profile, subscription.id, costQuery(from, to, names, grain));
      return shapeRows(rowsOf(payload), subscription.name);
    } catch (err) {
      last = err;
      if (/too many requests|429|503/i.test(err.message)) throw err;
    }
  }
  throw last || new Error("Azure did not return cost for one subscription.");
}

export async function readBilling({ orgId, projectId, from, to }) {
  const subscriptions = await subscriptionsForProject(projectId, orgId);
  if (!subscriptions.length) throw new HttpError(400, "This project has no Azure subscriptions.");
  const byConnection = new Map();
  for (const subscription of subscriptions) {
    const list = byConnection.get(subscription.connection_id) || [];
    list.push(subscription);
    byConnection.set(subscription.connection_id, list);
  }
  const rows = [];
  let currency = "USD";
  let partial = false;
  const warnings = [];
  for (const [connectionId, group] of byConnection) {
    if (partial) break;
    await withLock(connectionId, async () => {
      const creds = await connectionSecrets(connectionId, orgId);
      try {
        const profile = await openSandbox(connectionId, creds);
        for (const subscription of group) {
          try {
            const next = await querySubscription(profile, subscription, from, to);
            for (const row of next) {
              if (row.currency) currency = row.currency;
              rows.push(row);
            }
          } catch (err) {
            if (/too many requests|429|503/i.test(err.message)) {
              partial = true;
              warnings.push("Azure is pacing cost reads. The days already returned stay on screen.");
              break;
            }
            warnings.push("Azure did not return cost for one subscription.");
          }
        }
      } finally {
        creds.clientSecret = "";
      }
    });
  }
  if (!rows.length && partial) throw new HttpError(429, "Azure is pacing cost reads. Try this range again in a few minutes.");
  if (!rows.length && warnings.length) throw new HttpError(502, warnings[0]);
  return { from, to, currency, rows, partial, warnings };
}

function amountOf(value) {
  if (value && typeof value === "object") return { amount: Number(value.value ?? value.amount) || 0, currency: value.currency || "USD" };
  const amount = Number(value);
  return { amount: Number.isFinite(amount) ? amount : 0, currency: "USD" };
}

export function shapeInvoices(payload, subscription) {
  return (payload?.value || []).map((item) => {
    const props = item.properties || {};
    const due = amountOf(props.amountDue ?? props.billedAmount ?? props.totalAmount);
    const documentUrl = (props.documents || []).find((doc) => doc?.url)?.url || props.downloadUrl?.url || props.invoicePdfUrl || "";
    return {
      id: `${subscription.profileId || subscription.id}:${item.name}`,
      name: String(item.name || ""),
      subscriptionId: subscription.id,
      profileId: subscription.profileId || "",
      subscription: subscription.name,
      start: props.billingPeriodStartDate || props.invoicePeriodStartDate || props.invoiceDate || "",
      end: props.billingPeriodEndDate || props.invoicePeriodEndDate || props.dueDate || "",
      status: props.status || props.invoiceStatus || "",
      amount: due.amount,
      currency: due.currency,
      download: typeof documentUrl === "string" ? documentUrl : "",
    };
  }).filter((item) => item.name);
}

export function safeDownload(url) {
  try {
    const parsed = new URL(String(url || ""));
    if (parsed.protocol !== "https:") return "";
    if (!/azure|microsoft|windows\.net/i.test(parsed.hostname)) return "";
    return parsed.toString();
  } catch {
    return "";
  }
}

export async function readInvoices({ orgId, projectId, save = false }) {
  const subscriptions = await subscriptionsForProject(projectId, orgId);
  if (!subscriptions.length) throw new HttpError(400, "This project has no Azure subscriptions.");
  const byConnection = new Map();
  for (const subscription of subscriptions) {
    const list = byConnection.get(subscription.connection_id) || [];
    list.push(subscription);
    byConnection.set(subscription.connection_id, list);
  }
  const invoices = [];
  let blocked = false;
  const seenProfiles = new Set();
  for (const [connectionId, group] of byConnection) {
    await withLock(connectionId, async () => {
      const creds = await connectionSecrets(connectionId, orgId);
      try {
        const profile = await openSandbox(connectionId, creds);
        for (const subscription of group) {
          let profileId = "";
          try {
            const property = await billingProperty(profile, subscription.id);
            profileId = String(property?.properties?.billingProfileId || "");
          } catch {
            profileId = "";
          }
          if (!profileId || seenProfiles.has(profileId)) continue;
          seenProfiles.add(profileId);
          try {
            const shaped = shapeInvoices(await profileInvoices(profile, profileId), { ...subscription, profileId, name: "Billing profile" });
            if (save) {
              for (const invoice of shaped) {
                const kept = await keepInvoicePdf(profile, projectId, invoice);
                invoice.saved = kept.saved;
                invoice.file = kept.file;
              }
            }
            invoices.push(...shaped);
          } catch (err) {
            if (/unauthorized|AuthorizationFailed|Forbidden|403/i.test(err.message)) blocked = true;
          }
        }
      } finally {
        creds.clientSecret = "";
      }
    });
  }
  const seen = new Set();
  const unique = invoices.filter((item) => {
    if (seen.has(item.id)) return false;
    seen.add(item.id);
    return true;
  });
  unique.sort((a, b) => String(b.end).localeCompare(String(a.end)));
  return {
    invoices: unique,
    message: unique.length
      ? ""
      : blocked
        ? "Billing Reader on the subscription can read cost. Of the billing roles in that list, Billing Reader is the one that can read invoice PDFs, and it has to be assigned on the billing profile as well. The other four roles do not download these bills."
        : "Azure did not list invoices for these subscriptions.",
  };
}

export async function readInvoiceFile({ orgId, projectId, subscriptionId, name }) {
  const subscriptions = await subscriptionsForProject(projectId, orgId);
  const subscription = subscriptions.find((item) => item.id === subscriptionId);
  if (!subscription) throw new HttpError(404, "That subscription is not on this project.");
  let url = "";
  await withLock(subscription.connection_id, async () => {
    const creds = await connectionSecrets(subscription.connection_id, orgId);
    try {
      const sandbox = await openSandbox(subscription.connection_id, creds);
      let payload = null;
      try {
        const property = await billingProperty(sandbox, subscription.id);
        const profileId = String(property?.properties?.billingProfileId || "");
        if (profileId) payload = await profileInvoice(sandbox, profileId, name);
      } catch {
        payload = null;
      }
      if (!payload) payload = await invoiceGet(sandbox, subscription.id, name);
      const documentUrl = (payload?.properties?.documents || []).find((doc) => doc?.url)?.url || payload?.properties?.downloadUrl?.url || payload?.properties?.invoicePdfUrl || "";
      url = safeDownload(documentUrl);
    } catch (err) {
      if (/not authorized|AuthorizationFailed|Forbidden|403|billing account/i.test(err.message || "")) {
        throw new HttpError(403, "Azure did not share this invoice. The PDF needs access on the billing account.");
      }
      throw new HttpError(404, "Azure did not attach a PDF to this invoice.");
    } finally {
      creds.clientSecret = "";
    }
  });
  if (!url) throw new HttpError(404, "Azure did not attach a PDF to this invoice.");
  return { url };
}

export async function paintSnapshotCost(orgId, projectId, preset, from, to, rows, currency) {
  const expected = billingWindow(preset);
  if (!expected || expected.from !== from || expected.to !== to) return;
  const saved = await one(
    "SELECT payload, synced_at FROM estate_snapshots WHERE org_id = ? AND project_id = ? AND range_id = ?",
    [orgId, projectId, preset],
  );
  if (!saved?.payload || !rows.length) return;
  const payload = saved.payload;
  const days = eachDay(from, to);
  const serviceRows = rows.map((row) => ({ UsageDate: row.date, ServiceName: row.service, Cost: row.cost, Currency: currency }));
  const groupRows = rows.filter((row) => row.group).map((row) => ({ ResourceGroupName: row.group, Cost: row.cost }));
  const costs = foldCosts(serviceRows, days);
  payload.kpis = { ...payload.kpis, spend: costs.total, currency: costs.currency || currency };
  const end = inclusiveEnd(to);
  const title = preset === "qtr" ? "Spend · this quarter" : preset === "mtd" ? "Spend · this month" : preset === "30d" ? "Spend · last 30 days" : "Spend · last 7 days";
  payload.trend = { title, from, end, points: costs.points };
  payload.services = costs.services;
  if (groupRows.length) payload.groups = foldGroups(groupRows);
  await run(
    "UPDATE estate_snapshots SET payload = ?::jsonb WHERE org_id = ? AND project_id = ? AND range_id = ?",
    [JSON.stringify(payload), orgId, projectId, preset],
  );
}
