import { connectionSecrets, subscriptionsForProject } from "../access.js";
import { presentAlert } from "../alerts.js";
import { factsFromRow } from "../compute.js";
import { serviceFor } from "../services.js";
import { eachDay, foldCosts, foldGroups, foldMeters, forecastMonth, rowsOf } from "./fold.js";
import { bindAzCaller } from "./calls.js";
import { activitySandbox, costSandbox, openSandbox, readSandbox } from "./sandbox.js";
import { withLock } from "./cli.js";
import { rangeById, rangeWindow } from "../ranges.js";

const cache = new Map();
const inflight = new Map();
const FRESH_MS = 60_000;
const STALE_MS = 15 * 60_000;

function cacheRead(key) {
  const hit = cache.get(key);
  if (!hit) return null;
  const age = Date.now() - hit.at;
  if (age > STALE_MS) {
    cache.delete(key);
    return null;
  }
  return { value: hit.value, fresh: age <= FRESH_MS };
}

function presentWarnings(warnings) {
  const throttled = warnings.filter((item) => /too many requests/i.test(item));
  const rest = warnings.filter((item) => !/too many requests/i.test(item));
  if (throttled.length) rest.unshift("Azure is pacing some cost details. Figures already collected stay on screen.");
  return rest;
}

async function safe(warnings, label, work) {
  try {
    return await work();
  } catch (err) {
    warnings.push(`${label}: ${err.message}`);
    return null;
  }
}

function limitConcurrency(limit) {
  let active = 0;
  const queue = [];
  return function run(work) {
    return new Promise((resolve, reject) => {
      const start = () => {
        active += 1;
        Promise.resolve()
          .then(work)
          .then(resolve, reject)
          .finally(() => {
            active -= 1;
            const next = queue.shift();
            if (next) next();
          });
      };
      if (active < limit) start();
      else queue.push(start);
    });
  };
}

function costBody(from, to, grouping, filter) {
  const body = {
    type: "ActualCost",
    timeframe: "Custom",
    timePeriod: { from: `${from}T00:00:00Z`, to: `${to}T00:00:00Z` },
    dataset: {
      granularity: "Daily",
      aggregation:
        grouping === "Meter"
          ? { qty: { name: "UsageQuantity", function: "Sum" } }
          : { totalCost: { name: "Cost", function: "Sum" } },
      grouping: [{ type: "Dimension", name: grouping }],
    },
  };
  if (filter) body.dataset.filter = filter;
  return body;
}

function shapeActivity(rows) {
  return rows
    .map((item, index) => ({
      id: [item.eventTimestamp, item.operationName?.value || item.operationName, item.resourceId, item.caller, index]
        .filter((part) => part !== undefined && part !== null && part !== "")
        .join("|"),
      time: item.eventTimestamp || item.submissionTimestamp || "",
      status: item.status?.value || (typeof item.status === "string" ? item.status : "") || "",
      caller: item.caller || "",
      text: item.operationName?.localizedValue || item.operationName?.value || item.text || "Activity",
      resource: String(item.resourceId || item.resource || "").split("/").pop() || "",
      resourceId: String(item.resourceId || ""),
      resourceType: typeof item.resourceType === "string" ? item.resourceType : item.resourceType?.value || "",
    }))
    .sort((a, b) => Date.parse(b.time) - Date.parse(a.time));
}

function splitActivity(rows) {
  const seen = new Set();
  const unique = [];
  for (const item of shapeActivity(rows)) {
    const key = [item.time, item.text, item.resource, String(item.resourceType || "").toLowerCase()].join("|");
    if (seen.has(key)) continue;
    seen.add(key);
    unique.push(item);
  }
  const byType = new Map();
  for (const item of unique) {
    const key = String(item.resourceType || "other").toLowerCase();
    const list = byType.get(key) || [];
    if (list.length < 20) list.push(item);
    byType.set(key, list);
  }
  const operations = [...byType.values()].flat().sort((a, b) => Date.parse(b.time) - Date.parse(a.time));
  return { operations, activity: operations.slice(0, 12) };
}

