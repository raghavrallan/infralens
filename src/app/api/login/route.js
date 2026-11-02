import { NextResponse } from "next/server";
import { audit, HttpError } from "@/lib/access";
import { one } from "@/lib/db";
import { fail } from "@/lib/http";
import { verifyPassword } from "@/lib/ids";
import { COOKIE, cookieOptions, createSession } from "@/lib/session";

export const dynamic = "force-dynamic";

export async function POST(request) {
  try {
    const body = await request.json().catch(() => ({}));
    const email = String(body.email || "").trim().toLowerCase();
    const password = String(body.password || "");
    const user = await one("SELECT id, password_hash FROM users WHERE lower(email) = lower(?)", [email]);
    if (!user || !verifyPassword(password, user.password_hash)) throw new HttpError(401, "Those credentials do not match an account.");
    const membership = await one("SELECT org_id FROM org_memberships WHERE user_id = ? ORDER BY created_at LIMIT 1", [user.id]);
    if (!membership) throw new HttpError(403, "This account is not a member of an organization.");
    await audit({ orgId: membership.org_id, userId: user.id, action: "auth.login" });
    const response = NextResponse.json({ ok: true });
    response.cookies.set(COOKIE, await createSession(user.id, membership.org_id), cookieOptions());
    return response;
  } catch (err) {
    return fail(err);
  }
}
