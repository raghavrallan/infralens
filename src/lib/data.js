import { healthBucket, sanitizeClause, signalValue } from "./compute.js";
import { serviceById } from "./services.js";

function tidy(value) {
  const text = String(value ?? "").trim();
  if (!text || text.toLowerCase() === "null") return "";
  return text;
}

function yesNo(value) {
  const text = tidy(value).toLowerCase();
  if (text === "true" || text === "enabled") return "Yes";
  if (text === "false" || text === "disabled") return "No";
  return tidy(value);
}

function statusLabel(value) {
  const text = tidy(value);
  if (!text) return "";
  if (text === text.toLowerCase()) return text.charAt(0).toUpperCase() + text.slice(1);
  return text;
}

const COSMOS_API = {
  GlobalDocumentDB: "NoSQL",
  MongoDB: "MongoDB",
  Cassandra: "Cassandra",
  Gremlin: "Gremlin",
  Table: "Table",
  Parse: "Parse",
};

function haLabel(value) {
  const text = tidy(value);
  if (!text) return "";
  if (/disabled/i.test(text)) return "Off";
  if (/zoneredundant/i.test(text)) return "Zone redundant";
  if (/samezone/i.test(text)) return "Same zone";
  return text;
}

const SERVERLESS_MEMORY = {
  1: ["0.5", "1", "2.02", "3"],
  2: ["0.5", "2", "2.05", "6"],
  4: ["0.5", "4", "2.10", "12"],
  6: ["0.75", "6", "2.25", "18"],
  8: ["1", "8", "3", "24"],
  10: ["1.25", "10", "3.75", "30"],
  12: ["1.5", "12", "4.5", "36"],
  14: ["1.75", "14", "5.25", "42"],
  16: ["2", "16", "6", "48"],
  18: ["2.25", "18", "6.75", "54"],
  20: ["2.5", "20", "7.5", "60"],
  24: ["3", "24", "9", "72"],
  32: ["4", "32", "12", "96"],
  40: ["5", "40", "15", "120"],
  80: ["10", "80", "30", "240"],
};

const REDIS_MB = { C0: 250, C1: 1024, C2: 2560, C3: 6144, C4: 13312, C5: 26624, C6: 54272, P1: 6144, P2: 13312, P3: 26624, P4: 54272, P5: 122880 };

function storageLabel(bytes) {
  const value = Number(bytes);
  if (!Number.isFinite(value) || value <= 0) return "";
  const gb = value / (1024 ** 3);
  if (gb >= 1024) return `${Math.round((gb / 1024) * 10) / 10} TB`;
  return `${Math.round(gb)} GB`;
}

function sqlSize(facts) {
  const sku = tidy(facts.sku);
  const edition = tidy(facts.edition);
  const tier = tidy(facts.tier);
  const storage = storageLabel(facts.maxBytes);
  if (/system/i.test(sku) || /system/i.test(tier) || /system/i.test(edition)) return { vCores: "", memory: "", storage, compute: "System" };
  const maxCores = Number(facts.capacity);
  const serverless = /_S_|serverless/i.test(`${sku} ${edition}`);
  const known = SERVERLESS_MEMORY[maxCores];
  if (serverless && known) {
    return { vCores: `${facts.minCapacity || known[0]}–${known[1]}`, memory: `${known[2]}–${known[3]} GB`, storage, compute: "Serverless" };
  }
  if (Number.isFinite(maxCores) && maxCores > 0) {
    const perCore = /MOPRMS|memory optimized/i.test(`${sku} ${edition}`) ? 13.6 : /PRMS|premium-series/i.test(`${sku} ${edition}`) ? 7 : 5.1;
    return { vCores: String(maxCores), memory: `${Math.round(maxCores * perCore * 10) / 10} GB`, storage, compute: tier || "Provisioned" };
  }
  return { vCores: "", memory: "", storage, compute: edition || sku };
}

function flexibleSize(sku) {
  const name = tidy(sku);
  const burst = name.match(/_B(\d+)(ms|s)/i);
  if (burst) {
    const cores = Number(burst[1]);
    const ram = burst[2].toLowerCase() === "ms" ? (cores === 1 ? 2 : cores * 4) : cores * 2;
    return { vCores: String(cores), memory: `${ram} GB` };
  }
  const general = name.match(/_D(\d+)/i);
  if (general) return { vCores: general[1], memory: `${Number(general[1]) * 4} GB` };
  const memory = name.match(/_E(\d+)/i);
  if (memory) {
    const cores = Number(memory[1]);
    return { vCores: String(cores), memory: `${cores === 64 ? 504 : cores * 8} GB` };
  }
  return { vCores: "", memory: "" };
}

