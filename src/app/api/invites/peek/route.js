import { peekInvite } from "@/lib/invites";
import { fail, ok } from "@/lib/http";

export const dynamic = "force-dynamic";

export async function GET(request) {
  try {
    const token = new URL(request.url).searchParams.get("token") || "";
    return ok(await peekInvite(token));
  } catch (err) {
    return fail(err);
  }
}
