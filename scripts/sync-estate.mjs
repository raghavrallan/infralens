import { readFileSync } from "node:fs";
import { releaseSync, writeSnapshot, readSnapshot } from "../src/lib/estate-store.js";

for (const line of readFileSync(new URL("../.env", import.meta.url), "utf8").split("\n")) {
  const trimmed = line.trim();
  if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) continue;
  const name = trimmed.slice(0, trimmed.indexOf("=")).trim();
  let value = trimmed.slice(trimmed.indexOf("=") + 1).trim();
  if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) value = value.slice(1, -1);
  if (!process.env[name]) process.env[name] = value;
}

const [orgId, projectId, rangeId] = process.argv.slice(2);
const safeId = /^[A-Za-z0-9-]{8,64}$/;
const safeRange = /^(7d|30d|mtd|qtr)$/;

function keepComputeOperations(previous, next) {
  const computeCount = (rows) => (rows || []).filter((item) => /microsoft\.(compute|web|app|containerservice|sql|dbformysql|dbforpostgresql|documentdb|cache|storage|datafactory|databricks|network|cdn|keyvault|apimanagement|servicebus|eventhub|logic|cognitiveservices)\//i.test(item.resourceType || "")).length;
  if (computeCount(next.operations) > 0 || computeCount(previous?.operations) === 0) return next;
  return { ...next, operations: previous.operations };
}

function keepPreviousSignals(previous, next) {
  const prior = new Map((previous?.resources || []).filter((item) => item.signal).map((item) => [item.id, item.signal]));
  if (!prior.size) return next;
  return {
    ...next,
    resources: (next.resources || []).map((item) => (item.signal ? item : { ...item, signal: prior.get(item.id) || null })),
  };
}

function keepPreviousCosts(previous, next) {
  const pacing = (next.warnings || []).some((item) => /pacing some cost details/i.test(item));
  const previousSpend = Number(previous?.kpis?.spend || 0);
  const nextSpend = Number(next?.kpis?.spend || 0);
  if (!previous || !pacing || previousSpend <= nextSpend) return next;
  return {
    ...next,
    kpis: { ...next.kpis, spend: previous.kpis.spend, forecast: previous.kpis.forecast, currency: previous.kpis.currency || next.kpis.currency },
    trend: previous.trend,
    services: previous.services,
    groups: previous.groups,
    databricks: previous.databricks,
    warnings: ["Azure is pacing some cost details. The last complete billing snapshot stays on screen."],
    message: "Azure is pacing some cost details. The last complete billing snapshot stays on screen.",
  };
}

try {
  if (!safeId.test(orgId || "") || !safeId.test(projectId || "") || !safeRange.test(rangeId || "")) {
    throw new Error("Invalid sync target.");
  }
  const { one } = await import("../src/lib/db.js");
  const project = await one("SELECT id, name, budget_usd::float8 AS budget_usd FROM projects WHERE id = ? AND org_id = ?", [projectId, orgId]);
  if (!project) throw new Error("Project not found.");
  const { loadEstate } = await import("../src/lib/azure/estate.js");
  const previous = await readSnapshot(orgId, projectId, rangeId);
  const model = keepComputeOperations(previous, keepPreviousSignals(previous, keepPreviousCosts(previous, await loadEstate({
    orgId,
    project,
    rangeId,
    canSeeCost: true,
    fresh: true,
    wait: true,
  }))));
  if (!(model.status === "error" && previous?.status === "ready")) {
    await writeSnapshot(orgId, projectId, rangeId, model);
    try {
      const { refreshStoredReads } = await import("../src/lib/refresh-reads.js");
      await refreshStoredReads(orgId, projectId);
    } catch {
      // The estate copy is already saved. A later visit refreshes any read Redis missed.
    }
    if (rangeId === "mtd") {
      try {
        const { syncProjectInvoices } = await import("../src/lib/invoice-sync.js");
        await syncProjectInvoices({ orgId, projectId });
      } catch {
        // A missed invoice download waits for the next month sync. Cost data is already saved.
      }
    }
  }
} finally {
  if (safeId.test(orgId || "") && safeId.test(projectId || "") && safeRange.test(rangeId || "")) {
    await releaseSync(orgId, projectId, rangeId);
  }
  const { closeDb } = await import("../src/lib/db.js");
  await closeDb();
}