function providersIn(resources) {
  const bySubscription = new Map();
  for (const row of resources || []) {
    const subscriptionId = String(row.id || "").split("/")[2] || "";
    const provider = String(row.type || "").split("/")[0];
    if (!/^[0-9a-f-]{36}$/i.test(subscriptionId) || !/^microsoft\.[a-z0-9]+$/i.test(provider)) continue;
    const set = bySubscription.get(subscriptionId) || new Set();
    set.add(provider);
    bySubscription.set(subscriptionId, set);
  }
  return bySubscription;
}

async function collectActivity(profile, subscriptions, resources) {
  const providers = providersIn(resources);
  const jobs = [];
  for (const subscription of subscriptions) {
    for (const provider of providers.get(subscription.id) || []) jobs.push({ subscription, provider });
  }
  const rows = [];
  const queue = [...jobs];
  async function run() {
    while (queue.length) {
      const job = queue.shift();
      try {
        rows.push(...(await activitySandbox(profile, job.subscription.id, job.provider)));
      } catch {
        // One provider can fail. The others still fill the log.
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(2, jobs.length) }, run));
  return rows;
}

function powerLabel(value) {
  const text = String(value || "Unknown");
  if (/running/i.test(text)) return "Running";
  if (/deallocated|stopped/i.test(text)) return "Stopped";
  return text.replace(/^VM\s+/i, "");
}

function ofType(rows, type) {
  return rows.filter((row) => String(row.type || "").toLowerCase() === type);
}

function shapeInventory(resources, groups, advisor, alerts = []) {
  const rows = resources.map((row) => ({
    ...row,
    kind: row.kind ?? row.kindText ?? "",
    sku: row.sku ?? row.skuName ?? "",
    enabled: row.enabled ?? row.enabledFlag,
    severity: row.severity ?? row.severityText,
  }));
  return {
    resources: rows,
    vms: ofType(rows, "microsoft.compute/virtualmachines").map((row) => ({
      id: row.id,
      name: row.name,
      resourceGroup: row.resourceGroup,
      location: row.location,
      hardwareProfile: { vmSize: row.vmSize },
      powerState: row.power,
    })),
    groups,
    workspaces: ofType(rows, "microsoft.databricks/workspaces").map((row) => ({
      id: row.id,
      name: row.name,
      resourceGroup: row.resourceGroup,
      location: row.location,
      sku: { name: row.sku },
    })),
    storage: ofType(rows, "microsoft.storage/storageaccounts").map((row) => ({
      id: row.id,
      name: row.name,
      resourceGroup: row.resourceGroup,
      location: row.location,
      kind: row.kind,
      isHnsEnabled: row.hns === "true",
    })),
    apps: ofType(rows, "microsoft.app/containerapps").map((row) => ({
      id: row.id,
      name: row.name,
      resourceGroup: row.resourceGroup,
      location: row.location,
    })),
    clusters: ofType(rows, "microsoft.containerservice/managedclusters").map((row) => ({
      id: row.id,
      name: row.name,
      resourceGroup: row.resourceGroup,
      location: row.location,
    })),
    sites: ofType(rows, "microsoft.web/sites")
      .filter((row) => !/function/i.test(row.kind))
      .map((row) => ({
        id: row.id,
        name: row.name,
        resourceGroup: row.resourceGroup,
        location: row.location,
        kind: row.kind,
      })),
    factories: ofType(rows, "microsoft.datafactory/factories").map((row) => ({
      id: row.id,
      name: row.name,
      resourceGroup: row.resourceGroup,
      location: row.location,
    })),
    alerts: (alerts || []).map(presentAlert),
    advisor: advisor.map((row) => {
      let props = row.properties;
      if (typeof props === "string") {
        try {
          props = JSON.parse(props);
        } catch {
          props = {};
        }
      }
      return {
        id: row.id,
        impact: props?.impact || "",
        category: props?.category || "Advisor",
        shortDescription: {
          problem: props?.shortDescription?.problem || "Recommendation",
          solution: props?.shortDescription?.solution || "",
        },
      };
    }),
  };
}

