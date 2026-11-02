import { AsyncLocalStorage } from "node:async_hooks";
import path from "path";
import { many, run } from "../db.js";
import { id } from "../ids.js";

const callers = new AsyncLocalStorage();
let tableReady;

export function bindAzCaller(caller) {
  const current = callers.getStore() || {};
  callers.enterWith({ ...current, ...caller });
}

async function ensureTable() {
  if (!tableReady) {
    tableReady = (async () => {
      await run(
        `CREATE TABLE IF NOT EXISTS sandbox_calls (
          id VARCHAR(36) PRIMARY KEY,
          org_id VARCHAR(36),
          project_id VARCHAR(36),
          user_id VARCHAR(36),
          connection_id VARCHAR(36) NOT NULL,
          command VARCHAR(32) NOT NULL,
          method VARCHAR(8) NOT NULL DEFAULT '',
          route TEXT NOT NULL,
          caller VARCHAR(120) NOT NULL DEFAULT '',
          status VARCHAR(16) NOT NULL,
          duration_ms INTEGER NOT NULL,
          detail TEXT NOT NULL DEFAULT '',
          created_at BIGINT NOT NULL
        )`,
      );
      await run("CREATE INDEX IF NOT EXISTS sandbox_calls_connection_idx ON sandbox_calls (connection_id, created_at DESC)");
    })().catch((err) => {
      tableReady = null;
      throw err;
    });
  }
  return tableReady;
}

export async function recordAzCall({ profile, command, method, route, status, durationMs, detail }) {
  const connectionId = path.basename(profile || "");
  if (!/^[a-f0-9]{32}$/.test(connectionId)) return;
  const caller = callers.getStore() || {};
  await ensureTable();
  await run(
    `INSERT INTO sandbox_calls
     (id, org_id, project_id, user_id, connection_id, command, method, route, caller, status, duration_ms, detail, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    [
      id(),
      caller.orgId || null,
      caller.projectId || null,
      caller.userId || null,
      connectionId,
      String(command || "az").slice(0, 32),
      String(method || "").slice(0, 8),
      String(route || "").slice(0, 500),
      String(caller.caller || "az").slice(0, 120),
      status === "ok" ? "ok" : "fail",
      Math.max(0, Math.round(Number(durationMs) || 0)),
      String(detail || "").slice(0, 180),
      Date.now(),
    ],
  );
  if (Math.random() < 0.05) {
    await run("DELETE FROM sandbox_calls WHERE created_at < ?", [Date.now() - 7 * 24 * 60 * 60 * 1000]);
  }
}

export async function sandboxCalls(orgId, projectId) {
  await ensureTable();
  const rows = await many(
    `SELECT c.created_at, c.command, c.method, c.route, c.caller, c.status, c.duration_ms, c.detail, a.name AS connection
     FROM sandbox_calls c
     JOIN azure_connections a ON a.id = c.connection_id
     JOIN project_connections pc ON pc.connection_id = c.connection_id
     WHERE pc.project_id = ? AND a.org_id = ?
     ORDER BY c.created_at DESC
     LIMIT 200`,
    [projectId, orgId],
  );
  return rows.map((row) => ({
    at: Number(row.created_at),
    command: row.command,
    method: row.method,
    route: row.route,
    caller: row.caller,
    status: row.status,
    durationMs: Number(row.duration_ms),
    detail: row.detail || "",
    connection: row.connection,
  }));
}
