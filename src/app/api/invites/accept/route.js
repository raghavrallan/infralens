import { acceptInvite } from "@/lib/invites";
import { fail, ok } from "@/lib/http";

export const dynamic = "force-dynamic";

export async function POST(request) {
  try {
    const body = await request.json().catch(() => ({}));
    return ok(await acceptInvite({ token: body.token, name: body.name, password: body.password }));
  } catch (err) {
    return fail(err);
  }
}
