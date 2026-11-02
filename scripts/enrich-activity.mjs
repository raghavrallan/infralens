import { readFileSync } from "node:fs";
import { operationsFor } from "../src/lib/compute.js";

for (const line of readFileSync(new URL("../.env", import.meta.url), "utf8").split("\n")) {
  const trimmed = line.trim();
  if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) continue;
  const name = trimmed.slice(0, trimmed.indexOf("=")).trim();
  let value = trimmed.slice(trimmed.indexOf("=") + 1).trim();
  if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) value = value.slice(1, -1);
  if (!process.env[name]) process.env[name] = value;
}

const INTERESTED = /^microsoft\.(network|cdn|keyvault|apimanagement|servicebus|eventhub|logic|cognitiveservices)\//i;

function shape(rows) {
  return rows
    .map((item, index) => ({
      id: [item.eventTimestamp, item.operationName?.value || item.operationName, item.resourceId, index].filter(Boolean).join("|"),
      time: item.eventTimestamp || item.submissionTimestamp || "",
      status: item.status?.value || (typeof item.status === "string" ? item.status : "") || "",
      caller: item.caller || "",
      text: item.operationName?.localizedValue || item.operationName?.value || "Activity",
      resource: String(item.resourceId || "").split("/").pop() || "",
      resourceId: String(item.resourceId || ""),
      resourceType: typeof item.resourceType === "string" ? item.resourceType : item.resourceType?.value || "",
    }))
    .sort((a, b) => Date.parse(b.time) - Date.parse(a.time));
}

function cap(rows) {
  const seen = new Set();
  const byType = new Map();
  for (const item of rows) {
    const key = [item.time, item.text, item.resource, String(item.resourceType || "").toLowerCase()].join("|");
    if (seen.has(key)) continue;
    seen.add(key);
    const type = String(item.resourceType || "other").toLowerCase();
    const list = byType.get(type) || [];
    if (list.length < 20) list.push(item);
    byType.set(type, list);
  }
  return [...byType.values()].flat();
}

const { many, run, closeDb } = await import("../src/lib/db.js");
const { connectionSecrets, subscriptionsForProject } = await import("../src/lib/access.js");
const { openSandbox, activitySandbox } = await import("../src/lib/azure/sandbox.js");
const { withLock } = await import("../src/lib/azure/cli.js");

const projects = await many("SELECT DISTINCT org_id, project_id FROM estate_snapshots");

for (const project of projects) {
  const current = await many(
    "SELECT payload FROM estate_snapshots WHERE org_id = ? AND project_id = ? AND range_id = 'mtd'",
    [project.org_id, project.project_id],
  );
  const resources = current[0]?.payload?.resources || [];
  const subscriptions = await subscriptionsForProject(project.project_id, project.org_id);
  const byConnection = new Map();
  for (const subscription of subscriptions) {
    const list = byConnection.get(subscription.connection_id) || [];
    list.push(subscription);
    byConnection.set(subscription.connection_id, list);
  }
  const providersBySub = new Map();
  for (const resource of resources) {
    if (!INTERESTED.test(resource.type || "")) continue;
    const subscriptionId = String(resource.id || "").split("/")[2] || "";
    const provider = String(resource.type || "").split("/")[0];
    if (!/^[0-9a-f-]{36}$/i.test(subscriptionId) || !/^microsoft\.[a-z0-9]+$/i.test(provider)) continue;
    const set = providersBySub.get(subscriptionId) || new Set();
    set.add(provider);
    providersBySub.set(subscriptionId, set);
  }
  const fresh = [];
  for (const [connectionId, group] of byConnection) {
    await withLock(connectionId, async () => {
      const creds = await connectionSecrets(connectionId, project.org_id);
      try {
        const profile = await openSandbox(connectionId, creds);
        const jobs = [];
        for (const subscription of group) {
          for (const provider of providersBySub.get(subscription.id) || []) jobs.push({ subscription, provider });
        }
        const queue = [...jobs];
        async function work() {
          while (queue.length) {
            const job = queue.shift();
            try {
              fresh.push(...(await activitySandbox(profile, job.subscription.id, job.provider)));
            } catch (err) {
              console.log("skipped", String(err.message || "").replace(/\s+/g, " ").slice(0, 140));
            }
          }
        }
        await Promise.all(Array.from({ length: Math.min(2, jobs.length) }, work));
      } finally {
        creds.clientSecret = "";
      }
    });
  }
  const added = cap(shape(fresh)).filter((item) => INTERESTED.test(item.resourceType || ""));
  console.log("added", added.length);
  const snapshots = await many(
    "SELECT range_id, payload, synced_at FROM estate_snapshots WHERE org_id = ? AND project_id = ?",
    [project.org_id, project.project_id],
  );
  for (const snapshot of snapshots) {
    const payload = snapshot.payload;
    const seen = new Set();
    const merged = [];
    for (const item of [...(payload.operations || []), ...added]) {
      const key = [item.time, item.text, item.resource, String(item.resourceType || "").toLowerCase()].join("|");
      if (seen.has(key)) continue;
      seen.add(key);
      merged.push(item);
    }
    payload.operations = merged.sort((a, b) => Date.parse(b.time) - Date.parse(a.time));
    payload.activity = payload.operations.slice(0, 12);
    const counts = {};
    for (const serviceId of ["virtual-networks", "application-gateways", "load-balancers", "front-door", "firewalls", "key-vaults", "api-management", "service-bus", "event-hubs", "logic-apps", "cognitive"]) {
      const rows = (payload.resources || []).filter((item) => item.service === serviceId);
      counts[serviceId] = operationsFor(payload, serviceId, rows).length;
    }
    await run(
      "UPDATE estate_snapshots SET payload = ?::jsonb WHERE org_id = ? AND project_id = ? AND range_id = ?",
      [JSON.stringify(payload), project.org_id, project.project_id, snapshot.range_id],
    );
    const kept = await many(
      "SELECT synced_at FROM estate_snapshots WHERE org_id = ? AND project_id = ? AND range_id = ?",
      [project.org_id, project.project_id, snapshot.range_id],
    );
    console.log(snapshot.range_id, String(kept[0]?.synced_at) === String(snapshot.synced_at) ? "synced_at unchanged" : "synced_at changed", JSON.stringify(counts));
  }
}

await closeDb();
