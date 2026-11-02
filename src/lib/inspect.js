import { connectionSecrets, HttpError, subscriptionsForProject } from "./access.js";
import { withLock } from "./azure/cli.js";
import { armGet, blobContainers, blobUsage, childResources, containerRevisions, containerWorkspaceLogs, graphQuery, metricSandbox, openSandbox } from "./azure/sandbox.js";
import { kqlColumns, kqlFor, metricChoice, metricSeries, sanitizeClause } from "./compute.js";
import { kqlColumns as dataKqlColumns, kqlFor as dataKqlFor, metricChoice as dataMetricChoice } from "./data.js";
import { kqlColumns as networkKqlColumns, kqlFor as networkKqlFor, metricChoice as networkMetricChoice } from "./network.js";
import { kqlColumns as platformKqlColumns, kqlFor as platformKqlFor, metricChoice as platformMetricChoice } from "./platform.js";

async function withProfile(orgId, projectId, work) {
  const subscriptions = await subscriptionsForProject(projectId, orgId);
  if (!subscriptions.length) throw new HttpError(400, "This project has no Azure subscriptions.");
  const byConnection = new Map();
  for (const subscription of subscriptions) {
    const list = byConnection.get(subscription.connection_id) || [];
    list.push(subscription);
    byConnection.set(subscription.connection_id, list);
  }
  const [connectionId, group] = [...byConnection][0];
  return withLock(connectionId, async () => {
    const creds = await connectionSecrets(connectionId, orgId);
    try {
      const profile = await openSandbox(connectionId, creds);
      return await work(profile, group);
    } finally {
      creds.clientSecret = "";
    }
  });
}

function stamp(value) {
  const time = Date.parse(value);
  if (!Number.isFinite(time)) return "";
  return new Date(time).toISOString();
}

function named(items, map) {
  return (items || []).slice(0, 40).map(map).filter((item) => item.name);
}

function shapeCatalog(type, parts) {
  if (type.includes("keyvault/vaults")) {
    const item = (row) => ({
      name: row.name || "",
      enabled: (row.properties?.attributes?.enabled ?? row.attributes?.enabled) === false ? "No" : "Yes",
      updated: stamp(row.properties?.attributes?.updated || row.attributes?.updated),
    });
    return {
      keys: named(parts.keys?.value, item),
      secrets: named(parts.secrets?.value, item),
      certificates: named(parts.certificates?.value, item),
    };
  }
  if (type.includes("apimanagement/service")) {
    return {
      apis: named(parts.apis?.value, (row) => ({
        name: row.name || "",
        path: row.properties?.path || "",
        revision: row.properties?.apiRevision || "",
      })),
    };
  }
  if (type.includes("servicebus/namespaces")) {
    return {
      queues: named(parts.queues?.value, (row) => ({
        name: row.name || "",
        status: row.properties?.status || "",
        messages: String(row.properties?.countDetails?.activeMessageCount ?? row.properties?.messageCount ?? ""),
      })),
      topics: named(parts.topics?.value, (row) => ({
        name: row.name || "",
        status: row.properties?.status || "",
      })),
    };
  }
  if (type.includes("eventhub/namespaces")) {
    return {
      hubs: named(parts.hubs?.value, (row) => ({
        name: row.name || "",
        partitions: String(row.properties?.partitionCount ?? ""),
        retention: String(row.properties?.messageRetentionInDays ?? ""),
      })),
    };
  }
  if (type.includes("logic/workflows")) {
    return {
      runs: named(parts.runs?.value, (row) => ({
        name: row.name || "",
        status: row.properties?.status || "",
        started: stamp(row.properties?.startTime),
      })).slice(0, 15),
    };
  }
  return {
    deployments: named(parts.deployments?.value, (row) => ({
      name: row.name || "",
      model: row.properties?.model?.name || "",
      version: row.properties?.model?.version || "",
      capacity: String(row.sku?.capacity ?? ""),
    })),
  };
}

function lastName(id) {
  return String(id || "").split("/").filter(Boolean).pop() || "";
}

