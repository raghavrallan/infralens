import { serviceById } from "./services.js";

function pick(value) {
  const text = String(value ?? "").trim();
  if (!text || text.toLowerCase() === "null") return "";
  return text;
}

function tidy(value) {
  return pick(value).replace(/^VM\s+/i, "").replace(/\s+/g, " ").trim();
}

export function factsFromRow(row) {
  return {
    power: tidy(row.power),
    size: tidy(row.vmSize || row.skuName || row.sku),
    os: tidy(row.osType),
    image: tidy(row.containerImage || row.imageName),
    zone: tidy(row.zoneName),
    provisioning: tidy(row.provisioning),
    state: tidy(row.runningStatus || row.siteState || row.powerCode),
    host: tidy(row.hostName || row.fqdn),
    https: tidy(row.httpsFlag),
    availability: tidy(row.availabilityState),
    runtime: tidy(row.runtime),
    plan: tidy(row.planName),
    minReplicas: tidy(row.minReplicas),
    maxReplicas: tidy(row.maxReplicas),
    ingress: tidy(row.ingressExternal),
    revision: tidy(row.revision),
    environment: tidy(row.environmentName),
    kubernetes: tidy(row.k8sVersion),
    plugin: tidy(row.networkPlugin),
    pools: tidy(row.poolCount),
    poolSize: tidy(row.poolSize),
    poolNodes: tidy(row.poolNodes),
    capacity: tidy(row.skuCapacity),
    orchestration: tidy(row.orchestration),
    upgrade: tidy(row.upgradeMode),
    tier: tidy(row.skuTier),
    disks: tidy(row.diskCount),
    sku: tidy(row.skuName || row.sku),
    revisionMode: tidy(row.revisionMode),
    statusText: tidy(row.statusText),
    version: tidy(row.versionText),
    publicNet: tidy(row.publicNet),
    endpoint: tidy(row.dataEndpoint),
    tls: tidy(row.tlsVersion),
    httpsTraffic: tidy(row.httpsTraffic),
    accessTier: tidy(row.accessTier),
    ha: tidy(row.haMode),
    storageGb: tidy(row.storageGb),
    backupDays: tidy(row.backupDays),
    consistency: tidy(row.consistencyLevel),
    backup: tidy(row.backupKind),
    zoneRedundant: tidy(row.zoneRedundant),
    family: tidy(row.skuFamily),
    server: tidy(row.serverName),
    kind: tidy(row.kindText),
    maxBytes: tidy(row.maxBytes),
    minCapacity: tidy(row.minCapacity),
    edition: tidy(row.edition),
    iops: tidy(row.iops),
    netDefault: tidy(row.netDefault),
    ipRules: tidy(row.ipRules),
    addressSpace: tidy(row.addressSpace),
    subnetCount: tidy(row.subnetCount),
    ddos: tidy(row.ddos),
    operational: tidy(row.operational),
    frontendCount: tidy(row.frontendCount),
    backendCount: tidy(row.backendCount),
    ruleCount: tidy(row.ruleCount),
    probeCount: tidy(row.probeCount),
    listenerCount: tidy(row.listenerCount),
    threatIntel: tidy(row.threatIntel),
    enabledState: tidy(row.enabledState),
    policyName: tidy(row.policyName),
    waf: tidy(row.wafEnabled),
    scaleMin: tidy(row.scaleMin),
    scaleMax: tidy(row.scaleMax),
    softDelete: tidy(row.softDelete),
    purge: tidy(row.purgeProtection),
    rbacAuth: tidy(row.rbacAuth),
    vaultUri: tidy(row.vaultUri),
    gatewayUrl: tidy(row.gatewayUrl),
    vnetType: tidy(row.vnetType),
    workflowState: tidy(row.workflowState),
    localAuth: tidy(row.localAuth),
    kafka: tidy(row.kafka),
    autoInflate: tidy(row.autoInflate),
    customDomain: tidy(row.customDomain),
  };
}

function yesNo(value) {
  if (value === "true") return "Yes";
  if (value === "false") return "No";
  return "";
}

function ingressLabel(value) {
  if (value === "true") return "External";
  if (value === "false") return "Internal";
  return value ? "Off" : "";
}

