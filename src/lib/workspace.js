import { subscriptionsForProject, visibleProjects } from "./access.js";
import { many, run } from "./db.js";
import { ensureOrgColumns, purgeExpiredProjects, rolePermissions } from "./org-lifecycle.js";
import { isOrgManager, permissionsFor } from "./rbac.js";

export async function workspacePayload(actor) {
  await ensureOrgColumns();
  if (isOrgManager(actor.membership.role)) await purgeExpiredProjects(actor.org.id);
  const projects = await Promise.all(
    (await visibleProjects(actor, { includeInactive: isOrgManager(actor.membership.role) })).map(async (project) => ({
      id: project.id,
      name: project.name,
      budget: project.budget_usd ?? null,
      role: project.role,
      permissions: (await rolePermissions(actor.org.id, project.role)) || permissionsFor(project.role),
      status: project.status || "active",
      deactivatedAt: project.deactivated_at || null,
      purgeAt: project.purge_at || null,
      connectionIds: (
        await many(
          `SELECT pc.connection_id AS id
           FROM project_connections pc
           JOIN projects p ON p.id = pc.project_id
           WHERE pc.project_id = ? AND p.org_id = ?`,
          [project.id, actor.org.id],
        )
      ).map((item) => item.id),
      subscriptionIds: (await subscriptionsForProject(project.id, actor.org.id)).map((item) => item.id),
    })),
  );
  const orgs = await many(
    `SELECT o.id, o.name, m.org_role AS role
     FROM org_memberships m
     JOIN organizations o ON o.id = m.org_id
     WHERE m.user_id = ?
     ORDER BY o.name`,
    [actor.user.id],
  );
  const payload = {
    user: actor.user,
    org: actor.org,
    orgs,
    orgRole: actor.membership.role,
    canManage: isOrgManager(actor.membership.role),
    projects: projects.filter((project) => project.status !== "inactive"),
    archivedProjects: projects.filter((project) => project.status === "inactive"),
  };
  if (!payload.canManage) return payload;

  const members = await many(
    `SELECT u.id, u.display_name AS name, u.email, m.org_role AS role, COALESCE(m.status, 'active') AS status
     FROM org_memberships m
     JOIN users u ON u.id = m.user_id
     WHERE m.org_id = ?
     ORDER BY u.display_name`,
    [actor.org.id],
  );
  payload.members = await Promise.all(
    members.map(async (member) => ({
      ...member,
      projects: await many(
        `SELECT p.id, p.name, pm.project_role AS role
         FROM project_memberships pm
         JOIN projects p ON p.id = pm.project_id
         WHERE pm.user_id = ? AND p.org_id = ?`,
        [member.id, actor.org.id],
      ),
    })),
  );
  payload.roles = await many(
    "SELECT id, name, permissions, COALESCE(rank, 10) AS rank FROM org_roles WHERE org_id = ? ORDER BY rank, name",
    [actor.org.id],
  );
  await run(
    "UPDATE invites SET status = 'expired' WHERE org_id = ? AND status = 'pending' AND expires_at < now()",
    [actor.org.id],
  );
  payload.invites = await many(
    `SELECT i.id, i.email, i.invitee_name AS name, i.org_role AS "orgRole", i.project_role AS "projectRole",
            i.project_id AS "projectId", p.name AS "projectName", i.expires_at AS "expiresAt"
     FROM invites i
     LEFT JOIN projects p ON p.id = i.project_id
     WHERE i.org_id = ? AND i.status = 'pending'
     ORDER BY i.created_at DESC`,
    [actor.org.id],
  );
  payload.connections = (
    await many(
      `SELECT id, name, status, status_detail AS "statusDetail", last_checked_at AS "lastCheckedAt",
              right(client_id, 4) AS "clientHint"
       FROM azure_connections WHERE org_id = ? ORDER BY name`,
      [actor.org.id],
    )
  ).map((item) => ({ ...item, secretStored: true }));
  const connectionOwners = await many(
    `SELECT pc.connection_id AS id, pc.project_id AS "projectId", p.name AS "projectName"
     FROM project_connections pc
     JOIN projects p ON p.id = pc.project_id
     WHERE p.org_id = ?`,
    [actor.org.id],
  );
  const ownerByConnection = new Map(connectionOwners.map((item) => [item.id, item]));
  payload.connections = payload.connections.map((item) => ({
    ...item,
    projectId: ownerByConnection.get(item.id)?.projectId || null,
    projectName: ownerByConnection.get(item.id)?.projectName || "",
  }));
  payload.subscriptions = await many(
    `SELECT s.id, s.name, s.state, s.connection_id AS "connectionId", ps.project_id AS "projectId"
     FROM subscriptions s
     LEFT JOIN project_subscriptions ps ON ps.subscription_id = s.id
     WHERE s.org_id = ?
     ORDER BY s.name`,
    [actor.org.id],
  );
  return payload;
}
