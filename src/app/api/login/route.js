import { audit, HttpError } from "@/lib/access";
import { many, one } from "@/lib/db";
import { fail, ok } from "@/lib/http";
import { verifyPassword } from "@/lib/ids";
import { issueLoginOtp } from "@/lib/login-otp";

export const dynamic = "force-dynamic";

export async function POST(request) {
  try {
    const body = await request.json().catch(() => ({}));
    const login = String(body.login || body.email || "").trim();
    const password = String(body.password || "");
    if (!login || !password) throw new HttpError(401, "Those credentials do not match an account.");
    const candidates = await many(
      `SELECT id, password_hash, email FROM users
       WHERE lower(email) = lower(?)
          OR lower(username) = lower(?)
          OR lower(display_name) = lower(?)`,
      [login, login, login],
    );
    const matched = candidates.filter((user) => verifyPassword(password, user.password_hash));
    if (matched.length !== 1) throw new HttpError(401, "Those credentials do not match an account.");
    const user = matched[0];
    const membership = await one(
      "SELECT org_id, COALESCE(status, 'active') AS status FROM org_memberships WHERE user_id = ? ORDER BY created_at LIMIT 1",
      [user.id],
    );
    if (!membership) throw new HttpError(403, "This account is not a member of an organization.");
    if (membership.status === "suspended") throw new HttpError(403, "Your access to this organization is suspended.");
    const challenge = await issueLoginOtp({ userId: user.id, orgId: membership.org_id, email: user.email });
    await audit({ orgId: membership.org_id, userId: user.id, action: "auth.otp" });
    return ok({ ok: true, step: "otp", ...challenge });
  } catch (err) {
    return fail(err);
  }
}
