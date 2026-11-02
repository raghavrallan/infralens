import { decrypt } from "./crypto.js";
import { many, one, run } from "./db.js";
import { id, isGuid } from "./ids.js";
import { ensureOrgColumns, rolePermissions } from "./org-lifecycle.js";
import { can, isOrgManager, PROJECT_ROLES } from "./rbac.js";
import { readSession } from "./session.js";

export class HttpError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function numberOrNull(value) {
  if (value == null || value === "") return null;
  const next = Number(value);
  return Number.isFinite(next) ? next : null;
}

export async function audit({ orgId, projectId, userId, action, detail }) {
  await run(
    "INSERT INTO audit_log (id, org_id, project_id, user_id, action, detail, created_at) VALUES (?, ?, ?, ?, ?, ?, now())",
    [id(), orgId || null, projectId || null, userId || null, action, detail || null],
  );
}

export async function actorFromToken(token) {
  const session = await readSession(token);
  if (!session) return null;
  const user = await one("SELECT id, email, display_name AS name FROM users WHERE id = ?", [session.user_id]);
  if (!user) return null;
  const org = session.org_id ? await one("SELECT id, name, slug FROM organizations WHERE id = ?", [session.org_id]) : null;
  await ensureOrgColumns();
  const membership = session.org_id
    ? await one("SELECT org_role AS role, COALESCE(status, 'active') AS status FROM org_memberships WHERE org_id = ? AND user_id = ?", [session.org_id, user.id])
    : null;
  if (membership?.status === "suspended") throw new HttpError(403, "Your access to this organization is suspended.");
  return { user, session, org: membership ? org : null, membership: membership || null };
}

export async function requireActor(token) {
  const actor = await actorFromToken(token);
  if (!actor?.user || !actor.org || !actor.membership) throw new HttpError(401, "Sign in again.");
  return actor;
}

export async function projectRole(userId, projectId) {
  const row = await one("SELECT project_role AS role FROM project_memberships WHERE project_id = ? AND user_id = ?", [projectId, userId]);
  return row?.role || null;
}

export async function holds(actor, permission, projectId) {
  const role = projectId ? await projectRole(actor.user.id, projectId) : null;
  const custom = role && !PROJECT_ROLES.includes(role) ? await rolePermissions(actor.org.id, role) : null;
  return can(actor.membership.role, role, permission, custom);
}

export async function assertCan(actor, permission, projectId) {
  const role = projectId ? await projectRole(actor.user.id, projectId) : null;
  if (!(await holds(actor, permission, projectId))) throw new HttpError(403, "Your role does not allow that.");
  return role;
}

export async function visibleProjects(actor, options = {}) {
  await ensureOrgColumns();
  const activeOnly = options.includeInactive ? "" : "AND COALESCE(status, 'active') = 'active'";
  if (isOrgManager(actor.membership.role)) {
    const rows = await many(
      `SELECT id, org_id, name, slug, budget_usd::float8 AS budget_usd, created_at,
              COALESCE(status, 'active') AS status, deactivated_at, purge_at
       FROM projects WHERE org_id = ? ${activeOnly} ORDER BY name`,
      [actor.org.id],
    );
    return rows.map((project) => ({ ...project, budget_usd: numberOrNull(project.budget_usd), role: actor.membership.role }));
  }
  const memberActive = options.includeInactive ? "" : "AND COALESCE(p.status, 'active') = 'active'";
  const rows = await many(
    `SELECT p.id, p.org_id, p.name, p.slug, p.budget_usd::float8 AS budget_usd, p.created_at, pm.project_role AS role,
            COALESCE(p.status, 'active') AS status, p.deactivated_at, p.purge_at
     FROM projects p
     JOIN project_memberships pm ON pm.project_id = p.id
     WHERE p.org_id = ? AND pm.user_id = ? ${memberActive}
     ORDER BY p.name`,
    [actor.org.id, actor.user.id],
  );
  return rows.map((project) => ({ ...project, budget_usd: numberOrNull(project.budget_usd) }));
}

export async function requireProject(actor, projectId, permission) {
  const project = await one("SELECT id, org_id, name, slug, budget_usd::float8 AS budget_usd FROM projects WHERE id = ?", [projectId]);
  if (!project || project.org_id !== actor.org.id) throw new HttpError(404, "Project not found.");
  project.budget_usd = numberOrNull(project.budget_usd);
  await assertCan(actor, permission, project.id);
  return project;
}

