import { NextResponse } from "next/server";
import { audit } from "@/lib/access";
import { one, run } from "@/lib/db";
import { fail } from "@/lib/http";
import { HttpError } from "@/lib/access";
import { hashPassword, id, slugify, usernameFor } from "@/lib/ids";
import { COOKIE, cookieOptions, createSession } from "@/lib/session";

export const dynamic = "force-dynamic";

export async function POST(request) {
  try {
    const body = await request.json().catch(() => ({}));
    const name = String(body.name || "").trim();
    const orgName = String(body.orgName || "").trim();
    const email = String(body.email || "").trim().toLowerCase();
    const password = String(body.password || "");
    if (name.length < 2 || orgName.length < 2) throw new HttpError(400, "Enter your name and the organization name.");
    if (!email.includes("@") || email.length > 160) throw new HttpError(400, "Enter a valid email.");
    if (password.length < 8) throw new HttpError(400, "Use a password of at least 8 characters.");
    if (await one("SELECT id FROM users WHERE lower(email) = lower(?)", [email])) {
      throw new HttpError(409, "That email already has an account. Sign in, or ask an admin to add you to the organization.");
    }
    const userId = id();
    const orgId = id();
    let slug = slugify(orgName);
    if (await one("SELECT id FROM organizations WHERE slug = ?", [slug])) slug = `${slug}-${orgId.slice(0, 4)}`;
    await run(
      "INSERT INTO users (id, username, email, display_name, password_hash, role, is_active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'org_admin', true, now(), now())",
      [userId, usernameFor(email, userId), email, name, hashPassword(password)],
    );
    await run(
      "INSERT INTO organizations (id, name, slug, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, now(), now())",
      [orgId, orgName, slug, userId],
    );
    await run(
      "INSERT INTO org_memberships (id, org_id, user_id, org_role, created_at) VALUES (?, ?, ?, 'org_owner', now())",
      [id(), orgId, userId],
    );
    await audit({ orgId, userId, action: "org.create", detail: orgName });
    const response = NextResponse.json({ ok: true });
    response.cookies.set(COOKIE, await createSession(userId, orgId), cookieOptions());
    return response;
  } catch (err) {
    return fail(err);
  }
}
