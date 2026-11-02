import { readFileSync } from "node:fs";
import { factsFromRow, COMPUTE_DEPTH, latestMetricPoint } from "../src/lib/compute.js";
import { serviceFor } from "../src/lib/services.js";

for (const line of readFileSync(new URL("../.env", import.meta.url), "utf8").split("\n")) {
  const trimmed = line.trim();
  if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) continue;
  const name = trimmed.slice(0, trimmed.indexOf("=")).trim();
  let value = trimmed.slice(trimmed.indexOf("=") + 1).trim();
  if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) value = value.slice(1, -1);
  if (!process.env[name]) process.env[name] = value;
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
      text: item.operationName?.localizedValue || item.operationName?.value || "Activity",
      resource: String(item.resourceId || "").split("/").pop() || "",
      resourceType: typeof item.resourceType === "string" ? item.resourceType : item.resourceType?.value || "",
    }))
    .sort((a, b) => Date.parse(b.time) - Date.parse(a.time))
    .slice(0, 60);
}

async function pool(items, limit, work) {
  const queue = [...items];
  const results = [];
  async function run() {
    while (queue.length) {
      const item = queue.shift();
      results.push(await work(item));
    }
  }
  await Promise.all(Array.from({ length: limit }, run));
  return results;
}

const { many, run, closeDb } = await import("../src/lib/db.js");
const { connectionSecrets, subscriptionsForProject } = await import("../src/lib/access.js");
const { openSandbox, readSandbox, activitySandbox, metricSandbox } = await import("../src/lib/azure/sandbox.js");
const { withLock } = await import("../src/lib/azure/cli.js");

const projects = await many(
  `SELECT DISTINCT org_id, project_id FROM estate_snapshots`,
);

let stopped = false;
for (const project of projects) {
  const subscriptions = await subscriptionsForProject(project.project_id, project.org_id);
  const byConnection = new Map();
  for (const subscription of subscriptions) {
    const list = byConnection.get(subscription.connection_id) || [];
    list.push(subscription);
    byConnection.set(subscription.connection_id, list);
  }
  const facts = new Map();
  const signals = new Map();
  const operations = [];
  for (const [connectionId, group] of byConnection) {
    await withLock(connectionId, async () => {
      const creds = await connectionSecrets(connectionId, project.org_id);
      try {
        const profile = await openSandbox(connectionId, creds);
        const inventory = await readSandbox(profile, group);
        for (const row of inventory.resources || []) {
          const service = serviceFor({ type: row.type, kind: row.kindText });
          if (!service || !COMPUTE_DEPTH[service.id]) continue;
          facts.set(String(row.id).toLowerCase(), factsFromRow(row));
        }
        for (const subscription of group) {
          try {
            operations.push(...(await activitySandbox(profile, subscription.id)));
          } catch (err) {
            console.log("activity skipped", err.message.slice(0, 140));
          }
        }
        const targets = (inventory.resources || []).flatMap((row) => {
          const service = serviceFor({ type: row.type, kind: row.kindText });
          const spec = service && COMPUTE_DEPTH[service.id];
          if (!spec) return [];
          return [{ id: row.id, spec }];
        });
        await pool(targets, 2, async (target) => {
          if (stopped) return;
          try {
            const payload = await metricSandbox(profile, target.id, target.spec.metric.name, target.spec.metric.aggregation);
            const value = latestMetricPoint(payload, target.spec.metric.aggregation);
            if (value === null) return;
            signals.set(String(target.id).toLowerCase(), {
              label: target.spec.metric.label,
              metric: target.spec.metric.name,
              unit: target.spec.metric.unit,
              value,
            });
          } catch (err) {
            if (/too many requests|429|503/i.test(err.message)) stopped = true;
            else console.log("metric skipped", err.message.slice(0, 140));
          }
        });
      } finally {
        creds.clientSecret = "";
      }
    });
  }
  const shaped = shapeActivity(operations);
  const snapshots = await many(
    "SELECT range_id, payload FROM estate_snapshots WHERE org_id = ? AND project_id = ?",
    [project.org_id, project.project_id],
  );
  for (const snapshot of snapshots) {
    const payload = snapshot.payload;
    let matched = 0;
    for (const resource of payload.resources || []) {
      const detail = facts.get(String(resource.id || "").toLowerCase());
      if (!detail) continue;
      matched += 1;
      resource.facts = detail;
      if (detail.size) resource.size = detail.size;
      if (detail.power || detail.state || detail.provisioning) resource.state = detail.power || detail.state || detail.provisioning;
      const signal = signals.get(String(resource.id || "").toLowerCase());
      if (signal) resource.signal = signal;
    }
    payload.operations = shaped;
    await run(
      "UPDATE estate_snapshots SET payload = ?::jsonb WHERE org_id = ? AND project_id = ? AND range_id = ?",
      [JSON.stringify(payload), project.org_id, project.project_id, snapshot.range_id],
    );
    console.log(snapshot.range_id, "resources", matched, "signals", signals.size, "operations", shaped.length);
  }
}

await closeDb();
