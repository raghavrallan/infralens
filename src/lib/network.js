import { sanitizeClause, signalValue } from "./compute.js";
import { serviceById } from "./services.js";

function tidy(value) {
  const text = String(value ?? "").trim();
  if (!text || text.toLowerCase() === "null") return "";
  return text;
}

function count(value) {
  const text = tidy(value);
  return text;
}

function ddosLabel(value) {
  const text = tidy(value).toLowerCase();
  if (text === "true") return "On";
  if (text === "false") return "Off";
  return tidy(value);
}

function capacityLabel(facts) {
  const min = tidy(facts.scaleMin);
  const max = tidy(facts.scaleMax);
  if (min && max) return `${min}–${max}`;
  if (min) return min;
  return tidy(facts.capacity);
}

export const NETWORK_DEPTH = {
  "virtual-networks": {
    summary: "Address space, subnet count, and DDoS for each virtual network. Subnets lists the prefixes in the selected network.",
    metric: null,
    columns: [["name", "Name"], ["status", "Status"], ["address", "Address space"], ["subnets", "Subnets"], ["ddos", "DDoS"], ["location", "Region"], ["group", "Resource group"]],
    essentials: [["status", "Status"], ["address", "Address space"], ["subnets", "Subnets"], ["ddos", "DDoS"], ["location", "Region"], ["group", "Resource group"]],
    availability: [["status", "Status"], ["address", "Address space"], ["subnets", "Subnets"], ["ddos", "DDoS"]],
  },
  "application-gateways": {
    summary: "SKU, autoscale capacity, listeners, backend pools, and the WAF policy for each gateway.",
    metric: { name: "TotalRequests", aggregation: "Total", unit: "", label: "Requests" },
    columns: [["name", "Name"], ["status", "Status"], ["sku", "SKU"], ["capacity", "Capacity"], ["listeners", "Listeners"], ["backends", "Backends"], ["waf", "WAF"], ["location", "Region"]],
    essentials: [["status", "Status"], ["sku", "SKU"], ["tier", "Tier"], ["capacity", "Capacity"], ["listeners", "Listeners"], ["backends", "Backend pools"], ["frontends", "Frontends"], ["waf", "WAF policy"], ["location", "Region"], ["group", "Resource group"]],
    availability: [["status", "Status"], ["sku", "SKU"], ["capacity", "Capacity"], ["waf", "WAF policy"]],
  },
  "load-balancers": {
    summary: "SKU, frontend IPs, backend pools, rules, and health probes for each load balancer.",
    metric: { name: "ByteCount", aggregation: "Total", unit: "B", label: "Bytes" },
    columns: [["name", "Name"], ["status", "Status"], ["sku", "SKU"], ["tier", "Tier"], ["frontends", "Frontends"], ["backends", "Backends"], ["rules", "Rules"], ["probes", "Probes"], ["location", "Region"]],
    essentials: [["status", "Status"], ["sku", "SKU"], ["tier", "Tier"], ["frontends", "Frontends"], ["backends", "Backend pools"], ["rules", "Rules"], ["probes", "Probes"], ["location", "Region"], ["group", "Resource group"]],
    availability: [["status", "Status"], ["sku", "SKU"], ["rules", "Rules"], ["probes", "Probes"]],
  },
  "front-door": {
    summary: "SKU and provisioning for each Front Door profile. Endpoints lists the hosts on the selected profile.",
    metric: { name: "RequestCount", aggregation: "Total", unit: "", label: "Requests" },
    columns: [["name", "Name"], ["status", "Status"], ["sku", "SKU"], ["kind", "Kind"], ["location", "Region"], ["group", "Resource group"]],
    essentials: [["status", "Status"], ["sku", "SKU"], ["kind", "Kind"], ["location", "Region"], ["group", "Resource group"]],
    availability: [["status", "Status"], ["sku", "SKU"], ["kind", "Kind"]],
  },
  firewalls: {
    summary: "SKU, threat intelligence mode, and firewall policy for each Azure Firewall.",
    metric: { name: "Throughput", aggregation: "Average", unit: "b/s", label: "Throughput" },
    columns: [["name", "Name"], ["status", "Status"], ["sku", "SKU"], ["threat", "Threat intel"], ["waf", "Policy"], ["location", "Region"]],
    essentials: [["status", "Status"], ["sku", "SKU"], ["tier", "Tier"], ["threat", "Threat intelligence"], ["waf", "Policy"], ["location", "Region"], ["group", "Resource group"]],
    availability: [["status", "Status"], ["sku", "SKU"], ["threat", "Threat intelligence"], ["waf", "Policy"]],
  },
};

