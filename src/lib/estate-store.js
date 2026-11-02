import { spawn } from "node:child_process";
import path from "node:path";
import { one, run } from "./db.js";
import { EstateError } from "./estate-messages.js";

export const CADENCES = {
  visit: { label: "Every time I open the console", ms: 0 },
  "3h": { label: "Every 3 hours", ms: 3 * 60 * 60 * 1000 },
  "12h": { label: "Every 12 hours", ms: 12 * 60 * 60 * 1000 },
  "7d": { label: "Every week", ms: 7 * 24 * 60 * 60 * 1000 },
};

const CLAIM_MS = 15 * 60 * 1000;
let tablesReady;

function ensureTables() {
  tablesReady ||= run(`
    CREATE TABLE IF NOT EXISTS estate_snapshots (
      org_id VARCHAR(36) NOT NULL,
      project_id VARCHAR(36) NOT NULL,
      range_id VARCHAR(16) NOT NULL,
      payload JSONB NOT NULL,
      synced_at BIGINT NOT NULL,
      PRIMARY KEY (org_id, project_id, range_id)
    );
    CREATE TABLE IF NOT EXISTS estate_schedules (
      org_id VARCHAR(36) NOT NULL,
      project_id VARCHAR(36) NOT NULL,
      cadence VARCHAR(16) NOT NULL,
      updated_at BIGINT NOT NULL,
      PRIMARY KEY (org_id, project_id)
    );
    CREATE TABLE IF NOT EXISTS estate_syncs (
      org_id VARCHAR(36) NOT NULL,
      project_id VARCHAR(36) NOT NULL,
      range_id VARCHAR(16) NOT NULL,
      started_at BIGINT NOT NULL,
      PRIMARY KEY (org_id, project_id, range_id)
    );
  `);
  return tablesReady;
}

export function cadenceOf(value) {
  return CADENCES[value] ? value : "12h";
}

export async function readSchedule(orgId, projectId) {
  await ensureTables();
  const row = await one("SELECT cadence FROM estate_schedules WHERE org_id = ? AND project_id = ?", [orgId, projectId]);
  return cadenceOf(row?.cadence);
}

export async function writeSchedule(orgId, projectId, cadence) {
  await ensureTables();
  const value = cadenceOf(cadence);
  await run(
    `INSERT INTO estate_schedules (org_id, project_id, cadence, updated_at) VALUES (?, ?, ?, ?)
     ON CONFLICT (org_id, project_id) DO UPDATE SET cadence = EXCLUDED.cadence, updated_at = EXCLUDED.updated_at`,
    [orgId, projectId, value, Date.now()],
  );
  return value;
}

const SNAPSHOT_PARTS = {
  status: ["status", "message", "warnings", "project", "subscriptions"],
  overview: ["status", "message", "warnings", "project", "kpis", "trend", "services", "groups", "databricks"],
  resources: ["resources", "vms", "hosting", "workspaces", "storage", "pipelines", "subscriptions", "project"],
  activity: ["activity", "operations"],
  alerts: ["alerts"],
  advisor: ["advisor"],
};

const SNAPSHOT_SCALARS = new Set(["status", "message"]);

export async function readSnapshotKeys(orgId, projectId, rangeId, part) {
  const keys = SNAPSHOT_PARTS[part];
  if (!keys) throw new EstateError("part.unknown");
  await ensureTables();
  const select = keys.map((key) => (
    SNAPSHOT_SCALARS.has(key) ? `payload->>'${key}' AS "${key}"` : `payload->'${key}' AS "${key}"`
  )).join(", ");
  const row = await one(
    `SELECT synced_at, ${select} FROM estate_snapshots WHERE org_id = ? AND project_id = ? AND range_id = ?`,
    [orgId, projectId, rangeId],
  );
  if (!row) return null;
  const payload = { syncedAt: Number(row.synced_at) || 0 };
  for (const key of keys) payload[key] = row[key];
  return payload;
}

export async function readSnapshot(orgId, projectId, rangeId) {
  await ensureTables();
  const row = await one(
    "SELECT payload, synced_at FROM estate_snapshots WHERE org_id = ? AND project_id = ? AND range_id = ?",
    [orgId, projectId, rangeId],
  );
  if (!row) return null;
  const payload = typeof row.payload === "string" ? JSON.parse(row.payload) : row.payload;
  return { ...payload, syncedAt: Number(row.synced_at) || payload.syncedAt };
}

export async function writeSnapshot(orgId, projectId, rangeId, payload) {
  await ensureTables();
  const syncedAt = Date.now();
  await run(
    `INSERT INTO estate_snapshots (org_id, project_id, range_id, payload, synced_at) VALUES (?, ?, ?, ?::jsonb, ?)
     ON CONFLICT (org_id, project_id, range_id) DO UPDATE SET payload = EXCLUDED.payload, synced_at = EXCLUDED.synced_at`,
    [orgId, projectId, rangeId, JSON.stringify({ ...payload, syncedAt }), syncedAt],
  );
}

export async function syncRunning(orgId, projectId, rangeId) {
  await ensureTables();
  const row = await one(
    "SELECT started_at FROM estate_syncs WHERE org_id = ? AND project_id = ? AND range_id = ?",
    [orgId, projectId, rangeId],
  );
  return Boolean(row && Number(row.started_at) > Date.now() - CLAIM_MS);
}

export async function claimSync(orgId, projectId, rangeId) {
  await ensureTables();
  const now = Date.now();
  const row = await one(
    `INSERT INTO estate_syncs (org_id, project_id, range_id, started_at) VALUES (?, ?, ?, ?)
     ON CONFLICT (org_id, project_id, range_id)
     DO UPDATE SET started_at = EXCLUDED.started_at
     WHERE estate_syncs.started_at < ?
     RETURNING org_id`,
    [orgId, projectId, rangeId, now, now - CLAIM_MS],
  );
  return Boolean(row);
}

export async function releaseSync(orgId, projectId, rangeId) {
  await ensureTables();
  await run("DELETE FROM estate_syncs WHERE org_id = ? AND project_id = ? AND range_id = ?", [orgId, projectId, rangeId]);
}

export function scheduleDue(cadence, syncedAt, opened) {
  if (!syncedAt || !opened) return false;
  const item = CADENCES[cadenceOf(cadence)];
  if (item.ms === 0) return opened;
  return opened && Date.now() - syncedAt >= item.ms;
}

export function enqueueSync(orgId, projectId, rangeId) {
  const root = process.cwd();
  const python = path.join(root, ".venv", "bin", "python");
  return new Promise((resolve) => {
    const child = spawn(python, ["-m", "app.estate.enqueue", orgId, projectId, rangeId], {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, "engine") },
      stdio: "ignore",
    });
    child.on("error", () => resolve(1));
    child.on("close", (code) => resolve(code ?? 1));
  });
}
