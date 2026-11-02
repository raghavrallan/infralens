import { currentActor, fail, ok } from "@/lib/http";
import { workspacePayload } from "@/lib/workspace";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const actor = await currentActor();
    return ok(await workspacePayload(actor));
  } catch (err) {
    return fail(err);
  }
}