export const COMPUTE_DEPTH = {
  "virtual-machines": {
    summary: "Power, size, operating system, availability zone, and host CPU for each machine.",
    metric: { name: "Percentage CPU", aggregation: "Average", unit: "%", label: "CPU" },
    metricNote: "Host CPU is the platform metric Azure collects for every virtual machine.",
    columns: [
      ["name", "Name"],
      ["status", "Status"],
      ["size", "Size"],
      ["os", "OS"],
      ["zone", "Zone"],
      ["location", "Region"],
      ["group", "Resource group"],
    ],
    essentials: [
      ["status", "Status"],
      ["size", "Size"],
      ["os", "Operating system"],
      ["image", "Image"],
      ["zone", "Availability zone"],
      ["disks", "Data disks"],
      ["provisioning", "Provisioning"],
      ["location", "Region"],
      ["group", "Resource group"],
    ],
    availability: [
      ["zone", "Availability zone"],
      ["provisioning", "Provisioning"],
      ["os", "OS disk"],
      ["disks", "Data disks"],
    ],
  },
  "vm-scale-sets": {
    summary: "Capacity, orchestration, and upgrade mode for each scale set.",
    metric: { name: "Percentage CPU", aggregation: "Average", unit: "%", label: "CPU" },
    metricNote: "CPU is the average host percentage across the scale set.",
    columns: [
      ["name", "Name"],
      ["status", "Status"],
      ["size", "SKU"],
      ["capacity", "Capacity"],
      ["orchestration", "Orchestration"],
      ["upgrade", "Upgrade"],
      ["location", "Region"],
      ["group", "Resource group"],
    ],
    essentials: [
      ["status", "Status"],
      ["size", "SKU"],
      ["tier", "Tier"],
      ["capacity", "Capacity"],
      ["orchestration", "Orchestration"],
      ["upgrade", "Upgrade policy"],
      ["zone", "Zones"],
      ["provisioning", "Provisioning"],
      ["location", "Region"],
      ["group", "Resource group"],
    ],
    availability: [
      ["zone", "Zones"],
      ["capacity", "Capacity"],
      ["upgrade", "Upgrade policy"],
      ["provisioning", "Provisioning"],
    ],
  },
  "app-service": {
    summary: "Run state, plan, hostname, HTTPS, and request count for each web app.",
    metric: { name: "Requests", aggregation: "Total", unit: "", label: "Requests" },
    metricNote: "Requests are the platform total Azure records for the app over the last hour.",
    columns: [
      ["name", "Name"],
      ["status", "Status"],
      ["plan", "Plan"],
      ["runtime", "Runtime"],
      ["https", "HTTPS only"],
      ["host", "Hostname"],
      ["location", "Region"],
    ],
    essentials: [
      ["status", "Status"],
      ["availability", "Availability"],
      ["plan", "App Service plan"],
      ["runtime", "Runtime"],
      ["https", "HTTPS only"],
      ["host", "Default hostname"],
      ["location", "Region"],
      ["group", "Resource group"],
    ],
    availability: [
      ["status", "State"],
      ["availability", "Availability"],
      ["https", "HTTPS only"],
      ["host", "Hostname"],
    ],
  },
  functions: {
    summary: "Run state, runtime, plan, and request count for each function app.",
    metric: { name: "Requests", aggregation: "Total", unit: "", label: "Requests" },
    metricNote: "Requests are the platform total Azure records for the function app over the last hour.",
    columns: [
      ["name", "Name"],
      ["status", "Status"],
      ["runtime", "Runtime"],
      ["plan", "Plan"],
      ["https", "HTTPS only"],
      ["location", "Region"],
      ["group", "Resource group"],
    ],
    essentials: [
      ["status", "Status"],
      ["runtime", "Runtime"],
      ["plan", "Plan"],
      ["https", "HTTPS only"],
      ["host", "Hostname"],
      ["availability", "Availability"],
      ["location", "Region"],
      ["group", "Resource group"],
    ],
    availability: [
      ["status", "State"],
      ["availability", "Availability"],
      ["https", "HTTPS only"],
      ["host", "Hostname"],
    ],
  },
  "container-apps": {
    summary: "Running status, replica range, ingress, and the active revision for each app.",
    metric: { name: "Replicas", aggregation: "Average", unit: "", label: "Replicas" },
    metricNote: "Replicas are the average active replica count Azure reports for the last hour.",
    columns: [
      ["name", "Name"],
      ["status", "Status"],
      ["replicas", "Replicas"],
      ["ingress", "Ingress"],
      ["revision", "Revision"],
      ["image", "Artifact"],
      ["environment", "Environment"],
      ["location", "Region"],
      ["group", "Resource group"],
    ],
    essentials: [
      ["status", "Running status"],
      ["provisioning", "Provisioning"],
      ["replicas", "Replica range"],
      ["ingress", "Ingress"],
      ["host", "FQDN"],
      ["revision", "Latest revision"],
      ["revisionMode", "Revision mode"],
      ["image", "Artifact"],
      ["environment", "Environment"],
      ["location", "Region"],
      ["group", "Resource group"],
    ],
    availability: [
      ["status", "Running status"],
      ["provisioning", "Provisioning"],
      ["replicas", "Replica range"],
      ["ingress", "Ingress"],
      ["revision", "Latest revision"],
    ],
  },
  kubernetes: {
    summary: "Power, Kubernetes version, node pools, and network plugin for each cluster.",
    metric: { name: "node_cpu_usage_percentage", aggregation: "Average", unit: "%", label: "Node CPU" },
    metricNote: "Node CPU is the platform percentage Azure Monitor keeps for the cluster.",
    columns: [
      ["name", "Name"],
      ["status", "Status"],
      ["kubernetes", "Version"],
      ["pools", "Node pools"],
      ["poolNodes", "Nodes"],
      ["poolSize", "Node size"],
      ["plugin", "Network"],
      ["location", "Region"],
    ],
    essentials: [
      ["status", "Power"],
      ["provisioning", "Provisioning"],
      ["kubernetes", "Kubernetes version"],
      ["tier", "SKU tier"],
      ["pools", "Node pools"],
      ["poolNodes", "Nodes in first pool"],
      ["poolSize", "Node size"],
      ["plugin", "Network plugin"],
      ["host", "API server"],
      ["location", "Region"],
      ["group", "Resource group"],
    ],
    availability: [
      ["status", "Power"],
      ["provisioning", "Provisioning"],
      ["kubernetes", "Version"],
      ["pools", "Node pools"],
      ["poolNodes", "Nodes"],
      ["zone", "Zones"],
    ],
  },
};