async function readConnectionChunk(profile, subscriptions, window, canSeeCost, warnings) {
  const inventory = await safe(warnings, "Resource Graph", () => readSandbox(profile, subscriptions));
  const shaped = shapeInventory(inventory?.resources || [], inventory?.groups || [], inventory?.advisor || [], inventory?.alerts || []);
  const serviceRows = [];
  const groupRows = [];
  const meterRows = [];
  if (canSeeCost) {
    const limited = limitConcurrency(2);
    let throttled = false;
    async function collect(label, grouping, filter) {
      if (throttled) return [];
      const rows = [];
      await Promise.all(
        subscriptions.map((subscription) =>
          limited(async () => {
            if (throttled) return;
            const before = warnings.length;
            const payload = await safe(warnings, `${subscription.name} ${label}`, () =>
              costSandbox(profile, subscription.id, costBody(window.from, window.to, grouping, filter))
            );
            if (warnings.slice(before).some((item) => /too many requests/i.test(item))) throttled = true;
            rows.push(...rowsOf(payload));
          })
        )
      );
      return rows;
    }
    serviceRows.push(...(await collect("service cost", "ServiceName")));
    groupRows.push(...(await collect("resource group cost", "ResourceGroupName")));
    if (shaped.workspaces.length) {
      meterRows.push(
        ...(await collect("Databricks usage", "Meter", {
          dimensions: { name: "ServiceName", operator: "In", values: ["Azure Databricks"] },
        }))
      );
    }
  }
  const activity = await collectActivity(profile, subscriptions, inventory?.resources || []);
  return { ...shaped, activity, serviceRows, groupRows, meterRows };
}

