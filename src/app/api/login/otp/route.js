import { NextResponse } from "next/server";
import { audit } from "@/lib/access";
import { fail } from "@/lib/http";
import { sendLoginNotice } from "@/lib/login-notice";
import { resendLoginOtp, verifyLoginOtp } from "@/lib/login-otp";
import { COOKIE, cookieOptions, createSession } from "@/lib/session";

export const dynamic = "force-dynamic";

export async function POST(request) {
  try {
    const body = await request.json().catch(() => ({}));
    if (body.resend) {
      const sent = await resendLoginOtp(body.challengeId);
      return NextResponse.json(sent);
    }
    const verified = await verifyLoginOtp(body.challengeId, body.code);
    await audit({ orgId: verified.orgId, userId: verified.userId, action: "auth.login" });
    try {
      await sendLoginNotice(request, verified.email);
    } catch (err) {
      console.error("Login notice failed:", err?.message || "notice");
    }
    const response = NextResponse.json({ ok: true });
    response.cookies.set(COOKIE, await createSession(verified.userId, verified.orgId), cookieOptions());
    return response;
  } catch (err) {
    return fail(err);
  }
}