export function isCompute(id) {
  return Boolean(COMPUTE_DEPTH[id]);
}

export function computeHref(id) {
  return isCompute(id) ? `/compute/${id}` : "";
}

function statusLabel(value) {
  const text = tidy(value);
  if (!text) return "";
  if (text === text.toLowerCase()) return text.charAt(0).toUpperCase() + text.slice(1);
  return text;
}

export function statusFor(serviceId, facts, resource) {
  const power = statusLabel(facts.power || resource.state);
  const state = statusLabel(facts.state);
  const provisioning = statusLabel(facts.provisioning);
  if (serviceId === "virtual-machines") return power || provisioning || "Unknown";
  if (serviceId === "vm-scale-sets") return provisioning || power || "Unknown";
  return state || provisioning || power || "Unknown";
}

export function healthBucket(status) {
  const value = String(status || "").toLowerCase();
  if (/fail|degrad|unavailable/.test(value)) return "attention";
  if (/stop|deallocat|scale to 0|paused|disabled/.test(value)) return "stopped";
  if (/run|succeed|ready|provisioned|online|available|enabled/.test(value)) return "healthy";
  return "other";
}

export function presentResource(serviceId, resource) {
  const facts = resource.facts || {};
  const status = statusFor(serviceId, facts, resource);
  const min = facts.minReplicas;
  const max = facts.maxReplicas;
  return {
    ...resource,
    status,
    size: facts.size || resource.size || "",
    os: facts.os || "",
    image: facts.image || "",
    zone: facts.zone || "None",
    provisioning: facts.provisioning || "",
    runtime: String(facts.runtime || "").replace("|", " "),
    plan: facts.plan || "",
    host: facts.host || "",
    https: yesNo(facts.https),
    availability: facts.availability || "",
    replicas: min || max ? `${min || "0"}–${max || "0"}` : "",
    ingress: ingressLabel(facts.ingress),
    revision: facts.revision || "",
    revisionMode: facts.revisionMode || "",
    environment: facts.environment || "",
    kubernetes: facts.kubernetes || "",
    plugin: facts.plugin || "",
    pools: facts.pools || "",
    poolSize: facts.poolSize || "",
    poolNodes: facts.poolNodes || "",
    capacity: facts.capacity || "",
    orchestration: facts.orchestration || "",
    upgrade: facts.upgrade || "",
    tier: facts.tier || facts.sku || resource.sku || "",
    disks: facts.disks || "",
    sku: facts.sku || resource.sku || "",
  };
}

