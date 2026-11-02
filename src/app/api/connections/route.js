import { audit, HttpError, replaceSubscriptions } from "@/lib/access";
import { bindAzCaller } from "@/lib/azure/calls";
import { listSandboxSubscriptions } from "@/lib/azure/sandbox";
import { redact } from "@/lib/azure/cli";
import { encrypt } from "@/lib/crypto";
import { isUniqueViolation, one, run } from "@/lib/db";
import { currentActor, fail, ok } from "@/lib/http";
import { id, isGuid } from "@/lib/ids";

export const dynamic = "force-dynamic";

export async function POST(request) {
  try {
    const actor = await currentActor();
    if (actor.membership.role !== "org_owner" && actor.membership.role !== "org_admin") {
      throw new HttpError(403, "Only an organization admin can connect Azure.");
    }
    const body = await request.json().catch(() => ({}));
    const name = String(body.name || "").trim();
    const tenantId = String(body.tenantId || "").trim();
    const clientId = String(body.clientId || "").trim();
    const clientSecret = String(body.clientSecret || "");
    if (name.length < 2) throw new HttpError(400, "Name the connection.");
    if (!isGuid(tenantId) || !isGuid(clientId)) throw new HttpError(400, "Tenant ID and client ID must be Azure GUIDs.");
    if (clientSecret.length < 8) throw new HttpError(400, "Paste the client secret from the app registration.");
    const normalizedClientId = clientId.toLowerCase();
    const existing = await one("SELECT id, org_id FROM azure_connections WHERE lower(client_id) = lower(?)", [normalizedClientId]);
    if (existing && existing.org_id !== actor.org.id) {
      throw new HttpError(409, "That client ID is already connected to another organization.");
    }
    let connectionId = existing?.id || id();
    const now = Date.now();
    const cipher = encrypt(clientSecret);
    const saveExisting = async (rowId) => {
      await run(
        `UPDATE azure_connections
         SET name = ?, tenant_id = ?, client_id = ?, secret_cipher = ?, status = 'pending', status_detail = ''
         WHERE id = ? AND org_id = ?`,
        [name, tenantId.toLowerCase(), normalizedClientId, cipher, rowId, actor.org.id],
      );
    };
    if (existing) await saveExisting(connectionId);
    else {
      try {
        await run(
          `INSERT INTO azure_connections
           (id, org_id, name, tenant_id, client_id, secret_cipher, status, status_detail, created_at)
           VALUES (?, ?, ?, ?, ?, ?, 'pending', '', ?)`,
          [connectionId, actor.org.id, name, tenantId.toLowerCase(), normalizedClientId, cipher, now],
        );
      } catch (err) {
        if (!isUniqueViolation(err)) throw err;
        const winner = await one("SELECT id, org_id FROM azure_connections WHERE lower(client_id) = lower(?)", [normalizedClientId]);
        if (!winner || winner.org_id !== actor.org.id) throw new HttpError(409, "That client ID is already connected to another organization.");
        connectionId = winner.id;
        await saveExisting(connectionId);
      }
    }
    try {
      bindAzCaller({ orgId: actor.org.id, userId: actor.user.id, caller: "POST /api/connections" });
      const subscriptions = await listSandboxSubscriptions(connectionId, { tenantId, clientId: normalizedClientId, clientSecret });
      await replaceSubscriptions(actor.org.id, connectionId, subscriptions);
      await run(
        "UPDATE azure_connections SET status = 'connected', status_detail = ?, last_checked_at = ? WHERE id = ? AND org_id = ?",
        [`${subscriptions.length} subscriptions visible`, now, connectionId, actor.org.id],
      );
      await audit({ orgId: actor.org.id, userId: actor.user.id, action: existing ? "azure.update" : "azure.connect", detail: name });
      return ok({ ok: true, updated: Boolean(existing), subscriptionCount: subscriptions.length });
    } catch (err) {
      const message = redact(err.message, clientSecret);
      await run(
        "UPDATE azure_connections SET status = 'error', status_detail = ?, last_checked_at = ? WHERE id = ? AND org_id = ?",
        [message, now, connectionId, actor.org.id],
      );
      throw new HttpError(502, message);
    }
  } catch (err) {
    return fail(err);
  }
}
