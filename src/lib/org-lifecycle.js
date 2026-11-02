import { rm } from "node:fs/promises";
import { invoiceFolder } from "./invoice-store.js";
import { one, run, many } from "./db.js";
import { id } from "./ids.js";
import { MODULES, PROJECT_RANKS, PROJECT_ROLES, rankOf } from "./rbac.js";

export const RETENTION_DAYS = 60;

const ALLOWED = new Set(MODULES.map(([key]) => key));

const PROJECT_TABLES = [
  "estate_syncs",
  "estate_schedules",
  "estate_snapshots",
  "sandbox_calls",
  "project_subscriptions",
  "project_connections",
  "project_memberships",
  "connections",
  "findings",
  "finding_identities",
  "workflow_runs",
  "workflows",
  "approvals",
  "engineering_memory",
  "architecture_runs",
  "project_requirements",
  "project_artifacts",
  "delivery_tasks",
  "project_risks",
  "project_activities",
  "execution_jobs",
  "delivery_runs",
];

let ready;

export function ensureOrgColumns() {
  ready ||= run(`
    ALTER TABLE projects ADD COLUMN IF NOT EXISTS status VARCHAR(16) NOT NULL DEFAULT 'active';
    ALTER TABLE projects ADD COLUMN IF NOT EXISTS deactivated_at TIMESTAMPTZ;
    ALTER TABLE projects ADD COLUMN IF NOT EXISTS purge_at TIMESTAMPTZ;
    ALTER TABLE org_memberships ADD COLUMN IF NOT EXISTS status VARCHAR(16) NOT NULL DEFAULT 'active';
    CREATE TABLE IF NOT EXISTS org_roles (
      id VARCHAR(36) PRIMARY KEY,
      org_id VARCHAR(36) NOT NULL,
      name VARCHAR(80) NOT NULL,
      permissions JSONB NOT NULL DEFAULT '[]'::jsonb,
      rank INTEGER NOT NULL DEFAULT 10,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    ALTER TABLE org_roles ADD COLUMN IF NOT EXISTS rank INTEGER NOT NULL DEFAULT 10;
    CREATE UNIQUE INDEX IF NOT EXISTS org_roles_org_name ON org_roles (org_id, lower(name));
    CREATE TABLE IF NOT EXISTS invites (
      id VARCHAR(36) PRIMARY KEY,
      org_id VARCHAR(36) NOT NULL,
      email VARCHAR(255) NOT NULL,
      token_hash VARCHAR(64) NOT NULL UNIQUE,
      invited_role VARCHAR(64) NOT NULL DEFAULT 'developer',
      org_role VARCHAR(32) NOT NULL DEFAULT 'member',
      project_id VARCHAR(36),
      project_role VARCHAR(64) NOT NULL DEFAULT 'developer',
      status VARCHAR(16) NOT NULL DEFAULT 'pending',
      invited_by VARCHAR(36) NOT NULL DEFAULT '',
      invitee_name VARCHAR(120) NOT NULL DEFAULT '',
      expires_at TIMESTAMPTZ NOT NULL,
      accepted_at TIMESTAMPTZ,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    ALTER TABLE invites ADD COLUMN IF NOT EXISTS invitee_name VARCHAR(120) NOT NULL DEFAULT '';
    ALTER TABLE invites ALTER COLUMN project_role TYPE VARCHAR(64);
    ALTER TABLE invites ALTER COLUMN invited_role TYPE VARCHAR(64);
  `).catch((err) => {
    ready = null;
    throw err;
  });
  return ready;
}

export function cleanPermissions(values) {
  const picked = [];
  for (const value of values || []) {
    const key = String(value || "");
    if (ALLOWED.has(key) && !picked.includes(key)) picked.push(key);
  }
  return picked;
}

export async function rolePermissions(orgId, role) {
  if (!role || PROJECT_ROLES.includes(role)) return null;
  await ensureOrgColumns();
  const row = await one("SELECT permissions FROM org_roles WHERE id = ? AND org_id = ?", [role, orgId]);
  if (!row) return [];
  return Array.isArray(row.permissions) ? row.permissions : [];
}