export const LIVE_METRICS = {
  "virtual-networks": [],
  "application-gateways": [
    { name: "TotalRequests", aggregation: "Total", unit: "", label: "Requests" },
    { name: "Throughput", aggregation: "Average", unit: "B/s", label: "Throughput" },
    { name: "HealthyHostCount", aggregation: "Average", unit: "", label: "Healthy hosts" },
    { name: "UnhealthyHostCount", aggregation: "Average", unit: "", label: "Unhealthy hosts" },
    { name: "FailedRequests", aggregation: "Total", unit: "", label: "Failed requests" },
    { name: "CurrentConnections", aggregation: "Average", unit: "", label: "Connections" },
  ],
  "load-balancers": [
    { name: "ByteCount", aggregation: "Total", unit: "B", label: "Bytes" },
    { name: "PacketCount", aggregation: "Total", unit: "", label: "Packets" },
    { name: "SnatConnectionCount", aggregation: "Total", unit: "", label: "SNAT connections" },
    { name: "VipAvailability", aggregation: "Average", unit: "", label: "VIP availability" },
    { name: "DipAvailability", aggregation: "Average", unit: "", label: "DIP availability" },
  ],
  "front-door": [
    { name: "RequestCount", aggregation: "Total", unit: "", label: "Requests" },
    { name: "TotalLatency", aggregation: "Average", unit: "ms", label: "Latency" },
    { name: "Percentage4XX", aggregation: "Average", unit: "%", label: "4XX" },
    { name: "Percentage5XX", aggregation: "Average", unit: "%", label: "5XX" },
    { name: "OriginHealthPercentage", aggregation: "Average", unit: "%", label: "Origin health" },
  ],
  firewalls: [
    { name: "Throughput", aggregation: "Average", unit: "b/s", label: "Throughput" },
    { name: "DataProcessed", aggregation: "Total", unit: "B", label: "Data processed" },
    { name: "FirewallHealth", aggregation: "Average", unit: "%", label: "Health" },
    { name: "ApplicationRuleHit", aggregation: "Total", unit: "", label: "Application rules" },
    { name: "NetworkRuleHit", aggregation: "Total", unit: "", label: "Network rules" },
  ],
};

