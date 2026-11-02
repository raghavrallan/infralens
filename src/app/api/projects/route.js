import { audit, bindConnections, HttpError } from "@/lib/access";
import { one, run } from "@/lib/db";
import { currentActor, fail, ok } from "@/lib/http";
import { id, slugify } from "@/lib/ids";

export const dynamic = "force-dynamic";

export async function POST(request) {
  try {
    const actor = await currentActor();
    if (actor.membership.role !== "org_owner" && actor.membership.role !== "org_admin") {
      throw new HttpError(403, "Only an organization admin can create a project.");
    }
    const body = await request.json().catch(() => ({}));
    const name = String(body.name || "").trim();
    const budget = body.budget === "" || body.budget == null ? null : Number(body.budget);
    if (name.length < 2) throw new HttpError(400, "Name the project.");
    if (budget != null && (!Number.isFinite(budget) || budget < 0)) throw new HttpError(400, "Budget must be a positive amount in USD.");
    const projectId = id();
    let slug = slugify(name);
    if (await one("SELECT id FROM projects WHERE org_id = ? AND slug = ?", [actor.org.id, slug])) slug = `${slug}-${projectId.slice(0, 4)}`;
    await run(
      "INSERT INTO projects (id, org_id, name, slug, budget_usd, repos, created_at, updated_at) VALUES (?, ?, ?, ?, ?, '[]'::jsonb, now(), now())",
      [projectId, actor.org.id, name, slug, budget],
    );
    await bindConnections(actor.org.id, projectId, body.connectionIds || []);
    await audit({ orgId: actor.org.id, projectId, userId: actor.user.id, action: "project.create", detail: name });
    return ok({ ok: true, id: projectId });
  } catch (err) {
    return fail(err);
  }
}