export async function subscriptionsForProject(projectId, orgId) {
  const rows = await many(
    `SELECT DISTINCT s.id, s.name, s.state, s.connection_id
     FROM subscriptions s
     WHERE s.org_id = ?
       AND EXISTS (SELECT 1 FROM projects p WHERE p.id = ? AND p.org_id = s.org_id)
       AND (
         s.connection_id IN (SELECT connection_id FROM project_connections WHERE project_id = ?)
         OR s.id IN (SELECT subscription_id FROM project_subscriptions WHERE project_id = ?)
       )`,
    [orgId, projectId, projectId, projectId],
  );
  return rows.filter((row) => isGuid(row.id));
}

export async function bindConnections(orgId, projectId, ids) {
  const unique = [...new Set((ids || []).map((item) => String(item).trim()).filter(Boolean))];
  const project = await one("SELECT id FROM projects WHERE id = ? AND org_id = ?", [projectId, orgId]);
  if (!project) throw new HttpError(404, "Project not found.");
  for (const connectionId of unique) {
    const row = await one("SELECT id FROM azure_connections WHERE id = ? AND org_id = ?", [connectionId, orgId]);
    if (!row) throw new HttpError(400, "That connection is not on this organization.");
    const taken = await one(
      `SELECT p.name
       FROM project_connections pc
       JOIN projects p ON p.id = pc.project_id
       WHERE pc.connection_id = ? AND pc.project_id <> ? AND p.org_id = ?`,
      [connectionId, projectId, orgId],
    );
    if (taken) throw new HttpError(409, `Remove that connection from ${taken.name} first. Each project keeps its own connection.`);
  }
  await run("DELETE FROM project_connections WHERE project_id = ?", [projectId]);
  for (const connectionId of unique) {
    await run("INSERT INTO project_connections (project_id, connection_id) VALUES (?, ?)", [projectId, connectionId]);
  }
}

export async function connectionSecrets(connectionId, orgId) {
  const row = await one("SELECT * FROM azure_connections WHERE id = ? AND org_id = ?", [connectionId, orgId]);
  if (!row) throw new HttpError(404, "Azure connection not found.");
  return {
    id: row.id,
    tenantId: row.tenant_id,
    clientId: row.client_id,
    clientSecret: decrypt(row.secret_cipher),
  };
}

export async function replaceSubscriptions(orgId, connectionId, rows) {
  const seen = new Set();
  for (const row of rows) {
    if (!isGuid(row.id)) continue;
    const owner = await one("SELECT org_id FROM subscriptions WHERE id = ?", [row.id]);
    if (owner && owner.org_id !== orgId) {
      throw new HttpError(409, "That subscription is already connected to another organization.");
    }
    seen.add(row.id);
    await run(
      `INSERT INTO subscriptions (id, org_id, connection_id, name, state)
       VALUES (?, ?, ?, ?, ?)
       ON CONFLICT (id) DO UPDATE SET
         name = EXCLUDED.name,
         state = EXCLUDED.state,
         connection_id = EXCLUDED.connection_id,
         org_id = EXCLUDED.org_id`,
      [row.id, orgId, connectionId, row.name || row.id, row.state || ""],
    );
  }
  const existing = await many("SELECT id FROM subscriptions WHERE connection_id = ? AND org_id = ?", [connectionId, orgId]);
  for (const row of existing) {
    if (seen.has(row.id)) continue;
    await run("DELETE FROM project_subscriptions WHERE subscription_id = ?", [row.id]);
    await run("DELETE FROM subscriptions WHERE id = ? AND org_id = ?", [row.id, orgId]);
  }
}

export async function bindSubscriptions(orgId, projectId, ids) {
  const unique = [...new Set((ids || []).map((item) => String(item).trim()))];
  for (const subId of unique) {
    if (!isGuid(subId)) throw new HttpError(400, "Choose a real subscription.");
    const sub = await one("SELECT org_id FROM subscriptions WHERE id = ?", [subId]);
    if (!sub || sub.org_id !== orgId) throw new HttpError(400, "That subscription is not on this organization.");
    const taken = await one("SELECT project_id FROM project_subscriptions WHERE subscription_id = ?", [subId]);
    if (taken && taken.project_id !== projectId) {
      throw new HttpError(409, "That subscription is already attached to another project.");
    }
  }
  await run("DELETE FROM project_subscriptions WHERE project_id = ?", [projectId]);
  for (const subId of unique) {
    await run("INSERT INTO project_subscriptions (project_id, subscription_id) VALUES (?, ?)", [projectId, subId]);
  }
}
