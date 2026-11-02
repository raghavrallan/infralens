import { audit, HttpError } from "@/lib/access";
import { many, one, run } from "@/lib/db";
import { currentActor, fail, ok } from "@/lib/http";
import { createMemberInvite } from "@/lib/invites";
import { roleRank } from "@/lib/org-lifecycle";
import { rankOf } from "@/lib/rbac";

export const dynamic = "force-dynamic";

async function memberPower(orgId, userId) {
  const membership = await one("SELECT org_role AS role FROM org_memberships WHERE org_id = ? AND user_id = ?", [orgId, userId]);
  const projects = await many(
    `SELECT pm.project_role AS role
     FROM project_memberships pm
     JOIN projects p ON p.id = pm.project_id
     WHERE pm.user_id = ? AND p.org_id = ?`,
    [userId, orgId],
  );
  let rank = rankOf(membership?.role);
  for (const project of projects) rank = Math.max(rank, await roleRank(orgId, project.role));
  return rank;
}

export async function POST(request) {
  try {
    const actor = await currentActor();
    if (actor.membership.role !== "org_owner" && actor.membership.role !== "org_admin") {
      throw new HttpError(403, "Only an organization admin can add members.");
    }
    const body = await request.json().catch(() => ({}));
    const invited = await createMemberInvite(request, actor, body);
    await audit({ orgId: actor.org.id, userId: actor.user.id, action: "member.invite", detail: String(body.email || "").trim().toLowerCase() });
    return ok(invited);
  } catch (err) {
    return fail(err);
  }
}

export async function PATCH(request) {
  try {
    const actor = await currentActor();
    if (actor.membership.role !== "org_owner" && actor.membership.role !== "org_admin") {
      throw new HttpError(403, "Only an organization admin can change a member.");
    }
    const body = await request.json().catch(() => ({}));
    const userId = String(body.userId || "");
    const status = String(body.status || "");
    if (!userId || userId === actor.user.id) throw new HttpError(400, "You cannot change your own status here.");
    if (status !== "active" && status !== "suspended") throw new HttpError(400, "Choose active or suspended.");
    const membership = await one("SELECT org_role AS role FROM org_memberships WHERE org_id = ? AND user_id = ?", [actor.org.id, userId]);
    if (!membership) throw new HttpError(404, "Member not found.");
    if ((await memberPower(actor.org.id, userId)) >= rankOf(actor.membership.role)) {
      throw new HttpError(403, "You can only change someone below your level.");
    }
    if (membership.role === "org_owner" && status === "suspended") throw new HttpError(400, "An organization owner stays active.");
    await run("UPDATE org_memberships SET status = ? WHERE org_id = ? AND user_id = ?", [status, actor.org.id, userId]);
    await audit({ orgId: actor.org.id, userId: actor.user.id, action: "member.status", detail: `${userId} ${status}` });
    return ok({ ok: true, status });
  } catch (err) {
    return fail(err);
  }
}

export async function DELETE(request) {
  try {
    const actor = await currentActor();
    if (actor.membership.role !== "org_owner" && actor.membership.role !== "org_admin") {
      throw new HttpError(403, "Only an organization admin can remove members.");
    }
    const userId = String(new URL(request.url).searchParams.get("userId") || "");
    if (!userId || userId === actor.user.id) throw new HttpError(400, "You cannot remove your own account here.");
    const membership = await one("SELECT org_role AS role FROM org_memberships WHERE org_id = ? AND user_id = ?", [actor.org.id, userId]);
    if (!membership) throw new HttpError(404, "Member not found.");
    if ((await memberPower(actor.org.id, userId)) >= rankOf(actor.membership.role)) {
      throw new HttpError(403, "You can only remove someone below your level.");
    }
    if (membership.role === "org_owner") {
      const owners = await one("SELECT COUNT(*)::int AS count FROM org_memberships WHERE org_id = ? AND org_role = 'org_owner'", [actor.org.id]);
      if (owners.count <= 1) throw new HttpError(400, "Keep at least one organization owner.");
    }
    const projects = await many("SELECT id FROM projects WHERE org_id = ?", [actor.org.id]);
    for (const project of projects) {
      await run("DELETE FROM project_memberships WHERE project_id = ? AND user_id = ?", [project.id, userId]);
    }
    await run("DELETE FROM org_memberships WHERE org_id = ? AND user_id = ?", [actor.org.id, userId]);
    await audit({ orgId: actor.org.id, userId: actor.user.id, action: "member.remove", detail: userId });
    return ok({ ok: true });
  } catch (err) {
    return fail(err);
  }
}
