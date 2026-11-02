import { HttpError, audit } from "@/lib/access";
import { isUniqueViolation, one, run } from "@/lib/db";
import { currentActor, fail, ok } from "@/lib/http";
import { createOrgRole } from "@/lib/org-lifecycle";
import { rankOf } from "@/lib/rbac";

export const dynamic = "force-dynamic";

function manager(actor) {
  if (actor.membership.role !== "org_owner" && actor.membership.role !== "org_admin") {
    throw new HttpError(403, "Only an organization admin can change roles.");
  }
}

export async function POST(request) {
  try {
    const actor = await currentActor();
    manager(actor);
    const body = await request.json().catch(() => ({}));
    let role;
    try {
      const rank = Number(body.rank);
      if (rankOf(actor.membership.role) <= rank) throw new HttpError(403, "Choose a level below your own.");
      role = await createOrgRole(actor.org.id, body.name, body.permissions, rank);
    } catch (err) {
      if (isUniqueViolation(err)) throw new HttpError(409, "That role name is already in this organization.");
      if (err.status) throw new HttpError(err.status, err.message);
      throw err;
    }
    await audit({ orgId: actor.org.id, userId: actor.user.id, action: "role.create", detail: role.name });
    return ok(role);
  } catch (err) {
    return fail(err);
  }
}

export async function DELETE(request) {
  try {
    const actor = await currentActor();
    manager(actor);
    const roleId = String(new URL(request.url).searchParams.get("id") || "");
    if (!roleId) throw new HttpError(400, "Choose a role.");
    const assigned = await one(
      `SELECT 1 AS hit FROM project_memberships pm
       JOIN projects p ON p.id = pm.project_id
       WHERE pm.project_role = ? AND p.org_id = ?`,
      [roleId, actor.org.id],
    );
    if (assigned) throw new HttpError(400, "Remove this role from people before deleting it.");
    await run("DELETE FROM org_roles WHERE id = ? AND org_id = ?", [roleId, actor.org.id]);
    await audit({ orgId: actor.org.id, userId: actor.user.id, action: "role.delete", detail: roleId });
    return ok({ ok: true });
  } catch (err) {
    return fail(err);
  }
}