function redisSize(facts) {
  const family = tidy(facts.family).toUpperCase();
  const capacity = tidy(facts.capacity);
  const key = `${family}${capacity}`;
  const mb = REDIS_MB[key];
  if (!mb) return { memory: "" };
  return { memory: mb >= 1024 ? `${Math.round((mb / 1024) * 10) / 10} GB` : `${mb} MB` };
}

function addressList(value) {
  if (!value) return [];
  try {
    const parsed = JSON.parse(value);
    if (!Array.isArray(parsed)) return [];
    return parsed.map((item) => tidy(item.value || item.ipAddressOrRange)).filter(Boolean);
  } catch {
    return [];
  }
}

export const DATA_DEPTH = {
  sql: {
    summary: "Servers and databases are separate. Servers show the IP allow list. Databases show vCores, memory, and storage.",
    metric: { name: "cpu_percent", aggregation: "Average", unit: "%", label: "CPU" },
    columns: [["name", "Name"], ["status", "Status"], ["sku", "SKU"], ["location", "Region"], ["group", "Resource group"]],
    essentials: [["status", "Status"], ["location", "Region"], ["group", "Resource group"]],
    availability: [["status", "Status"], ["public", "Public network"], ["backup", "Backup"]],
  },
  mysql: {
    summary: "vCores, memory, storage, high availability, and the public IP allow list for each server.",
    metric: { name: "cpu_percent", aggregation: "Average", unit: "%", label: "CPU" },
    columns: [["name", "Name"], ["status", "Status"], ["version", "Version"], ["vCores", "vCores"], ["memory", "Memory"], ["storage", "Storage"], ["ha", "High availability"], ["location", "Region"]],
    essentials: [["status", "Status"], ["version", "Version"], ["sku", "SKU"], ["vCores", "vCores"], ["memory", "Memory"], ["storage", "Storage"], ["iops", "IOPS"], ["ha", "High availability"], ["backup", "Backup retention"], ["public", "Public network"], ["host", "Endpoint"], ["location", "Region"], ["group", "Resource group"]],
    availability: [["status", "Status"], ["ha", "High availability"], ["backup", "Backup retention"], ["public", "Public network"], ["host", "Endpoint"]],
  },
  postgresql: {
    summary: "vCores, memory, storage, high availability, and the public IP allow list for each server.",
    metric: { name: "cpu_percent", aggregation: "Average", unit: "%", label: "CPU" },
    columns: [["name", "Name"], ["status", "Status"], ["version", "Version"], ["vCores", "vCores"], ["memory", "Memory"], ["storage", "Storage"], ["ha", "High availability"], ["location", "Region"]],
    essentials: [["status", "Status"], ["version", "Version"], ["sku", "SKU"], ["vCores", "vCores"], ["memory", "Memory"], ["storage", "Storage"], ["iops", "IOPS"], ["ha", "High availability"], ["backup", "Backup retention"], ["public", "Public network"], ["host", "Endpoint"], ["location", "Region"], ["group", "Resource group"]],
    availability: [["status", "Status"], ["ha", "High availability"], ["backup", "Backup retention"], ["public", "Public network"], ["host", "Endpoint"]],
  },
  cosmos: {
    summary: "API, consistency, backup policy, public access, and request units for each account.",
    metric: { name: "TotalRequestUnits", aggregation: "Total", unit: "", label: "Request units" },
    columns: [["name", "Name"], ["status", "Status"], ["api", "API"], ["consistency", "Consistency"], ["backup", "Backup"], ["public", "Public"], ["location", "Region"], ["group", "Resource group"]],
    essentials: [["status", "Status"], ["api", "API"], ["consistency", "Consistency"], ["backup", "Backup policy"], ["public", "Public network"], ["host", "Endpoint"], ["location", "Region"], ["group", "Resource group"]],
    availability: [["status", "Status"], ["consistency", "Consistency"], ["backup", "Backup policy"], ["public", "Public network"]],
  },
  redis: {
    summary: "SKU, family, capacity, version, TLS, and processor for each cache.",
    metric: { name: "percentProcessorTime", aggregation: "Average", unit: "%", label: "CPU" },
    columns: [["name", "Name"], ["status", "Status"], ["sku", "SKU"], ["memory", "Memory"], ["version", "Version"], ["location", "Region"], ["group", "Resource group"]],
    essentials: [["status", "Status"], ["sku", "SKU"], ["family", "Family"], ["memory", "Cache size"], ["version", "Version"], ["public", "Public network"], ["host", "Hostname"], ["location", "Region"], ["group", "Resource group"]],
    availability: [["status", "Status"], ["sku", "SKU"], ["public", "Public network"], ["host", "Hostname"]],
  },
  storage: {
    summary: "Kind, HTTPS, and TLS for each account. Containers shows how many blob containers it has, the used size, and when each container was updated.",
    metric: { name: "Transactions", aggregation: "Total", unit: "", label: "Transactions" },
    columns: [["name", "Name"], ["status", "Status"], ["kind", "Kind"], ["sku", "SKU"], ["https", "HTTPS"], ["tls", "TLS"], ["hns", "Data lake"], ["location", "Region"]],
    essentials: [["status", "Status"], ["kind", "Kind"], ["sku", "SKU"], ["tier", "Access tier"], ["https", "HTTPS only"], ["tls", "Minimum TLS"], ["hns", "Hierarchical namespace"], ["public", "Public blob"], ["location", "Region"], ["group", "Resource group"]],
    availability: [["status", "Status"], ["https", "HTTPS only"], ["tls", "Minimum TLS"], ["public", "Public blob"], ["hns", "Data lake"]],
  },
  "data-factory": {
    summary: "Version, public access, and pipeline runs for each factory.",
    metric: { name: "PipelineSucceededRuns", aggregation: "Total", unit: "", label: "Succeeded runs" },
    columns: [["name", "Name"], ["status", "Status"], ["version", "Version"], ["public", "Public"], ["location", "Region"], ["group", "Resource group"]],
    essentials: [["status", "Status"], ["version", "Version"], ["public", "Public network"], ["location", "Region"], ["group", "Resource group"]],
    availability: [["status", "Status"], ["version", "Version"], ["public", "Public network"]],
  },
  databricks: {
    summary: "SKU, pricing tier, provisioning, and workspace URL for each workspace.",
    metric: null,
    columns: [["name", "Name"], ["status", "Status"], ["sku", "SKU"], ["tier", "Tier"], ["host", "Workspace URL"], ["location", "Region"], ["group", "Resource group"]],
    essentials: [["status", "Status"], ["sku", "SKU"], ["tier", "Tier"], ["host", "Workspace URL"], ["location", "Region"], ["group", "Resource group"]],
    availability: [["status", "Status"], ["sku", "SKU"], ["tier", "Tier"], ["host", "Workspace URL"]],
  },
};

