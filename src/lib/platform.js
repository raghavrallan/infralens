import { sanitizeClause, signalValue } from "./compute.js";
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

function localAuthLabel(value) {
  const text = tidy(value).toLowerCase();
  if (text === "true") return "Off";
  if (text === "false") return "On";
  return tidy(value);
}

export const PLATFORM_DEPTH = {
  "key-vaults": {
    summary: "SKU, soft delete, purge protection, and RBAC for each vault. Keys lists key, secret, and certificate names.",
    metric: { name: "ServiceApiHit", aggregation: "Count", unit: "", label: "API hits" },
    columns: [["name", "Name"], ["status", "Status"], ["sku", "SKU"], ["soft", "Soft delete"], ["purge", "Purge protection"], ["rbac", "RBAC"], ["public", "Public"], ["location", "Region"]],
    essentials: [["status", "Status"], ["sku", "SKU"], ["soft", "Soft delete"], ["purge", "Purge protection"], ["rbac", "RBAC authorization"], ["public", "Public network"], ["host", "Vault URI"], ["location", "Region"], ["group", "Resource group"]],
    availability: [["status", "Status"], ["soft", "Soft delete"], ["purge", "Purge protection"], ["public", "Public network"]],
  },
  "api-management": {
    summary: "SKU, capacity, virtual network, and gateway URL for each service. APIs lists the current API set.",
    metric: { name: "Requests", aggregation: "Total", unit: "", label: "Requests" },
    columns: [["name", "Name"], ["status", "Status"], ["sku", "SKU"], ["capacity", "Capacity"], ["vnet", "Virtual network"], ["public", "Public"], ["location", "Region"]],
    essentials: [["status", "Status"], ["sku", "SKU"], ["capacity", "Capacity"], ["vnet", "Virtual network"], ["public", "Public network"], ["host", "Gateway"], ["location", "Region"], ["group", "Resource group"]],
    availability: [["status", "Status"], ["sku", "SKU"], ["vnet", "Virtual network"], ["public", "Public network"]],
  },
  "service-bus": {
    summary: "SKU, public access, local auth, and zone redundancy for each namespace. Queues lists queues and topics.",
    metric: { name: "IncomingRequests", aggregation: "Total", unit: "", label: "Requests" },
    columns: [["name", "Name"], ["status", "Status"], ["sku", "SKU"], ["tier", "Tier"], ["public", "Public"], ["local", "Local auth"], ["zone", "Zone redundant"], ["location", "Region"]],
    essentials: [["status", "Status"], ["sku", "SKU"], ["tier", "Tier"], ["capacity", "Capacity"], ["public", "Public network"], ["local", "Local auth"], ["zone", "Zone redundant"], ["host", "Endpoint"], ["location", "Region"], ["group", "Resource group"]],
    availability: [["status", "Status"], ["sku", "SKU"], ["public", "Public network"], ["zone", "Zone redundant"]],
  },
  "event-hubs": {
    summary: "SKU, Kafka, auto-inflate, and public access for each namespace. Hubs lists the event hubs inside it.",
    metric: { name: "IncomingMessages", aggregation: "Total", unit: "", label: "Incoming" },
    columns: [["name", "Name"], ["status", "Status"], ["sku", "SKU"], ["tier", "Tier"], ["kafka", "Kafka"], ["inflate", "Auto-inflate"], ["public", "Public"], ["location", "Region"]],
    essentials: [["status", "Status"], ["sku", "SKU"], ["tier", "Tier"], ["capacity", "Capacity"], ["kafka", "Kafka"], ["inflate", "Auto-inflate"], ["public", "Public network"], ["zone", "Zone redundant"], ["host", "Endpoint"], ["location", "Region"], ["group", "Resource group"]],
    availability: [["status", "Status"], ["sku", "SKU"], ["kafka", "Kafka"], ["public", "Public network"]],
  },
  "logic-apps": {
    summary: "Workflow state for each logic app. Runs lists the latest workflow runs.",
    metric: { name: "RunsStarted", aggregation: "Total", unit: "", label: "Runs started" },
    columns: [["name", "Name"], ["status", "Status"], ["sku", "SKU"], ["location", "Region"], ["group", "Resource group"]],
    essentials: [["status", "Status"], ["sku", "SKU"], ["location", "Region"], ["group", "Resource group"]],
    availability: [["status", "Status"], ["sku", "SKU"]],
  },
  cognitive: {
    summary: "Kind, SKU, endpoint, and public access for each account. Deployments lists models on the selected account.",
    metric: { name: "TotalCalls", aggregation: "Total", unit: "", label: "Calls" },
    columns: [["name", "Name"], ["status", "Status"], ["kind", "Kind"], ["sku", "SKU"], ["public", "Public"], ["local", "Local auth"], ["location", "Region"]],
    essentials: [["status", "Status"], ["kind", "Kind"], ["sku", "SKU"], ["public", "Public network"], ["local", "Local auth"], ["domain", "Custom domain"], ["host", "Endpoint"], ["location", "Region"], ["group", "Resource group"]],
    availability: [["status", "Status"], ["kind", "Kind"], ["sku", "SKU"], ["public", "Public network"]],
  },
};

