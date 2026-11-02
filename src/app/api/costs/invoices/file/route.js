import { NextResponse } from "next/server";
import { assertCan, HttpError } from "@/lib/access";
import { currentActor, fail } from "@/lib/http";
import { invoiceFileName, readSavedPdf } from "@/lib/invoice-store";

export const dynamic = "force-dynamic";

export async function POST(request) {
  try {
    const actor = await currentActor();
    const body = await request.json().catch(() => ({}));
    const projectId = String(body.projectId || "");
    const name = String(body.name || "");
    if (!/^[a-z0-9-]{8,64}$/i.test(projectId) || !name) throw new HttpError(400, "Choose an invoice on this project.");
    await assertCan(actor, "billing.read", projectId);
    const bytes = await readSavedPdf(projectId, name);
    if (!bytes) throw new HttpError(404, "This invoice is not in the project folder yet. The sandbox sync saves each bill once.");
    return new NextResponse(bytes, {
      headers: {
        "Content-Type": "application/pdf",
        "Content-Disposition": `attachment; filename="${invoiceFileName(name)}"`,
      },
    });
  } catch (err) {
    return fail(err);
  }
}
