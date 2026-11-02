import { audit, connectionSecrets, HttpError, replaceSubscriptions } from "@/lib/access";
import { bindAzCaller } from "@/lib/azure/calls";
import { listSandboxSubscriptions } from "@/lib/azure/sandbox";
import { run } from "@/lib/db";
import { currentActor, fail, ok } from "@/lib/http";

export const dynamic = "force-dynamic";

export async function POST(_request, context) {
  try {
    const actor = await currentActor();
    if (actor.membership.role !== "org_owner" && actor.membership.role !== "org_admin") {
      throw new HttpError(403, "Only an organization admin can refresh Azure subscriptions.");
    }
    const { id } = await context.params;
    bindAzCaller({ orgId: actor.org.id, userId: actor.user.id, caller: "POST /api/connections/refresh" });
    const creds = await connectionSecrets(id, actor.org.id);
    const subscriptions = await listSandboxSubscriptions(id, creds);
    creds.clientSecret = "";
    await replaceSubscriptions(actor.org.id, id, subscriptions);
    const now = Date.now();
    await run(
      "UPDATE azure_connections SET status = 'connected', status_detail = ?, last_checked_at = ? WHERE id = ? AND org_id = ?",
      [`${subscriptions.length} subscriptions visible`, now, id, actor.org.id],
    );
    await audit({ orgId: actor.org.id, userId: actor.user.id, action: "azure.refresh", detail: id });
    return ok({ ok: true, subscriptions });
  } catch (err) {
    return fail(err);
  }
}
