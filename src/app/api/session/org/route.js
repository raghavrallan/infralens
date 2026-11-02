import { HttpError } from "@/lib/access";
import { one } from "@/lib/db";
import { currentActor, currentToken, fail, ok } from "@/lib/http";
import { setSessionOrg } from "@/lib/session";

export const dynamic = "force-dynamic";

export async function POST(request) {
  try {
    const actor = await currentActor();
    const body = await request.json().catch(() => ({}));
    const orgId = String(body.orgId || "");
    const membership = await one("SELECT org_role AS role FROM org_memberships WHERE org_id = ? AND user_id = ?", [orgId, actor.user.id]);
    if (!membership) throw new HttpError(403, "You are not a member of that organization.");
    await setSessionOrg(await currentToken(), orgId);
    return ok({ ok: true });
  } catch (err) {
    return fail(err);
  }
}