function shapeLayout(type, payload) {
  if (type.includes("virtualnetworks")) {
    return {
      subnets: (payload?.properties?.subnets || []).slice(0, 80).map((item) => ({
        name: item.name || "",
        prefix: [item.properties?.addressPrefix, ...(item.properties?.addressPrefixes || [])].filter(Boolean).join(", "),
        nsg: lastName(item.properties?.networkSecurityGroup?.id),
        delegation: (item.properties?.delegations || []).map((row) => row.properties?.serviceName).filter(Boolean).join(", "),
      })),
    };
  }
  if (type.includes("applicationgateways")) {
    const ports = new Map((payload?.properties?.frontendPorts || []).map((item) => [String(item.id || "").toLowerCase(), item.properties?.port ?? ""]));
    return {
      listeners: (payload?.properties?.httpListeners || []).slice(0, 40).map((item) => ({
        name: item.name || "",
        protocol: item.properties?.protocol || "",
        host: item.properties?.hostName || "",
        port: String(ports.get(String(item.properties?.frontendPort?.id || "").toLowerCase()) ?? ""),
      })),
      backends: (payload?.properties?.backendAddressPools || []).slice(0, 40).map((item) => ({
        name: item.name || "",
        addresses: String((item.properties?.backendAddresses || []).length),
      })),
    };
  }
  if (type.includes("loadbalancers")) {
    return {
      rules: (payload?.properties?.loadBalancingRules || []).slice(0, 40).map((item) => ({
        name: item.name || "",
        protocol: item.properties?.protocol || "",
        frontend: String(item.properties?.frontendPort ?? ""),
        backend: String(item.properties?.backendPort ?? ""),
      })),
      probes: (payload?.properties?.probes || []).slice(0, 40).map((item) => ({
        name: item.name || "",
        protocol: item.properties?.protocol || "",
        port: String(item.properties?.port ?? ""),
        path: item.properties?.requestPath || "",
      })),
    };
  }
  if (type.includes("cdn/profiles")) {
    return {
      endpoints: (payload?.value || []).slice(0, 40).map((item) => ({
        name: item.name || "",
        host: item.properties?.hostName || "",
        state: item.properties?.enabledState || "",
      })),
    };
  }
  if (type.includes("frontdoors")) {
    return {
      endpoints: (payload?.properties?.frontendEndpoints || []).slice(0, 40).map((item) => ({
        name: item.name || "",
        host: item.properties?.hostName || "",
        state: item.properties?.resourceState || "",
      })),
    };
  }
  return {
    endpoints: [{
      name: payload?.name || "",
      host: "",
      state: payload?.properties?.threatIntelMode || payload?.properties?.provisioningState || "",
    }].filter((item) => item.name),
  };
}

function shapeRevision(row) {
  const props = row?.properties || {};
  return {
    name: row?.name || "",
    active: Boolean(props.active),
    created: props.createdTime || "",
    health: props.healthState || "",
    running: props.runningState || "",
    replicas: props.replicas ?? "",
    traffic: props.trafficWeight ?? "",
    image: props.template?.containers?.[0]?.image || "",
  };
}

