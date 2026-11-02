import { bindAzCaller } from "./azure/calls.js";
import { readSnapshot } from "./estate-store.js";
import { executeInspect } from "./inspect.js";
import { listReplays, storeRead } from "./read-cache.js";

const FRESH_MS = 45 * 60 * 1000;

export async function refreshStoredReads(orgId, projectId) {
  const replays = await listReplays(orgId, projectId);
  const due = replays.filter((item) => item.action !== "billing" && item.action !== "invoices" && Date.now() - Number(item.at || 0) > FRESH_MS).slice(0, 8);
  for (const item of due) {
    try {
      bindAzCaller({ orgId, projectId, caller: "estate.sync" });
      const snapshot = await readSnapshot(orgId, projectId, item.input?.rangeId || "mtd");
      const resources = (snapshot?.resources || []).filter((row) => row.service === item.serviceId && row.id);
      let chosen = resources;
      if (item.action === "metrics") {
        const wanted = new Set((item.input?.resourceIds || []).map((id) => String(id).toLowerCase()));
        chosen = resources.filter((row) => !wanted.size || wanted.has(String(row.id).toLowerCase())).slice(0, 8);
      }
      if (item.action === "containers") chosen = resources.slice(0, 30);
      const payload = await executeInspect({
        orgId,
        projectId,
        serviceId: item.serviceId,
        action: item.action,
        resources: chosen,
        body: item.input || {},
      });
      await storeRead(orgId, projectId, item, payload);
    } catch {
      // A failed refresh leaves the previous Redis copy in place.
    }
  }
}