export function resourcesFor(model, serviceId) {
  return (model?.resources || [])
    .filter((item) => item.service === serviceId)
    .map((item) => presentResource(serviceId, item));
}

export function operationsFor(model, serviceId, rows) {
  const service = serviceById(serviceId);
  const names = new Set(rows.map((item) => String(item.name || "").toLowerCase()));
  const types = new Set((service?.types || []).map((item) => item.toLowerCase()));
  return (model?.operations || model?.activity || []).filter((item) => {
    const type = String(item.resourceType || "").toLowerCase();
    if (type && [...types].some((known) => type === known || type.startsWith(`${known}/`))) return true;
    const resource = String(item.resource || "").toLowerCase();
    if (names.has(resource)) return true;
    const id = String(item.resourceId || "").toLowerCase();
    return [...names].some((name) => name && (id.endsWith(`/${name}`) || id.includes(`/${name}/`)));
  });
}

export function signalValue(value, unit) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "";
  if (unit === "%") return `${Math.round(number * 10) / 10}%`;
  if (unit === "ms") return `${Math.round(number)} ms`;
  if (unit === "B") {
    if (number >= 1e9) return `${(number / 1e9).toFixed(1)} GB`;
    if (number >= 1e6) return `${(number / 1e6).toFixed(1)} MB`;
    if (number >= 1e3) return `${(number / 1e3).toFixed(1)} KB`;
    return `${Math.round(number)} B`;
  }
  if (number >= 100) return String(Math.round(number));
  return String(Math.round(number * 10) / 10);
}

export const LIVE_METRICS = {
  "virtual-machines": [
    { name: "Percentage CPU", aggregation: "Average", unit: "%", label: "CPU" },
    { name: "Network In Total", aggregation: "Total", unit: "B", label: "Network in" },
    { name: "Network Out Total", aggregation: "Total", unit: "B", label: "Network out" },
    { name: "VmAvailabilityMetric", aggregation: "Average", unit: "", label: "Host up" },
  ],
  "vm-scale-sets": [
    { name: "Percentage CPU", aggregation: "Average", unit: "%", label: "CPU" },
    { name: "Network In Total", aggregation: "Total", unit: "B", label: "Network in" },
  ],
  "app-service": [
    { name: "Requests", aggregation: "Total", unit: "", label: "Requests" },
    { name: "Http5xx", aggregation: "Total", unit: "", label: "Server errors" },
    { name: "AverageResponseTime", aggregation: "Average", unit: "ms", label: "Response time" },
    { name: "MemoryWorkingSet", aggregation: "Average", unit: "B", label: "Memory" },
  ],
  functions: [
    { name: "Requests", aggregation: "Total", unit: "", label: "Requests" },
    { name: "Http5xx", aggregation: "Total", unit: "", label: "Server errors" },
    { name: "AverageResponseTime", aggregation: "Average", unit: "ms", label: "Response time" },
  ],
  "container-apps": [
    { name: "Replicas", aggregation: "Average", unit: "", label: "Replicas" },
    { name: "Requests", aggregation: "Total", unit: "", label: "Requests" },
    { name: "RestartCount", aggregation: "Total", unit: "", label: "Restarts" },
  ],
  kubernetes: [
    { name: "node_cpu_usage_percentage", aggregation: "Average", unit: "%", label: "Node CPU" },
    { name: "node_memory_rss_percentage", aggregation: "Average", unit: "%", label: "Node memory" },
  ],
};

export const METRIC_WINDOWS = [
  ["15m", "Last 15 minutes"],
  ["1h", "Last hour"],
  ["6h", "Last 6 hours"],
];

