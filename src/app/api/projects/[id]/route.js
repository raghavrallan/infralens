import { audit, bindConnections, HttpError } from "@/lib/access";
import { one, run } from "@/lib/db";
import { currentActor, fail, ok } from "@/lib/http";
import { setProjectActive } from "@/lib/org-lifecycle";

export const dynamic = "force-dynamic";

export async function PATCH(request, context) {
  try {
    const actor = await currentActor();
    if (actor.membership.role !== "org_owner" && actor.membership.role !== "org_admin") {
      throw new HttpError(403, "Only an organization admin can change a project.");
    }
    const { id } = await context.params;
    const project = await one("SELECT id, name FROM projects WHERE id = ? AND org_id = ?", [id, actor.org.id]);
    if (!project) throw new HttpError(404, "Project not found.");
    const body = await request.json().catch(() => ({}));
    if (body.status === "active" || body.status === "inactive") {
      const next = await setProjectActive(actor.org.id, id, body.status === "active");
      await audit({
        orgId: actor.org.id,
        projectId: id,
        userId: actor.user.id,
        action: body.status === "active" ? "project.activate" : "project.deactivate",
        detail: next?.purge_at ? `History kept until ${new Date(next.purge_at).toISOString().slice(0, 10)}` : project.name,
      });
      if (!body.name && !Array.isArray(body.connectionIds)) return ok({ ok: true, status: next?.status, purgeAt: next?.purge_at || null });
    }
    const name = String(body.name || project.name).trim();
    const budget = body.budget === "" || body.budget == null ? null : Number(body.budget);
    if (name.length < 2) throw new HttpError(400, "Name the project.");
    if (budget != null && (!Number.isFinite(budget) || budget < 0)) throw new HttpError(400, "Budget must be a positive amount in USD.");
    await run("UPDATE projects SET name = ?, budget_usd = ?, updated_at = now() WHERE id = ? AND org_id = ?", [name, budget, id, actor.org.id]);
    if (Array.isArray(body.connectionIds)) await bindConnections(actor.org.id, id, body.connectionIds);
    await audit({ orgId: actor.org.id, projectId: id, userId: actor.user.id, action: "project.update", detail: name });
    return ok({ ok: true });
  } catch (err) {
    return fail(err);
  }
}