export async function executeInspect({ orgId, projectId, serviceId, action, resources, body }) {
  if (action === "metrics") {
    const choice = metricChoice(serviceId, body.metric) || dataMetricChoice(serviceId, body.metric) || networkMetricChoice(serviceId, body.metric) || platformMetricChoice(serviceId, body.metric);
    if (!choice) throw new HttpError(400, "That metric is not part of this service.");
    const windowId = ["15m", "1h", "6h"].includes(body.window) ? body.window : "1h";
    const rows = [];
    const missing = [];
    let message = "";
    await withProfile(orgId, projectId, async (profile) => {
      for (const target of resources) {
        try {
          const payload = await metricSandbox(profile, target.id, choice.name, choice.aggregation, windowId);
          const series = metricSeries(payload, choice.aggregation);
          const value = series.length ? series[series.length - 1].value : null;
          if (value === null) missing.push(target.name);
          else rows.push({ id: target.id, name: target.name, value, series: series.slice(-24) });
        } catch (err) {
          missing.push(target.name);
          if (/too many requests|429|503/i.test(err.message)) {
            message = "Azure is pacing metric reads. The samples already collected stay on screen.";
            break;
          }
        }
      }
    });
    return { metric: choice.name, label: choice.label, unit: choice.unit, aggregation: choice.aggregation, window: windowId, readAt: Date.now(), rows, missing, message };
  }

  if (action === "kql") {
    let clause = "";
    try {
      clause = sanitizeClause(body.clause);
    } catch (err) {
      throw new HttpError(400, err.message);
    }
    const query = kqlFor(serviceId, clause) || dataKqlFor(serviceId, clause) || networkKqlFor(serviceId, clause) || platformKqlFor(serviceId, clause);
    const columns = kqlColumns(serviceId).length ? kqlColumns(serviceId) : dataKqlColumns(serviceId).length ? dataKqlColumns(serviceId) : networkKqlColumns(serviceId).length ? networkKqlColumns(serviceId) : platformKqlColumns(serviceId);
    const table = await withProfile(orgId, projectId, (profile, group) => graphQuery(profile, group.map((item) => item.id), query));
    const rows = (table || []).slice(0, 40).map((row) => {
      const shaped = {};
      for (const column of columns) {
        const text = String(row[column.key] ?? "").trim();
        shaped[column.key] = !text || text.toLowerCase() === "null" ? "" : text;
      }
      return shaped;
    });
    return { query, rows };
  }

  if (action === "containers") {
    if (serviceId !== "storage") throw new HttpError(400, "Containers are read from storage accounts.");
    const accounts = resources.slice(0, 30);
    const listed = await withProfile(orgId, projectId, async (profile) => {
      const rows = [];
      for (const account of accounts) {
        try {
          const containers = await blobContainers(profile, account.id);
          let usage = { bytes: null, count: null };
          try {
            usage = await blobUsage(profile, account.id);
          } catch {
            usage = { bytes: null, count: null };
          }
          rows.push({
            name: account.name,
            used: usage.bytes,
            blobs: usage.count,
            containers: containers.filter((item) => item?.properties?.deleted !== true).slice(0, 80).map((item) => ({
              name: item.name || "",
              updated: item.properties?.lastModifiedTime || "",
              access: item.properties?.publicAccess || "None",
            })),
          });
        } catch {
          rows.push({ name: account.name, used: null, blobs: null, containers: [], error: "Azure did not list containers for this account." });
        }
      }
      return rows;
    });
    return { accounts: listed };
  }

  if (action === "catalog") {
    const name = String(body.name || "").toLowerCase();
    const group = String(body.group || "");
    const match = resources.find((item) => String(item.name || "").toLowerCase() === name && item.group === group);
    if (!match?.id) throw new HttpError(404, "That resource is not in this project.");
    const type = String(match.type || "").toLowerCase();
    const lists = type.includes("keyvault/vaults")
      ? [["keys", "2023-07-01"], ["secrets", "2023-07-01"], ["certificates", "2023-07-01"]]
      : type.includes("apimanagement/service")
        ? [["apis", "2022-08-01"]]
        : type.includes("servicebus/namespaces")
          ? [["queues", "2021-11-01"], ["topics", "2021-11-01"]]
          : type.includes("eventhub/namespaces")
            ? [["eventhubs", "2024-01-01"]]
            : type.includes("logic/workflows")
              ? [["runs", "2019-05-01"]]
              : [["deployments", "2023-05-01"]];
    try {
      const parts = {};
      let failed = 0;
      await withProfile(orgId, projectId, async (profile) => {
        for (const [child, api] of lists) {
          const key = child === "eventhubs" ? "hubs" : child;
          try {
            parts[key] = await armGet(profile, `${match.id}/${child}`, api);
          } catch {
            failed += 1;
            parts[key] = { value: [] };
          }
        }
      });
      if (failed === lists.length) throw new HttpError(502, "Azure did not return that catalog.");
      return shapeCatalog(type, parts);
    } catch (err) {
      if (err instanceof HttpError) throw err;
      throw new HttpError(502, String(err.message || "Azure did not return that catalog.").replace(/\s+/g, " ").slice(0, 240));
    }
  }

  if (action === "layout") {
    const name = String(body.name || "").toLowerCase();
    const group = String(body.group || "");
    const match = resources.find((item) => String(item.name || "").toLowerCase() === name && item.group === group);
    if (!match?.id) throw new HttpError(404, "That resource is not in this project.");
    const type = String(match.type || "").toLowerCase();
    const api = type.includes("microsoft.cdn/profiles") ? "2024-02-01" : type.includes("microsoft.network/frontdoors") ? "2021-06-01" : "2023-11-01";
    try {
      const payload = type.includes("microsoft.cdn/profiles")
        ? await withProfile(orgId, projectId, (profile) => armGet(profile, `${match.id}/afdEndpoints`, api))
        : await withProfile(orgId, projectId, (profile) => armGet(profile, match.id, api));
      return shapeLayout(type, payload);
    } catch (err) {
      if (err instanceof HttpError) throw err;
      throw new HttpError(502, String(err.message || "Azure did not return that network detail.").replace(/\s+/g, " ").slice(0, 240));
    }
  }

  if (action === "network") {
    const name = String(body.name || "").toLowerCase();
    const group = String(body.group || "");
    const match = resources.find((item) => String(item.name || "").toLowerCase() === name && item.group === group);
    if (!match?.id) throw new HttpError(404, "That resource is not in this project.");
    const type = String(match.type || "").toLowerCase();
    const child = type.includes("microsoft.sql/servers") && !type.includes("/databases") && !type.includes("/elasticpools")
      ? ["firewallRules", "virtualNetworkRules", "2021-11-01"]
      : type.includes("flexibleservers")
        ? ["firewallRules", "", "2023-12-30"]
        : null;
    if (!child) throw new HttpError(400, "This service keeps its network on the resource itself.");
    try {
    const rulesPayload = await withProfile(orgId, projectId, (profile) => childResources(profile, match.id, child[0], child[2]));
    const subnetPayload = child[1]
      ? await withProfile(orgId, projectId, (profile) => childResources(profile, match.id, child[1], child[2]))
      : { value: [] };
    const rules = (rulesPayload?.value || []).slice(0, 50).map((row) => ({
      name: row.name || "",
      start: row.properties?.startIpAddress || "",
      end: row.properties?.endIpAddress || "",
    }));
    const subnets = (subnetPayload?.value || []).slice(0, 20).map((row) => row.properties?.virtualNetworkSubnetId?.split("/").slice(-3).join("/") || row.name || "").filter(Boolean);
    return { rules, subnets };
    } catch (err) {
      if (err instanceof HttpError) throw err;
      throw new HttpError(502, String(err.message || "Azure did not return the allow list.").replace(/\s+/g, " ").slice(0, 240));
    }
  }

  if (action === "revisions" || action === "logs") {
    const name = String(body.name || "").toLowerCase();
    const group = String(body.group || "");
    const match = resources.find((item) => String(item.name || "").toLowerCase() === name && item.group === group);
    if (!match) throw new HttpError(404, "That container app is not in this project.");
    const parts = String(match.id || "").split("/");
    const subscriptionId = parts[2] || "";
    const resourceGroup = parts[4] || match.group;
    const appName = (parts[8] || match.name).toLowerCase();
    if (action === "revisions") {
      try {
        const payload = await withProfile(orgId, projectId, (profile) => containerRevisions(profile, appName, resourceGroup, subscriptionId));
        return { rows: (Array.isArray(payload) ? payload : []).slice(0, 20).map(shapeRevision) };
      } catch (err) {
        if (err instanceof HttpError) throw err;
        const text = String(err.message || "");
        if (/AuthorizationFailed|Forbidden/i.test(text)) {
          throw new HttpError(403, "Azure blocked this read.");
        }
        throw new HttpError(502, text.replace(/\s+/g, " ").slice(0, 240));
      }
    }
    const environment = String(match.facts?.environment || "");
    const lines = await withProfile(orgId, projectId, (profile, subs) => containerWorkspaceLogs(profile, subs.map((item) => item.id), environment, appName, body.kind));
    return { lines };
  }

  throw new HttpError(400, "Choose metrics, KQL, revisions, or logs.");
}
