import { assertCan, HttpError } from "@/lib/access";
import { currentActor, fail, ok } from "@/lib/http";
import { syncProjectInvoices } from "@/lib/invoice-sync";
import { readInvoiceIndex } from "@/lib/invoice-store";

export const dynamic = "force-dynamic";

export async function POST(request) {
  try {
    const actor = await currentActor();
    const body = await request.json().catch(() => ({}));
    const projectId = String(body.projectId || "");
    if (!/^[a-z0-9-]{8,64}$/i.test(projectId)) throw new HttpError(400, "Choose a project.");
    await assertCan(actor, "billing.read", projectId);
    if (body.fresh === true) {
      return ok(await syncProjectInvoices({ orgId: actor.org.id, projectId }));
    }
    const index = await readInvoiceIndex(projectId);
    if (!index.checkedAt && !index.invoices.length && !index.message) {
      index.message = "Invoices are saved on the sandbox sync, in a folder for this project. A bill is downloaded once, and again only when its name is new.";
    }
    return ok(index);
  } catch (err) {
    return fail(err);
  }
}