const KQL_SHAPES = {
  "virtual-networks": {
    where: "| where type =~ 'microsoft.network/virtualnetworks'",
    extend: "| extend provisioning = tostring(properties.provisioningState), address = iff(isnull(properties.addressSpace.addressPrefixes), '', strcat_array(properties.addressSpace.addressPrefixes, ', ')), subnets = tostring(array_length(properties.subnets)), ddos = tostring(properties.enableDdosProtection)",
    project: "name, resourceGroup, location, provisioning, address, subnets, ddos",
    columns: [["name", "Name"], ["provisioning", "Status"], ["address", "Address space"], ["subnets", "Subnets"], ["ddos", "DDoS"], ["location", "Region"]],
    examples: [["Succeeded", "| where provisioning =~ 'Succeeded'"], ["DDoS on", "| where ddos =~ 'true'"], ["East US", "| where location == 'eastus'"]],
  },
  "application-gateways": {
    where: "| where type =~ 'microsoft.network/applicationgateways'",
    extend: "| extend status = tostring(properties.operationalState), skuName = coalesce(tostring(sku.name), tostring(properties.sku.name), ''), listeners = tostring(array_length(properties.httpListeners)), backends = tostring(array_length(properties.backendAddressPools)), policy = extract('/([^/]+)$', 1, tostring(properties.firewallPolicy.id))",
    project: "name, resourceGroup, location, status, skuName, listeners, backends, policy",
    columns: [["name", "Name"], ["status", "Status"], ["skuName", "SKU"], ["listeners", "Listeners"], ["backends", "Backends"], ["policy", "WAF"], ["location", "Region"]],
    examples: [["Running", "| where status =~ 'Running'"], ["WAF", "| where skuName contains 'WAF'"], ["East US", "| where location == 'eastus'"]],
  },
  "load-balancers": {
    where: "| where type =~ 'microsoft.network/loadbalancers'",
    extend: "| extend status = tostring(properties.provisioningState), skuName = tostring(sku.name), tier = tostring(sku.tier), rules = tostring(array_length(properties.loadBalancingRules)), probes = tostring(array_length(properties.probes)), backends = tostring(array_length(properties.backendAddressPools))",
    project: "name, resourceGroup, location, status, skuName, tier, rules, probes, backends",
    columns: [["name", "Name"], ["status", "Status"], ["skuName", "SKU"], ["tier", "Tier"], ["rules", "Rules"], ["probes", "Probes"], ["location", "Region"]],
    examples: [["Standard", "| where skuName =~ 'Standard'"], ["Succeeded", "| where status =~ 'Succeeded'"], ["East US", "| where location == 'eastus'"]],
  },
  "front-door": {
    where: "| where type =~ 'microsoft.cdn/profiles' or type =~ 'microsoft.network/frontdoors'",
    extend: "| extend status = tostring(properties.provisioningState), skuName = tostring(sku.name), kindName = tostring(kind)",
    project: "name, resourceGroup, location, status, skuName, kindName",
    columns: [["name", "Name"], ["status", "Status"], ["skuName", "SKU"], ["kindName", "Kind"], ["location", "Region"]],
    examples: [["Standard", "| where skuName contains 'Standard'"], ["Succeeded", "| where status =~ 'Succeeded'"]],
  },
  firewalls: {
    where: "| where type =~ 'microsoft.network/azurefirewalls'",
    extend: "| extend status = tostring(properties.provisioningState), skuName = tostring(sku.name), threat = tostring(properties.threatIntelMode), policy = extract('/([^/]+)$', 1, tostring(properties.firewallPolicy.id))",
    project: "name, resourceGroup, location, status, skuName, threat, policy",
    columns: [["name", "Name"], ["status", "Status"], ["skuName", "SKU"], ["threat", "Threat intel"], ["policy", "Policy"], ["location", "Region"]],
    examples: [["Succeeded", "| where status =~ 'Succeeded'"], ["Alert", "| where threat =~ 'Alert'"]],
  },
};

export const LAYOUT_LABEL = {
  "virtual-networks": "Subnets",
  "application-gateways": "Listeners",
  "load-balancers": "Rules",
  "front-door": "Endpoints",
  firewalls: "Policy",
};

export function isNetwork(id) {
  return Boolean(NETWORK_DEPTH[id]);
}

export function networkHref(id) {
  return isNetwork(id) ? `/network/${id}` : "";
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
    "virtual-networks": ["ddos", "DDoS"],
    "application-gateways": ["sku", "SKUs"],
    "load-balancers": ["sku", "SKUs"],
    "front-door": ["sku", "SKUs"],
    firewalls: ["threat", "Threat intel"],
  }[serviceId] || ["location", "Regions"];
  return facet;
}

export function presentResource(serviceId, resource) {
  const facts = resource.facts || {};
  const status = tidy(facts.operational || facts.enabledState || facts.provisioning || facts.statusText || resource.state) || "Unknown";
  return {
    ...resource,
    status,
    sku: tidy(facts.sku || resource.sku),
    tier: tidy(facts.tier),
    kind: tidy(facts.kind || resource.kind),
    address: tidy(facts.addressSpace),
    subnets: count(facts.subnetCount),
    ddos: ddosLabel(facts.ddos),
    capacity: capacityLabel(facts),
    listeners: count(facts.listenerCount),
    backends: count(facts.backendCount),
    frontends: count(facts.frontendCount),
    rules: count(facts.ruleCount),
    probes: count(facts.probeCount),
    threat: tidy(facts.threatIntel),
    waf: tidy(facts.policyName) || (tidy(facts.waf).toLowerCase() === "true" ? "Enabled" : tidy(facts.waf).toLowerCase() === "false" ? "Off" : ""),
  };
}

export function resourcesFor(model, serviceId) {
  return (model?.resources || [])
    .filter((item) => item.service === serviceId)
    .map((item) => presentResource(serviceId, item));
}

export { signalValue, serviceById };
