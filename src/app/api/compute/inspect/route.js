import { assertCan, HttpError } from "@/lib/access";
import { bindAzCaller } from "@/lib/azure/calls";
import { isCompute, metricChoice } from "@/lib/compute";
import { isData, metricChoice as dataMetricChoice } from "@/lib/data";
import { isNetwork, metricChoice as networkMetricChoice } from "@/lib/network";
import { isPlatform, metricChoice as platformMetricChoice } from "@/lib/platform";
import { readSnapshot } from "@/lib/estate-store";
import { executeInspect } from "@/lib/inspect";
import { rememberRead } from "@/lib/read-cache";
import { currentActor, fail, ok } from "@/lib/http";
import { rangeById } from "@/lib/ranges";

export const dynamic = "force-dynamic";

const CACHED = new Set(["metrics", "kql", "containers", "network", "revisions", "layout", "catalog"]);

function ownedRows(snapshot, serviceId) {
  return (snapshot?.resources || []).filter((item) => item.service === serviceId && item.id);
}

export async function POST(request) {
  try {
    const actor = await currentActor();
    const body = await request.json().catch(() => ({}));
    const projectId = String(body.projectId || "");
    const serviceId = String(body.serviceId || "");
    const action = String(body.action || "");
    if (!/^[a-z0-9-]{8,64}$/i.test(projectId) || (!isCompute(serviceId) && !isData(serviceId) && !isNetwork(serviceId) && !isPlatform(serviceId))) throw new HttpError(400, "Choose a service in this project.");
    await assertCan(actor, "resources.read", projectId);
    bindAzCaller({
      orgId: actor.org.id,
      projectId,
      userId: actor.user.id,
      caller: `POST /api/compute/inspect ${action}`,
    });
    const range = rangeById(body.rangeId);
    const snapshot = await readSnapshot(actor.org.id, projectId, range.id);
    const resources = ownedRows(snapshot, serviceId);

    if (CACHED.has(action)) {
      let chosen = resources;
      let input = { rangeId: range.id };
      if (action === "metrics") {
        const choice = metricChoice(serviceId, body.metric) || dataMetricChoice(serviceId, body.metric) || networkMetricChoice(serviceId, body.metric) || platformMetricChoice(serviceId, body.metric);
        if (!choice) throw new HttpError(400, "That metric is not part of this service.");
        const windowId = ["15m", "1h", "6h"].includes(body.window) ? body.window : "1h";
        const wanted = new Set((Array.isArray(body.resourceIds) ? body.resourceIds : []).map((item) => String(item).toLowerCase()));
        chosen = resources.filter((item) => !wanted.size || wanted.has(String(item.id).toLowerCase())).slice(0, 8);
        input = { rangeId: range.id, metric: choice.name, window: windowId, resourceIds: chosen.map((item) => item.id) };
      } else if (action === "kql") {
        input = { rangeId: range.id, clause: String(body.clause || "") };
      } else if (action === "network" || action === "revisions" || action === "layout" || action === "catalog") {
        input = { rangeId: range.id, name: String(body.name || ""), group: String(body.group || "") };
      }
      const payload = await rememberRead({
        orgId: actor.org.id,
        projectId,
        action,
        serviceId,
        input,
        fresh: body.fresh === true,
        cacheOnly: body.cacheOnly === true,
        load: () => executeInspect({ orgId: actor.org.id, projectId, serviceId, action, resources: chosen, body: input }),
      });
      return ok(payload);
    }

    if (action === "logs") {
      try {
        const payload = await executeInspect({
          orgId: actor.org.id,
          projectId,
          serviceId,
          action,
          resources,
          body: { name: body.name, group: body.group, kind: body.kind },
        });
        return ok(payload);
      } catch (err) {
        if (err instanceof HttpError) throw err;
        const text = String(err.message || "");
        if (/AuthorizationFailed|Forbidden/i.test(text)) {
          throw new HttpError(403, "Azure blocked this read. The app registration can see the container app, but it is not allowed to query logs for this environment.");
        }
        throw new HttpError(502, text.replace(/\s+/g, " ").slice(0, 240));
      }
    }

    throw new HttpError(400, "Choose metrics, KQL, revisions, or logs.");
  } catch (err) {
    return fail(err);
  }
}
