import { assertCan, HttpError } from "@/lib/access";
import { bindAzCaller } from "@/lib/azure/calls";
import { isoDay } from "@/lib/billing";
import { paintSnapshotCost, readBilling } from "@/lib/billing-read";
import { currentActor, fail, ok } from "@/lib/http";
import { rememberRead, storeRead } from "@/lib/read-cache";

export const dynamic = "force-dynamic";

export async function POST(request) {
  try {
    const actor = await currentActor();
    const body = await request.json().catch(() => ({}));
    const projectId = String(body.projectId || "");
    const from = isoDay(body.from);
    const to = isoDay(body.to);
    if (!/^[a-z0-9-]{8,64}$/i.test(projectId) || !from || !to || from >= to) throw new HttpError(400, "Choose a start and end date.");
    const span = (Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86400000;
    if (span > 366) throw new HttpError(400, "Keep a cost range inside one year.");
    await assertCan(actor, "billing.read", projectId);
    bindAzCaller({
      orgId: actor.org.id,
      projectId,
      userId: actor.user.id,
      caller: "POST /api/costs/query",
    });
    const input = { from, to };
    if (body.fresh !== true) {
      const cached = await rememberRead({
        orgId: actor.org.id,
        projectId,
        action: "billing",
        serviceId: "costs",
        input,
        cacheOnly: true,
        load: async () => ({}),
      });
      if (!cached.cacheMiss) return ok(cached);
    }
    const result = await readBilling({ orgId: actor.org.id, projectId, from, to });
    if (!result.partial) {
      await storeRead(actor.org.id, projectId, { action: "billing", serviceId: "costs", input }, result);
      try {
        await paintSnapshotCost(actor.org.id, projectId, String(body.preset || ""), from, to, result.rows, result.currency);
      } catch {
        // The chart still uses this response. The saved dashboard copy can wait for the schedule.
      }
    }
    return ok({ ...result, cached: false, cachedAt: Date.now() });
  } catch (err) {
    return fail(err);
  }
}
