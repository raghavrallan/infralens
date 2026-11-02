import { readFileSync } from "node:fs";
import { factsFromRow } from "../src/lib/compute.js";

for (const line of readFileSync(new URL("../.env", import.meta.url), "utf8").split("\n")) {
  const trimmed = line.trim();
  if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) continue;
  const name = trimmed.slice(0, trimmed.indexOf("=")).trim();
  let value = trimmed.slice(trimmed.indexOf("=") + 1).trim();
  if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) value = value.slice(1, -1);
  if (!process.env[name]) process.env[name] = value;
}

const QUERY = `Resources
| where type in~ ('microsoft.keyvault/vaults', 'microsoft.apimanagement/service', 'microsoft.servicebus/namespaces', 'microsoft.eventhub/namespaces', 'microsoft.logic/workflows', 'microsoft.cognitiveservices/accounts')
| extend skuName = coalesce(tostring(sku.name), tostring(properties.sku.name), '')
| extend skuTier = coalesce(tostring(sku.tier), tostring(properties.sku.tier), '')
| extend skuCapacity = tostring(sku.capacity)
| extend provisioning = tostring(properties.provisioningState)
| extend publicNet = tostring(properties.publicNetworkAccess)
| extend softDelete = tostring(properties.enableSoftDelete)
| extend purgeProtection = tostring(properties.enablePurgeProtection)
| extend rbacAuth = tostring(properties.enableRbacAuthorization)
| extend vaultUri = tostring(properties.vaultUri)
| extend dataEndpoint = coalesce(tostring(properties.endpoint), tostring(properties.vaultUri), tostring(properties.gatewayUrl), tostring(properties.serviceBusEndpoint), '')
| extend gatewayUrl = tostring(properties.gatewayUrl)
| extend vnetType = tostring(properties.virtualNetworkType)
| extend workflowState = tostring(properties.state)
| extend kindText = tostring(kind)
| extend zoneRedundant = tostring(properties.zoneRedundant)
| extend localAuth = tostring(properties.disableLocalAuth)
| extend kafka = tostring(properties.kafkaEnabled)
| extend autoInflate = tostring(properties.isAutoInflateEnabled)
| extend customDomain = tostring(properties.customSubDomainName)
| project id, skuName, skuTier, skuCapacity, provisioning, publicNet, softDelete, purgeProtection, rbacAuth, vaultUri, dataEndpoint, gatewayUrl, vnetType, workflowState, kindText, zoneRedundant, localAuth, kafka, autoInflate, customDomain`;

function mergeFacts(current, next) {
  const facts = { ...(current || {}) };
  for (const [key, value] of Object.entries(next)) {
    if (value !== "") facts[key] = value;
  }
  return facts;
}

const { many, run, closeDb } = await import("../src/lib/db.js");
const { connectionSecrets, subscriptionsForProject } = await import("../src/lib/access.js");
const { openSandbox, graphQuery } = await import("../src/lib/azure/sandbox.js");
const { withLock } = await import("../src/lib/azure/cli.js");

const projects = await many("SELECT DISTINCT org_id, project_id FROM estate_snapshots");

for (const project of projects) {
  const subscriptions = await subscriptionsForProject(project.project_id, project.org_id);
  const byConnection = new Map();
  for (const subscription of subscriptions) {
    const list = byConnection.get(subscription.connection_id) || [];
    list.push(subscription);
    byConnection.set(subscription.connection_id, list);
  }
  const facts = new Map();
  for (const [connectionId, group] of byConnection) {
    await withLock(connectionId, async () => {
      const creds = await connectionSecrets(connectionId, project.org_id);
      try {
        const profile = await openSandbox(connectionId, creds);
        const rows = await graphQuery(profile, group.map((item) => item.id), QUERY);
        for (const row of rows || []) {
          if (!row?.id) continue;
          facts.set(String(row.id).toLowerCase(), factsFromRow(row));
        }
        console.log("graph rows", (rows || []).length);
      } finally {
        creds.clientSecret = "";
      }
    });
  }
  const snapshots = await many(
    "SELECT range_id, payload, synced_at FROM estate_snapshots WHERE org_id = ? AND project_id = ?",
    [project.org_id, project.project_id],
  );
  for (const snapshot of snapshots) {
    const payload = snapshot.payload;
    let matched = 0;
    for (const resource of payload.resources || []) {
      const detail = facts.get(String(resource.id || "").toLowerCase());
      if (!detail) continue;
      matched += 1;
      resource.facts = mergeFacts(resource.facts, detail);
      if (!resource.sku && detail.sku) resource.sku = detail.sku;
    }
    await run(
      "UPDATE estate_snapshots SET payload = ?::jsonb WHERE org_id = ? AND project_id = ? AND range_id = ?",
      [JSON.stringify(payload), project.org_id, project.project_id, snapshot.range_id],
    );
    const kept = await many(
      "SELECT synced_at FROM estate_snapshots WHERE org_id = ? AND project_id = ? AND range_id = ?",
      [project.org_id, project.project_id, snapshot.range_id],
    );
    console.log(snapshot.range_id, "matched", matched, "synced_at", String(kept[0]?.synced_at) === String(snapshot.synced_at) ? "unchanged" : "changed");
  }
}

await closeDb();