export const LIVE_METRICS = {
  sql: [
    { name: "cpu_percent", aggregation: "Average", unit: "%", label: "CPU" },
    { name: "storage_percent", aggregation: "Average", unit: "%", label: "Storage" },
    { name: "dtu_consumption_percent", aggregation: "Average", unit: "%", label: "DTU" },
    { name: "connection_successful", aggregation: "Total", unit: "", label: "Connections" },
  ],
  mysql: [
    { name: "cpu_percent", aggregation: "Average", unit: "%", label: "CPU" },
    { name: "memory_percent", aggregation: "Average", unit: "%", label: "Memory" },
    { name: "storage_percent", aggregation: "Average", unit: "%", label: "Storage" },
    { name: "active_connections", aggregation: "Average", unit: "", label: "Connections" },
  ],
  postgresql: [
    { name: "cpu_percent", aggregation: "Average", unit: "%", label: "CPU" },
    { name: "memory_percent", aggregation: "Average", unit: "%", label: "Memory" },
    { name: "storage_percent", aggregation: "Average", unit: "%", label: "Storage" },
    { name: "active_connections", aggregation: "Average", unit: "", label: "Connections" },
  ],
  cosmos: [
    { name: "TotalRequestUnits", aggregation: "Total", unit: "", label: "Request units" },
    { name: "TotalRequests", aggregation: "Total", unit: "", label: "Requests" },
    { name: "ServerSideLatency", aggregation: "Average", unit: "ms", label: "Latency" },
  ],
  redis: [
    { name: "percentProcessorTime", aggregation: "Average", unit: "%", label: "CPU" },
    { name: "usedmemorypercentage", aggregation: "Average", unit: "%", label: "Memory" },
    { name: "connectedclients", aggregation: "Average", unit: "", label: "Clients" },
    { name: "cachehits", aggregation: "Total", unit: "", label: "Cache hits" },
  ],
  storage: [
    { name: "Transactions", aggregation: "Total", unit: "", label: "Transactions" },
    { name: "Availability", aggregation: "Average", unit: "%", label: "Availability" },
    { name: "SuccessE2ELatency", aggregation: "Average", unit: "ms", label: "Latency" },
    { name: "Ingress", aggregation: "Total", unit: "B", label: "Ingress" },
    { name: "Egress", aggregation: "Total", unit: "B", label: "Egress" },
  ],
  "data-factory": [
    { name: "PipelineSucceededRuns", aggregation: "Total", unit: "", label: "Succeeded runs" },
    { name: "PipelineFailedRuns", aggregation: "Total", unit: "", label: "Failed runs" },
    { name: "ActivitySucceededRuns", aggregation: "Total", unit: "", label: "Succeeded activities" },
    { name: "TriggerSucceededRuns", aggregation: "Total", unit: "", label: "Succeeded triggers" },
  ],
  databricks: [],
};