export const LIVE_METRICS = {
  "key-vaults": [
    { name: "ServiceApiHit", aggregation: "Count", unit: "", label: "API hits" },
    { name: "ServiceApiLatency", aggregation: "Average", unit: "ms", label: "Latency" },
    { name: "Availability", aggregation: "Average", unit: "%", label: "Availability" },
    { name: "SaturationShoebox", aggregation: "Average", unit: "%", label: "Saturation" },
  ],
  "api-management": [
    { name: "Requests", aggregation: "Total", unit: "", label: "Requests" },
    { name: "FailedRequests", aggregation: "Total", unit: "", label: "Failed requests" },
    { name: "Duration", aggregation: "Average", unit: "ms", label: "Duration" },
    { name: "Capacity", aggregation: "Average", unit: "%", label: "Capacity" },
  ],
  "service-bus": [
    { name: "IncomingRequests", aggregation: "Total", unit: "", label: "Requests" },
    { name: "SuccessfulRequests", aggregation: "Total", unit: "", label: "Successful" },
    { name: "ServerErrors", aggregation: "Total", unit: "", label: "Server errors" },
    { name: "ThrottledRequests", aggregation: "Total", unit: "", label: "Throttled" },
    { name: "ActiveConnections", aggregation: "Average", unit: "", label: "Connections" },
  ],
  "event-hubs": [
    { name: "IncomingMessages", aggregation: "Total", unit: "", label: "Incoming" },
    { name: "OutgoingMessages", aggregation: "Total", unit: "", label: "Outgoing" },
    { name: "SuccessfulRequests", aggregation: "Total", unit: "", label: "Successful" },
    { name: "ThrottledRequests", aggregation: "Total", unit: "", label: "Throttled" },
    { name: "ActiveConnections", aggregation: "Average", unit: "", label: "Connections" },
  ],
  "logic-apps": [
    { name: "RunsStarted", aggregation: "Total", unit: "", label: "Runs started" },
    { name: "RunsSucceeded", aggregation: "Total", unit: "", label: "Runs succeeded" },
    { name: "RunsFailed", aggregation: "Total", unit: "", label: "Runs failed" },
    { name: "ActionsFailed", aggregation: "Total", unit: "", label: "Actions failed" },
    { name: "TriggersStarted", aggregation: "Total", unit: "", label: "Triggers" },
  ],
  cognitive: [
    { name: "TotalCalls", aggregation: "Total", unit: "", label: "Calls" },
    { name: "SuccessfulCalls", aggregation: "Total", unit: "", label: "Successful" },
    { name: "TotalErrors", aggregation: "Total", unit: "", label: "Errors" },
    { name: "Latency", aggregation: "Average", unit: "ms", label: "Latency" },
    { name: "BlockedCalls", aggregation: "Total", unit: "", label: "Blocked" },
    { name: "AzureOpenAiRequests", aggregation: "Total", unit: "", label: "OpenAI requests" },
    { name: "ProcessedPromptTokens", aggregation: "Total", unit: "", label: "Prompt tokens" },
    { name: "GeneratedTokens", aggregation: "Total", unit: "", label: "Generated tokens" },
  ],
};