export async function roleRank(orgId, role) {
  if (PROJECT_ROLES.includes(role) || role === "org_owner" || role === "org_admin" || role === "member") return rankOf(role);
  await ensureOrgColumns();
  const row = await one("SELECT COALESCE(rank, 10) AS rank FROM org_roles WHERE id = ? AND org_id = ?", [role, orgId]);
  return rankOf(role, [{ id: role, rank: row?.rank }]);
}

export async function assertAssignableRole(orgId, role) {
  if (PROJECT_ROLES.includes(role)) return;
  await ensureOrgColumns();
  const row = await one("SELECT id FROM org_roles WHERE id = ? AND org_id = ?", [role, orgId]);
  if (!row) {
    const error = new Error("Choose a project role.");
    error.status = 400;
    throw error;
  }
}

export async function setProjectActive(orgId, projectId, active) {
  await ensureOrgColumns();
  const project = await one(
    "SELECT id, status FROM projects WHERE id = ? AND org_id = ?",
    [projectId, orgId],
  );
  if (!project) return null;
  if (active) {
    await run(
      "UPDATE projects SET status = 'active', deactivated_at = NULL, purge_at = NULL, updated_at = now() WHERE id = ? AND org_id = ?",
      [projectId, orgId],
    );
  } else if (project.status !== "inactive") {
    await run(
      `UPDATE projects
       SET status = 'inactive', deactivated_at = now(), purge_at = now() + interval '60 days', updated_at = now()
       WHERE id = ? AND org_id = ?`,
      [projectId, orgId],
    );
  }
  return one(
    "SELECT id, name, status, deactivated_at, purge_at FROM projects WHERE id = ? AND org_id = ?",
    [projectId, orgId],
  );
}

async function dropTableRows(table, projectId) {
  if (!/^[a-z_]+$/.test(table)) return;
  try {
    await run(`DELETE FROM ${table} WHERE project_id = ?`, [projectId]);
  } catch (err) {
    if (err?.code !== "42P01" && err?.code !== "42703") throw err;
  }
}

export async function purgeExpiredProjects(orgId) {
  await ensureOrgColumns();
  const due = await many(
    "SELECT id FROM projects WHERE org_id = ? AND status = 'inactive' AND purge_at IS NOT NULL AND purge_at < now()",
    [orgId],
  );
  for (const project of due) {
    try {
      await rm(invoiceFolder(project.id), { recursive: true, force: true });
    } catch {
      // The invoice folder is absent or the id is not a folder name.
    }
    try {
      await run("DELETE FROM messages WHERE chat_id IN (SELECT id FROM chats WHERE project_id = ?)", [project.id]);
      await run("DELETE FROM chats WHERE project_id = ?", [project.id]);
    } catch (err) {
      if (err?.code !== "42P01") throw err;
    }
    for (const table of PROJECT_TABLES) await dropTableRows(table, project.id);
    await run("DELETE FROM projects WHERE id = ? AND org_id = ? AND status = 'inactive'", [project.id, orgId]);
  }
  return due.length;
}

export async function createOrgRole(orgId, name, permissions, rank) {
  await ensureOrgColumns();
  const clean = String(name || "").trim().replace(/\s+/g, " ");
  const picked = cleanPermissions(permissions);
  const level = Number(rank);
  if (clean.length < 2 || clean.length > 80) {
    const error = new Error("Name the role.");
    error.status = 400;
    throw error;
  }
  if (!picked.length) {
    const error = new Error("Choose at least one module.");
    error.status = 400;
    throw error;
  }
  if (!PROJECT_RANKS.includes(level)) {
    const error = new Error("Choose a level on the role ladder.");
    error.status = 400;
    throw error;
  }
  const roleId = id();
  await run(
    "INSERT INTO org_roles (id, org_id, name, permissions, rank, created_at) VALUES (?, ?, ?, ?::jsonb, ?, now())",
    [roleId, orgId, clean, JSON.stringify(picked), level],
  );
  return { id: roleId, name: clean, permissions: picked, rank: level };
}
