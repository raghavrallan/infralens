export const SERVICE_GROUPS = [
  { id: "compute", label: "Compute" },
  { id: "data", label: "Data" },
  { id: "network", label: "Network" },
  { id: "platform", label: "Platform" },
];

export const SERVICES = [
  { id: "virtual-machines", label: "Virtual machines", group: "compute", types: ["microsoft.compute/virtualmachines"] },
  { id: "vm-scale-sets", label: "VM scale sets", group: "compute", types: ["microsoft.compute/virtualmachinescalesets"] },
  { id: "app-service", label: "App Service", group: "compute", types: ["microsoft.web/sites"], when: (kind) => !/function/i.test(kind) },
  { id: "functions", label: "Functions", group: "compute", types: ["microsoft.web/sites"], when: (kind) => /function/i.test(kind) },
  { id: "container-apps", label: "Container Apps", group: "compute", types: ["microsoft.app/containerapps"] },
  { id: "kubernetes", label: "Kubernetes", group: "compute", types: ["microsoft.containerservice/managedclusters"] },
  { id: "sql", label: "Azure SQL", group: "data", types: ["microsoft.sql/servers", "microsoft.sql/servers/databases", "microsoft.sql/servers/elasticpools"] },
  { id: "mysql", label: "MySQL", group: "data", types: ["microsoft.dbformysql/flexibleservers", "microsoft.dbformysql/servers"] },
  { id: "postgresql", label: "PostgreSQL", group: "data", types: ["microsoft.dbforpostgresql/flexibleservers", "microsoft.dbforpostgresql/servers"] },
  { id: "cosmos", label: "Cosmos DB", group: "data", types: ["microsoft.documentdb/databaseaccounts"] },
  { id: "redis", label: "Redis", group: "data", types: ["microsoft.cache/redis"] },
  { id: "storage", label: "Storage", group: "data", types: ["microsoft.storage/storageaccounts"] },
  { id: "data-factory", label: "Data Factory", group: "data", types: ["microsoft.datafactory/factories"] },
  { id: "databricks", label: "Databricks", group: "data", types: ["microsoft.databricks/workspaces"] },
  { id: "virtual-networks", label: "Virtual networks", group: "network", types: ["microsoft.network/virtualnetworks"] },
  { id: "application-gateways", label: "Application Gateway", group: "network", types: ["microsoft.network/applicationgateways"] },
  { id: "load-balancers", label: "Load balancers", group: "network", types: ["microsoft.network/loadbalancers"] },
  { id: "front-door", label: "Front Door", group: "network", types: ["microsoft.cdn/profiles", "microsoft.network/frontdoors"] },
  { id: "firewalls", label: "Firewall", group: "network", types: ["microsoft.network/azurefirewalls"] },
  { id: "key-vaults", label: "Key Vault", group: "platform", types: ["microsoft.keyvault/vaults"] },
  { id: "api-management", label: "API Management", group: "platform", types: ["microsoft.apimanagement/service"] },
  { id: "service-bus", label: "Service Bus", group: "platform", types: ["microsoft.servicebus/namespaces"] },
  { id: "event-hubs", label: "Event Hubs", group: "platform", types: ["microsoft.eventhub/namespaces"] },
  { id: "logic-apps", label: "Logic Apps", group: "platform", types: ["microsoft.logic/workflows"] },
  { id: "cognitive", label: "Cognitive Services", group: "platform", types: ["microsoft.cognitiveservices/accounts"] },
];

const LEGACY_KINDS = {
  vm: ["virtual-machines", "vm-scale-sets"],
  database: ["sql", "mysql", "postgresql", "cosmos", "redis"],
  storage: ["storage"],
  cdn: ["front-door"],
  serverless: ["functions", "logic-apps"],
};

export function inventoryFilter() {
  const types = [...new Set(SERVICES.flatMap((service) => service.types))];
  return `type in~ (${types.map((type) => `'${type}'`).join(", ")})`;
}

export function serviceFor(resource) {
  const type = String(resource?.type || "").toLowerCase();
  const kind = String(resource?.kind || resource?.kindText || "");
  return SERVICES.find((service) => service.types.includes(type) && (!service.when || service.when(kind, resource))) || null;
}

export function serviceById(id) {
  return SERVICES.find((service) => service.id === id) || null;
}

export function servicesForKind(kind) {
  return LEGACY_KINDS[kind] || null;
}