const KQL_SHAPES = {
  sql: {
    type: "microsoft.sql/servers",
    where: "| where type =~ 'microsoft.sql/servers' or type =~ 'microsoft.sql/servers/databases'",
    extend: "| extend role = iff(type =~ 'microsoft.sql/servers/databases', 'Database', 'Server'), status = coalesce(tostring(properties.status), tostring(properties.state), ''), skuName = tostring(sku.name), tier = tostring(sku.tier), zone = tostring(properties.zoneRedundant), backup = tostring(properties.currentBackupStorageRedundancy), public = tostring(properties.publicNetworkAccess)",
    project: "name, resourceGroup, location, role, status, skuName, tier, zone, backup, public",
    columns: [["name", "Name"], ["role", "Role"], ["status", "Status"], ["skuName", "SKU"], ["tier", "Tier"], ["backup", "Backup"], ["public", "Public"], ["location", "Region"]],
    examples: [["Databases", "| where role =~ 'Database'"], ["Servers", "| where role =~ 'Server'"], ["Online", "| where status =~ 'Online'"], ["East US", "| where location == 'eastus'"]],
  },
  mysql: {
    where: "| where type =~ 'microsoft.dbformysql/flexibleservers' or type =~ 'microsoft.dbformysql/servers'",
    extend: "| extend status = tostring(properties.state), version = tostring(properties.version), skuName = tostring(sku.name), ha = tostring(properties.highAvailability.mode), storage = tostring(properties.storage.storageSizeGB), backup = tostring(properties.backup.backupRetentionDays), public = tostring(properties.network.publicNetworkAccess)",
    project: "name, resourceGroup, location, status, version, skuName, ha, storage, backup, public",
    columns: [["name", "Name"], ["status", "Status"], ["version", "Version"], ["skuName", "SKU"], ["ha", "High availability"], ["storage", "Storage GB"], ["location", "Region"]],
    examples: [["Ready", "| where status =~ 'Ready'"], ["High availability", "| where ha != 'Disabled'"], ["East US", "| where location == 'eastus'"]],
  },
  postgresql: {
    where: "| where type =~ 'microsoft.dbforpostgresql/flexibleservers' or type =~ 'microsoft.dbforpostgresql/servers'",
    extend: "| extend status = tostring(properties.state), version = tostring(properties.version), skuName = tostring(sku.name), ha = tostring(properties.highAvailability.mode), storage = tostring(properties.storage.storageSizeGB), backup = tostring(properties.backup.backupRetentionDays), public = tostring(properties.network.publicNetworkAccess)",
    project: "name, resourceGroup, location, status, version, skuName, ha, storage, backup, public",
    columns: [["name", "Name"], ["status", "Status"], ["version", "Version"], ["skuName", "SKU"], ["ha", "High availability"], ["storage", "Storage GB"], ["location", "Region"]],
    examples: [["Ready", "| where status =~ 'Ready'"], ["High availability", "| where ha != 'Disabled'"], ["East US", "| where location == 'eastus'"]],
  },
  cosmos: {
    where: "| where type =~ 'microsoft.documentdb/databaseaccounts'",
    extend: "| extend api = tostring(kind), status = tostring(properties.provisioningState), consistency = tostring(properties.consistencyPolicy.defaultConsistencyLevel), public = tostring(properties.publicNetworkAccess), backup = tostring(properties.backupPolicy.type)",
    project: "name, resourceGroup, location, api, status, consistency, public, backup",
    columns: [["name", "Name"], ["api", "API"], ["status", "Status"], ["consistency", "Consistency"], ["backup", "Backup"], ["public", "Public"], ["location", "Region"]],
    examples: [["NoSQL", "| where api =~ 'GlobalDocumentDB'"], ["Succeeded", "| where status =~ 'Succeeded'"], ["East US", "| where location == 'eastus'"]],
  },
  redis: {
    where: "| where type =~ 'microsoft.cache/redis'",
    extend: "| extend status = tostring(properties.provisioningState), skuName = tostring(sku.name), family = tostring(sku.family), capacity = tostring(sku.capacity), version = tostring(properties.redisVersion), host = tostring(properties.hostName)",
    project: "name, resourceGroup, location, status, skuName, family, capacity, version, host",
    columns: [["name", "Name"], ["status", "Status"], ["skuName", "SKU"], ["family", "Family"], ["capacity", "Capacity"], ["version", "Version"], ["location", "Region"]],
    examples: [["Premium", "| where skuName =~ 'Premium'"], ["Succeeded", "| where status =~ 'Succeeded'"], ["East US", "| where location == 'eastus'"]],
  },
  storage: {
    where: "| where type =~ 'microsoft.storage/storageaccounts'",
    extend: "| extend kind = tostring(kind), skuName = tostring(sku.name), https = tostring(properties.supportsHttpsTrafficOnly), tls = tostring(properties.minimumTlsVersion), hns = tostring(properties.isHnsEnabled), public = tostring(properties.allowBlobPublicAccess), access = tostring(properties.accessTier)",
    project: "name, resourceGroup, location, kind, skuName, https, tls, hns, public, access",
    columns: [["name", "Name"], ["kind", "Kind"], ["skuName", "SKU"], ["https", "HTTPS"], ["tls", "TLS"], ["hns", "Data lake"], ["access", "Access tier"], ["location", "Region"]],
    examples: [["Data lake", "| where hns =~ 'true'"], ["HTTPS only", "| where https =~ 'true'"], ["East US", "| where location == 'eastus'"]],
  },
  "data-factory": {
    where: "| where type =~ 'microsoft.datafactory/factories'",
    extend: "| extend status = tostring(properties.provisioningState), version = tostring(properties.version), public = tostring(properties.publicNetworkAccess)",
    project: "name, resourceGroup, location, status, version, public",
    columns: [["name", "Name"], ["status", "Status"], ["version", "Version"], ["public", "Public"], ["location", "Region"]],
    examples: [["Succeeded", "| where status =~ 'Succeeded'"], ["East US", "| where location == 'eastus'"]],
  },
  databricks: {
    where: "| where type =~ 'microsoft.databricks/workspaces'",
    extend: "| extend status = tostring(properties.provisioningState), skuName = tostring(sku.name), tier = tostring(sku.tier), url = tostring(properties.workspaceUrl)",
    project: "name, resourceGroup, location, status, skuName, tier, url",
    columns: [["name", "Name"], ["status", "Status"], ["skuName", "SKU"], ["tier", "Tier"], ["url", "Workspace URL"], ["location", "Region"]],
    examples: [["Premium", "| where skuName =~ 'premium'"], ["Succeeded", "| where status =~ 'Succeeded'"], ["East US", "| where location == 'eastus'"]],
  },
};