export async function loadEstate({ orgId, project, rangeId, canSeeCost, fresh, wait }) {
  bindAzCaller({ orgId, projectId: project.id, caller: "estate.sync" });
  const range = rangeById(rangeId);
  const window = rangeWindow(range.id);
  const subscriptions = await subscriptionsForProject(project.id, orgId);
  const base = {
    status: "setup",
    message: "",
    warnings: [],
    canSeeCost,
    range,
    project: { id: project.id, name: project.name, budget: project.budget_usd },
    subscriptions: subscriptions.map((item) => ({ id: item.id, name: item.name, state: item.state })),
    kpis: { spend: null, currency: "USD", forecast: null, resourceCount: 0, vmCount: 0, vmRunning: 0, groupCount: 0 },
    trend: { title: `Spend · ${range.label.toLowerCase()}`, points: [] },
    services: [],
    groups: [],
    databricks: { series: [], points: [] },
    vms: [],
    hosting: [],
    workspaces: [],
    storage: [],
    pipelines: [],
    resources: [],
    activity: [],
    operations: [],
    alerts: [],
    advisor: [],
    syncedAt: Date.now(),
  };
  if (!subscriptions.length) {
    base.message = "Map an Azure connection to this project.";
    return base;
  }

  const key = `${orgId}:${project.id}:${range.id}:${canSeeCost}:${subscriptions.map((item) => item.id).join(",")}`;
  const cached = fresh ? null : cacheRead(key);
  if (cached?.fresh) return cached.value;

  const refresh = async () => {
  const warnings = [];
  const chunks = [];
  const byConnection = new Map();
  for (const subscription of subscriptions) {
    const list = byConnection.get(subscription.connection_id) || [];
    list.push(subscription);
    byConnection.set(subscription.connection_id, list);
  }

  await Promise.all(
    [...byConnection].map(([connectionId, group]) =>
      withLock(connectionId, async () => {
        let creds;
        try {
          creds = await connectionSecrets(connectionId, orgId);
          const profile = await openSandbox(connectionId, creds);
          chunks.push(await readConnectionChunk(profile, group, window, canSeeCost, warnings));
        } catch (err) {
          warnings.push(err.message);
        } finally {
          if (creds) creds.clientSecret = "";
        }
      })
    )
  );

  const days = eachDay(window.from, window.to);
  const serviceRows = chunks.flatMap((chunk) => chunk.serviceRows);
  const costs = canSeeCost ? foldCosts(serviceRows, days) : { currency: "USD", points: [], services: [], total: 0 };
  const groups = canSeeCost ? foldGroups(chunks.flatMap((chunk) => chunk.groupRows)) : [];
  const databricks = canSeeCost ? foldMeters(chunks.flatMap((chunk) => chunk.meterRows), days) : { series: [], points: [] };
  const resources = chunks.flatMap((chunk) => chunk.resources).flatMap((item) => {
    const service = serviceFor(item);
    if (!service) return [];
    return [{
      id: item.id,
      name: item.name,
      type: item.type,
      service: service.id,
      serviceLabel: service.label,
      kind: service.id,
      group: item.resourceGroup,
      location: item.location,
      sku: item.sku || "",
      size: item.vmSize || item.sku || "",
      state: item.power || item.runningStatus || item.siteState || item.statusText || item.powerCode ? powerLabel(item.power || item.runningStatus || item.siteState || item.statusText || item.powerCode) : "",
      facts: factsFromRow(item),
    }];
  });
  const vms = chunks.flatMap((chunk) => chunk.vms).map((item) => ({
    id: item.id,
    name: item.name,
    group: item.resourceGroup,
    location: item.location,
    size: item.hardwareProfile?.vmSize || "",
    state: powerLabel(item.powerState),
  }));
  const hosting = [
    ...chunks.flatMap((chunk) => chunk.apps).map((item) => ({ id: item.id, name: item.name, kind: "Container App", group: item.resourceGroup, location: item.location })),
    ...chunks.flatMap((chunk) => chunk.clusters).map((item) => ({ id: item.id, name: item.name, kind: "AKS", group: item.resourceGroup, location: item.location })),
    ...chunks.flatMap((chunk) => chunk.sites).map((item) => ({ id: item.id, name: item.name, kind: "App Service", group: item.resourceGroup, location: item.location })),
  ];
  const model = {
    ...base,
    status: "ready",
    message: presentWarnings(warnings)[0] || "",
    warnings: presentWarnings(warnings).slice(0, 4),
    kpis: {
      spend: canSeeCost ? costs.total : null,
      currency: costs.currency || "USD",
      forecast: canSeeCost && range.id === "mtd" ? forecastMonth(costs.total, days.length, new Date()) : null,
      resourceCount: resources.length,
      vmCount: vms.length,
      vmRunning: vms.filter((item) => item.state === "Running").length,
      groupCount: chunks.reduce((sum, chunk) => sum + chunk.groups.length, 0),
    },
    trend: {
      title: range.id === "7d" ? "Spend · last 7 days" : range.id === "30d" ? "Spend · last 30 days" : range.id === "qtr" ? "Spend · this quarter" : "Spend · this month",
      points: canSeeCost ? costs.points : [],
    },
    services: costs.services,
    groups,
    databricks,
    vms,
    hosting,
    workspaces: chunks.flatMap((chunk) => chunk.workspaces).map((item) => ({
      id: item.id,
      name: item.name,
      group: item.resourceGroup,
      location: item.location,
      sku: item.sku?.name || "",
    })),
    storage: chunks.flatMap((chunk) => chunk.storage).map((item) => ({
      id: item.id,
      name: item.name,
      group: item.resourceGroup,
      location: item.location,
      kind: item.kind || "Storage",
      hierarchical: Boolean(item.isHnsEnabled),
    })),
    pipelines: chunks.flatMap((chunk) => chunk.factories).map((item) => ({
      id: item.id,
      name: item.name,
      group: item.resourceGroup,
      location: item.location,
    })),
    resources,
    ...splitActivity(chunks.flatMap((chunk) => chunk.activity)),
    alerts: chunks.flatMap((chunk) => chunk.alerts).map(presentAlert),
    advisor: chunks.flatMap((chunk) => chunk.advisor).slice(0, 30).map((item) => ({
      id: item.id || item.name,
      impact: item.impact || "",
      category: item.category || "Advisor",
      problem: item.shortDescription?.problem || "Recommendation",
      solution: item.shortDescription?.solution || "",
    })),
    syncedAt: Date.now(),
  };
  if (!chunks.length && warnings.length) {
    model.status = "error";
    model.message = warnings[0];
  }
  if (model.status === "ready") cache.set(key, { at: Date.now(), value: model });
  return model;
  };

  let job = inflight.get(key);
  if (!job) {
    job = refresh().finally(() => {
      if (inflight.get(key) === job) inflight.delete(key);
    });
    inflight.set(key, job);
  }
  if (cached && !wait) return { ...cached.value, stale: true };
  return job;
}