const KQL_SHAPES = {
  "key-vaults": {
    where: "| where type =~ 'microsoft.keyvault/vaults'",
    extend: "| extend status = tostring(properties.provisioningState), skuName = coalesce(tostring(sku.name), tostring(properties.sku.name), ''), soft = tostring(properties.enableSoftDelete), purge = tostring(properties.enablePurgeProtection), rbac = tostring(properties.enableRbacAuthorization), public = tostring(properties.publicNetworkAccess)",
    project: "name, resourceGroup, location, status, skuName, soft, purge, rbac, public",
    columns: [["name", "Name"], ["status", "Status"], ["skuName", "SKU"], ["soft", "Soft delete"], ["purge", "Purge protection"], ["rbac", "RBAC"], ["public", "Public"], ["location", "Region"]],
    examples: [["Succeeded", "| where status =~ 'Succeeded'"], ["Soft delete", "| where soft =~ 'true'"], ["East US", "| where location == 'eastus'"]],
  },
  "api-management": {
    where: "| where type =~ 'microsoft.apimanagement/service'",
    extend: "| extend status = tostring(properties.provisioningState), skuName = tostring(sku.name), capacity = tostring(sku.capacity), vnet = tostring(properties.virtualNetworkType), public = tostring(properties.publicNetworkAccess)",
    project: "name, resourceGroup, location, status, skuName, capacity, vnet, public",
    columns: [["name", "Name"], ["status", "Status"], ["skuName", "SKU"], ["capacity", "Capacity"], ["vnet", "Virtual network"], ["public", "Public"], ["location", "Region"]],
    examples: [["Consumption", "| where skuName =~ 'Consumption'"], ["Succeeded", "| where status =~ 'Succeeded'"], ["East US", "| where location == 'eastus'"]],
  },
  "service-bus": {
    where: "| where type =~ 'microsoft.servicebus/namespaces'",
    extend: "| extend status = coalesce(tostring(properties.status), tostring(properties.provisioningState), ''), skuName = tostring(sku.name), tier = tostring(sku.tier), public = tostring(properties.publicNetworkAccess), zone = tostring(properties.zoneRedundant)",
    project: "name, resourceGroup, location, status, skuName, tier, public, zone",
    columns: [["name", "Name"], ["status", "Status"], ["skuName", "SKU"], ["tier", "Tier"], ["public", "Public"], ["zone", "Zone"], ["location", "Region"]],
    examples: [["Succeeded", "| where status =~ 'Succeeded'"], ["Premium", "| where skuName =~ 'Premium'"], ["East US", "| where location == 'eastus'"]],
  },
  "event-hubs": {
    where: "| where type =~ 'microsoft.eventhub/namespaces'",
    extend: "| extend status = coalesce(tostring(properties.status), tostring(properties.provisioningState), ''), skuName = tostring(sku.name), kafka = tostring(properties.kafkaEnabled), inflate = tostring(properties.isAutoInflateEnabled), public = tostring(properties.publicNetworkAccess)",
    project: "name, resourceGroup, location, status, skuName, kafka, inflate, public",
    columns: [["name", "Name"], ["status", "Status"], ["skuName", "SKU"], ["kafka", "Kafka"], ["inflate", "Auto-inflate"], ["public", "Public"], ["location", "Region"]],
    examples: [["Kafka", "| where kafka =~ 'true'"], ["Succeeded", "| where status =~ 'Succeeded'"], ["East US", "| where location == 'eastus'"]],
  },
  "logic-apps": {
    where: "| where type =~ 'microsoft.logic/workflows'",
    extend: "| extend status = tostring(properties.state), provisioning = tostring(properties.provisioningState)",
    project: "name, resourceGroup, location, status, provisioning",
    columns: [["name", "Name"], ["status", "State"], ["provisioning", "Provisioning"], ["location", "Region"]],
    examples: [["Enabled", "| where status =~ 'Enabled'"], ["Disabled", "| where status =~ 'Disabled'"], ["East US", "| where location == 'eastus'"]],
  },
  cognitive: {
    where: "| where type =~ 'microsoft.cognitiveservices/accounts'",
    extend: "| extend status = tostring(properties.provisioningState), kindName = tostring(kind), skuName = tostring(sku.name), public = tostring(properties.publicNetworkAccess), local = tostring(properties.disableLocalAuth)",
    project: "name, resourceGroup, location, status, kindName, skuName, public, local",
    columns: [["name", "Name"], ["status", "Status"], ["kindName", "Kind"], ["skuName", "SKU"], ["public", "Public"], ["location", "Region"]],
    examples: [["OpenAI", "| where kindName =~ 'OpenAI'"], ["Succeeded", "| where status =~ 'Succeeded'"], ["East US", "| where location == 'eastus'"]],
  },
};

export const CATALOG_LABEL = {
  "key-vaults": "Keys",
  "api-management": "APIs",
  "service-bus": "Queues",
  "event-hubs": "Hubs",
  "logic-apps": "Runs",
  cognitive: "Deployments",
};

export function isPlatform(id) {
  return Boolean(PLATFORM_DEPTH[id]);
}

export function platformHref(id) {
  return isPlatform(id) ? `/platform/${id}` : "";
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
    "key-vaults": ["sku", "SKUs"],
    "api-management": ["sku", "SKUs"],
    "service-bus": ["sku", "SKUs"],
    "event-hubs": ["sku", "SKUs"],
    "logic-apps": ["status", "States"],
    cognitive: ["kind", "Kinds"],
  }[serviceId] || ["location", "Regions"];
  return facet;
}

export function presentResource(serviceId, resource) {
  const facts = resource.facts || {};
  const status = tidy(facts.workflowState || facts.operational || facts.provisioning || facts.statusText || resource.state) || "Unknown";
  return {
    ...resource,
    status,
    sku: tidy(facts.sku || resource.sku),
    tier: tidy(facts.tier),
    kind: tidy(facts.kind),
    capacity: tidy(facts.capacity),
    public: yesNo(facts.publicNet),
    soft: yesNo(facts.softDelete),
    purge: yesNo(facts.purge),
    rbac: yesNo(facts.rbacAuth),
    vnet: tidy(facts.vnetType),
    local: localAuthLabel(facts.localAuth),
    kafka: yesNo(facts.kafka),
    inflate: yesNo(facts.autoInflate),
    zone: yesNo(facts.zoneRedundant) || tidy(facts.zone) || "None",
    host: tidy(facts.endpoint || facts.vaultUri || facts.gatewayUrl || facts.host),
    domain: tidy(facts.customDomain),
  };
}

export function resourcesFor(model, serviceId) {
  return (model?.resources || [])
    .filter((item) => item.service === serviceId)
    .map((item) => presentResource(serviceId, item));
}

export { signalValue, serviceById };