export function isData(id) {
  return Boolean(DATA_DEPTH[id]);
}

export function dataHref(id) {
  return isData(id) ? `/data/${id}` : "";
}

export function metricChoice(serviceId, name) {
  const list = LIVE_METRICS[serviceId] || [];
  return list.find((item) => item.name === name) || list[0] || null;
}

export function kqlColumns(serviceId) {
  return (KQL_SHAPES[serviceId]?.columns || []).map(([key, label]) => ({ key, label }));
}

export function kqlExamples(serviceId) {
  return (KQL_SHAPES[serviceId]?.examples || []).map(([label, clause]) => ({ label, clause }));
}

export function kqlFor(serviceId, clause = "") {
  const shape = KQL_SHAPES[serviceId];
  if (!shape) return "";
  let extra = "";
  try {
    extra = sanitizeClause(clause);
  } catch {
    extra = "";
  }
  return `Resources
${shape.where}
${shape.extend}
${extra ? `${extra}\n` : ""}| project ${shape.project}
| take 40`;
}

export function overviewFacets(serviceId) {
  const facet = {
    sql: ["role", "Roles"],
    mysql: ["version", "Versions"],
    postgresql: ["version", "Versions"],
    cosmos: ["api", "APIs"],
    redis: ["sku", "SKUs"],
    storage: ["kind", "Kinds"],
    "data-factory": ["version", "Versions"],
    databricks: ["sku", "SKUs"],
  }[serviceId] || ["location", "Regions"];
  return facet;
}