const KQL_SHAPES = {
  "virtual-machines": {
    type: "microsoft.compute/virtualmachines",
    extend: "| extend size = tostring(properties.hardwareProfile.vmSize), os = tostring(properties.storageProfile.osDisk.osType), image = strcat(tostring(properties.storageProfile.imageReference.offer), ' ', tostring(properties.storageProfile.imageReference.sku)), power = tostring(properties.extended.instanceView.powerState.displayStatus), zone = iff(isnull(zones), '', strcat_array(zones, ', ')), disks = tostring(array_length(properties.storageProfile.dataDisks)), provisioning = tostring(properties.provisioningState)",
    project: "name, resourceGroup, location, size, os, image, power, zone, disks, provisioning",
    columns: [["name", "Name"], ["power", "Power"], ["size", "Size"], ["os", "OS"], ["image", "Image"], ["zone", "Zone"], ["location", "Region"], ["resourceGroup", "Resource group"]],
    examples: [["Running", "| where power =~ 'VM running'"], ["Linux", "| where os =~ 'Linux'"], ["Windows", "| where os =~ 'Windows'"], ["East US", "| where location == 'eastus'"]],
  },
  "vm-scale-sets": {
    type: "microsoft.compute/virtualmachinescalesets",
    extend: "| extend skuName = tostring(sku.name), capacity = tostring(sku.capacity), upgrade = tostring(properties.upgradePolicy.mode), orchestration = tostring(properties.orchestrationMode), provisioning = tostring(properties.provisioningState)",
    project: "name, resourceGroup, location, skuName, capacity, upgrade, orchestration, provisioning",
    columns: [["name", "Name"], ["skuName", "SKU"], ["capacity", "Capacity"], ["upgrade", "Upgrade"], ["orchestration", "Orchestration"], ["location", "Region"], ["resourceGroup", "Resource group"]],
    examples: [["Manual upgrade", "| where upgrade =~ 'Manual'"], ["East US", "| where location == 'eastus'"]],
  },
  "app-service": {
    type: "microsoft.web/sites",
    kind: "| where kind !contains 'function'",
    extend: "| extend state = tostring(properties.state), host = tostring(properties.defaultHostName), https = iff(tostring(properties.httpsOnly) =~ 'true', 'Yes', 'No'), runtime = coalesce(tostring(properties.siteConfig.linuxFxVersion), tostring(properties.siteConfig.windowsFxVersion), tostring(properties.siteConfig.netFrameworkVersion), ''), plan = extract('/serverfarms/([^/]+)$', 1, tostring(properties.serverFarmId)), skuName = tostring(sku.name), availability = tostring(properties.availabilityState)",
    project: "name, resourceGroup, location, state, runtime, plan, host, https, skuName, availability",
    columns: [["name", "Name"], ["state", "State"], ["runtime", "Runtime"], ["plan", "Plan"], ["https", "HTTPS"], ["skuName", "SKU"], ["host", "Host"], ["location", "Region"]],
    examples: [["Running", "| where state =~ 'Running'"], ["Linux", "| where kind contains 'linux'"], ["East US", "| where location == 'eastus'"]],
  },
  functions: {
    type: "microsoft.web/sites",
    kind: "| where kind contains 'function'",
    extend: "| extend state = tostring(properties.state), host = tostring(properties.defaultHostName), https = iff(tostring(properties.httpsOnly) =~ 'true', 'Yes', 'No'), runtime = coalesce(tostring(properties.siteConfig.linuxFxVersion), tostring(properties.siteConfig.windowsFxVersion), tostring(properties.siteConfig.netFrameworkVersion), ''), plan = extract('/serverfarms/([^/]+)$', 1, tostring(properties.serverFarmId)), availability = tostring(properties.availabilityState)",
    project: "name, resourceGroup, location, state, runtime, plan, host, https, availability",
    columns: [["name", "Name"], ["state", "State"], ["runtime", "Runtime"], ["plan", "Plan"], ["https", "HTTPS"], ["host", "Host"], ["location", "Region"]],
    examples: [["Running", "| where state =~ 'Running'"], ["Stopped", "| where state =~ 'Stopped'"], ["East US", "| where location == 'eastus'"]],
  },
  "container-apps": {
    type: "microsoft.app/containerapps",
    extend: "| extend running = tostring(properties.runningStatus), revision = tostring(properties.latestRevisionName), image = extract('image\":\"([^\"]+)', 1, tostring(properties.template.containers)), environment = extract('/managedEnvironments/([^/]+)$', 1, tostring(properties.managedEnvironmentId)), ingress = iff(isnull(properties.configuration.ingress), 'Off', iff(tostring(properties.configuration.ingress.external) =~ 'true', 'External', 'Internal')), minReplicas = tostring(properties.template.scale.minReplicas), maxReplicas = tostring(properties.template.scale.maxReplicas), fqdn = tostring(properties.configuration.ingress.fqdn)",
    project: "name, resourceGroup, location, running, revision, image, environment, ingress, minReplicas, maxReplicas, fqdn",
    columns: [["name", "Name"], ["running", "Running"], ["revision", "Revision"], ["image", "Artifact"], ["environment", "Environment"], ["ingress", "Ingress"], ["location", "Region"]],
    examples: [["Running", "| where running =~ 'Running'"], ["Stopped", "| where running =~ 'Stopped'"], ["External", "| where ingress =~ 'External'"]],
  },
  kubernetes: {
    type: "microsoft.containerservice/managedclusters",
    extend: "| extend version = tostring(properties.kubernetesVersion), power = tostring(properties.powerState.code), plugin = tostring(properties.networkProfile.networkPlugin), pools = tostring(array_length(properties.agentPoolProfiles)), skuName = tostring(sku.name), provisioning = tostring(properties.provisioningState)",
    project: "name, resourceGroup, location, version, power, plugin, pools, skuName, provisioning",
    columns: [["name", "Name"], ["version", "Version"], ["power", "Power"], ["plugin", "Network"], ["pools", "Pools"], ["skuName", "SKU"], ["location", "Region"]],
    examples: [["Running", "| where power =~ 'Running'"], ["East US", "| where location == 'eastus'"]],
  },
};