export function essentialsFor(serviceId, row) {
  if (serviceId === "sql" && row?.role === "Server") {
    return [["status", "Status"], ["version", "Version"], ["public", "Public network"], ["host", "Endpoint"], ["location", "Region"], ["group", "Resource group"]];
  }
  if (serviceId === "sql" && row?.role === "Database") {
    return [["status", "Status"], ["server", "Server"], ["compute", "Compute"], ["vCores", "vCores"], ["memory", "Memory"], ["storage", "Max storage"], ["sku", "SKU"], ["backup", "Backup redundancy"], ["zone", "Zone redundant"], ["location", "Region"], ["group", "Resource group"]];
  }
  if (serviceId === "sql" && row?.role === "Pool") {
    return [["status", "Status"], ["server", "Server"], ["compute", "Compute"], ["vCores", "vCores"], ["memory", "Memory"], ["storage", "Max storage"], ["sku", "SKU"], ["location", "Region"], ["group", "Resource group"]];
  }
  return DATA_DEPTH[serviceId]?.essentials || [];
}

export function presentResource(serviceId, resource) {
  const facts = resource.facts || {};
  const type = String(resource.type || "").toLowerCase();
  const status = statusLabel(facts.statusText || facts.state || facts.provisioning || resource.state) || "Unknown";
  const role = type.includes("/databases") ? "Database" : type.includes("/elasticpools") ? "Pool" : type.includes("/servers") ? "Server" : "";
  const sized = role === "Database" || role === "Pool"
    ? sqlSize(facts)
    : serviceId === "mysql" || serviceId === "postgresql"
      ? { ...flexibleSize(facts.sku), storage: facts.storageGb ? `${facts.storageGb} GB` : "", compute: facts.tier || "" }
      : serviceId === "redis"
        ? redisSize(facts)
        : {};
  const backup = facts.backup || (facts.backupDays ? `${facts.backupDays} days` : "");
  return {
    ...resource,
    status,
    role,
    server: facts.server || "",
    version: facts.version || "",
    sku: facts.sku || resource.sku || "",
    tier: facts.accessTier || facts.tier || "",
    capacity: facts.capacity || "",
    family: facts.family || "",
    kind: serviceId === "cosmos" ? (COSMOS_API[facts.kind] || facts.kind || "") : (facts.kind || ""),
    api: COSMOS_API[facts.kind] || facts.kind || "",
    consistency: facts.consistency || "",
    backup,
    zone: yesNo(facts.zoneRedundant) || facts.zone || "None",
    public: yesNo(facts.publicNet),
    host: facts.endpoint || facts.host || "",
    https: yesNo(facts.httpsTraffic || facts.https),
    tls: facts.tls || "",
    hns: yesNo(facts.hns) === "Yes" ? "Yes" : yesNo(facts.hns) === "No" ? "No" : "",
    ha: haLabel(facts.ha),
    storage: sized.storage || (facts.storageGb ? `${facts.storageGb} GB` : ""),
    vCores: sized.vCores || "",
    memory: sized.memory || "",
    compute: sized.compute || "",
    iops: facts.iops || "",
    network: facts.netDefault || "",
    addresses: addressList(facts.ipRules),
    provisioning: facts.provisioning || "",
  };
}

export function resourcesFor(model, serviceId) {
  const rows = (model?.resources || [])
    .filter((item) => item.service === serviceId)
    .map((item) => presentResource(serviceId, item));
  if (serviceId !== "sql") return rows;
  const servers = new Map(rows.filter((row) => row.role === "Server").map((row) => [row.name.toLowerCase(), row]));
  return rows.map((row) => {
    if (row.role !== "Database") return row;
    const server = servers.get(String(row.server || "").toLowerCase());
    if (!server) return row;
    return { ...row, public: row.public || server.public, host: row.host || server.host };
  });
}

export function healthFor(status) {
  return healthBucket(status);
}

export { signalValue, serviceById };