export function metricChoice(serviceId, name) {
  const list = LIVE_METRICS[serviceId] || [];
  return list.find((item) => item.name === name) || list[0] || null;
}

export function sanitizeClause(clause) {
  const text = String(clause || "").trim();
  if (!text) return "";
  if (text.length > 240) throw new Error("Keep the extra filter under 240 characters.");
  if (!/^\| where [A-Za-z0-9_.'"=!~<>()\- ]+$/.test(text)) throw new Error("Add one | where line, using letters, numbers, and quotes.");
  if (/externaldata|evaluate|invoke|http|union|join|materialize/i.test(text)) throw new Error("That filter is not available here.");
  return text;
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
  const kind = shape.kind ? `\n${shape.kind}` : "";
  return `Resources
| where type =~ '${shape.type}'${kind}
${shape.extend}
${extra ? `${extra}\n` : ""}| project ${shape.project}
| take 40`;
}

export function logKql(name, kind = "console") {
  const app = String(name || "").replace(/[^a-z0-9-]/g, "") || "your-app";
  if (kind === "system") {
    return `ContainerAppSystemLogs_CL
| where ContainerAppName_s == '${app}'
| project TimeGenerated, ReplicaName_s, Reason_s
| order by TimeGenerated desc
| take 40`;
  }
  return `ContainerAppConsoleLogs_CL
| where ContainerAppName_s == '${app}'
| project TimeGenerated, RevisionName_s, Log_s
| order by TimeGenerated desc
| take 40`;
}

export function metricSeries(payload, aggregation) {
  const key = String(aggregation || "Average").toLowerCase();
  return (payload?.value?.[0]?.timeseries?.[0]?.data || [])
    .filter((point) => point?.[key] !== null && point?.[key] !== undefined)
    .map((point) => ({ time: point.timeStamp, value: Number(point[key]) }));
}

export function overviewFacets(serviceId) {
  const facet = {
    "virtual-machines": ["size", "Sizes"],
    "vm-scale-sets": ["capacity", "Capacity"],
    "app-service": ["runtime", "Runtimes"],
    functions: ["runtime", "Runtimes"],
    "container-apps": ["environment", "Environments"],
    kubernetes: ["kubernetes", "Versions"],
  }[serviceId] || ["location", "Regions"];
  return facet;
}

export function latestMetricPoint(payload, aggregation) {
  const points = payload?.value?.[0]?.timeseries?.[0]?.data || [];
  const key = String(aggregation || "Average").toLowerCase();
  const point = [...points].reverse().find((item) => item?.[key] !== null && item?.[key] !== undefined);
  return point ? Number(point[key]) : null;
}
