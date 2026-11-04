import { randomInt, timingSafeEqual } from "node:crypto";
import { one, run } from "./db.js";
import { HttpError } from "./access.js";
import { id, sha256 } from "./ids.js";
import { codeDigits, emailDocument } from "./email-layout.js";
import { sendEmail } from "./mail.js";

export const OTP_MINUTES = 10;
const MAX_ATTEMPTS = 5;
const RESEND_SECONDS = 30;

let ready;

function ensureLoginOtps() {
  ready ||= run(`
    CREATE TABLE IF NOT EXISTS login_otps (
      id VARCHAR(36) PRIMARY KEY,
      user_id VARCHAR(36) NOT NULL,
      org_id VARCHAR(36) NOT NULL,
      email VARCHAR(255) NOT NULL,
      code_hash VARCHAR(64) NOT NULL,
      expires_at TIMESTAMPTZ NOT NULL,
      attempts INTEGER NOT NULL DEFAULT 0,
      sent_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS login_otps_user ON login_otps (user_id);
  `).catch((err) => {
    ready = null;
    throw err;
  });
  return ready;
}

export function maskEmail(email) {
  const [name, domain] = String(email || "").split("@");
  if (!name || !domain) return "";
  return `${name.slice(0, 1)}${"*".repeat(Math.max(1, name.length - 1))}@${domain}`;
}

function codeHash(challengeId, code) {
  return sha256(`${challengeId}:${String(code || "").trim()}`);
}

function hashesMatch(left, right) {
  const a = Buffer.from(String(left || ""));
  const b = Buffer.from(String(right || ""));
  if (a.length !== b.length || a.length === 0) return false;
  return timingSafeEqual(a, b);
}

function otpEmail(code) {
  const subject = "Your Infralens sign-in code";
  const text = [
    "Your Infralens sign-in code is:",
    "",
    code,
    "",
    `It expires in ${OTP_MINUTES} minutes. If you did not try to sign in, ignore this email.`,
  ].join("\n");
  const html = emailDocument({
    preheader: `Your Infralens sign-in code is ${code}. It expires in ${OTP_MINUTES} minutes.`,
    eyebrow: "Sign in",
    title: "Your code is ready",
    intro: `Enter these six digits to finish signing in. The code expires in ${OTP_MINUTES} minutes.`,
    content: codeDigits(code),
    note: "If you did not try to sign in, you can ignore this email. Nobody at Infralens will ask you for this code.",
  });
  return { subject, text, html };
}

async function deliver(challengeId, email, code) {
  const message = otpEmail(code);
  const sent = await sendEmail({ to: email, ...message });
  if (!sent.ok) {
    await run("DELETE FROM login_otps WHERE id = ?", [challengeId]);
    throw new HttpError(503, sent.error === "Could not reach the mail server."
      ? "Could not reach the mail server. Outbound port 587 needs to be allowed."
      : "Could not email the sign-in code. Try again in a moment.");
  }
}

export async function issueLoginOtp({ userId, orgId, email }) {
  await ensureLoginOtps();
  await run("DELETE FROM login_otps WHERE user_id = ? OR expires_at < now()", [userId]);
  const challengeId = id();
  const code = String(randomInt(0, 1000000)).padStart(6, "0");
  await run(
    `INSERT INTO login_otps (id, user_id, org_id, email, code_hash, expires_at, attempts, sent_at)
     VALUES (?, ?, ?, ?, ?, now() + interval '${OTP_MINUTES} minutes', 0, now())`,
    [challengeId, userId, orgId, email, codeHash(challengeId, code)],
  );
  await deliver(challengeId, email, code);
  return { challengeId, emailHint: maskEmail(email) };
}

export async function resendLoginOtp(challengeId) {
  await ensureLoginOtps();
  const row = await one(
    "SELECT id, user_id, email, sent_at, expires_at FROM login_otps WHERE id = ?",
    [String(challengeId || "")],
  );
  if (!row || new Date(row.expires_at).getTime() <= Date.now()) {
    throw new HttpError(410, "That sign-in code has expired. Enter your password again.");
  }
  const waited = Date.now() - new Date(row.sent_at).getTime();
  if (waited < RESEND_SECONDS * 1000) throw new HttpError(429, "Wait a moment before sending another code.");
  const code = String(randomInt(0, 1000000)).padStart(6, "0");
  await run(
    "UPDATE login_otps SET code_hash = ?, attempts = 0, sent_at = now(), expires_at = now() + interval '10 minutes' WHERE id = ?",
    [codeHash(row.id, code), row.id],
  );
  await deliver(row.id, row.email, code);
  return { ok: true, challengeId: row.id, emailHint: maskEmail(row.email) };
}

export async function verifyLoginOtp(challengeId, code) {
  await ensureLoginOtps();
  const entered = String(code || "").trim();
  if (!/^\d{6}$/.test(entered)) throw new HttpError(400, "Enter the 6-digit code from the email.");
  const row = await one(
    "SELECT id, user_id, org_id, email, code_hash, attempts, expires_at FROM login_otps WHERE id = ?",
    [String(challengeId || "")],
  );
  if (!row) throw new HttpError(401, "That sign-in code is no longer valid. Enter your password again.");
  if (new Date(row.expires_at).getTime() <= Date.now()) {
    await run("DELETE FROM login_otps WHERE id = ?", [row.id]);
    throw new HttpError(410, "That sign-in code has expired. Enter your password again.");
  }
  if (Number(row.attempts) >= MAX_ATTEMPTS) {
    await run("DELETE FROM login_otps WHERE id = ?", [row.id]);
    throw new HttpError(401, "Too many attempts. Enter your password again.");
  }
  if (!hashesMatch(row.code_hash, codeHash(row.id, entered))) {
    await run("UPDATE login_otps SET attempts = attempts + 1 WHERE id = ?", [row.id]);
    throw new HttpError(401, "That code does not match. Check the email and try again.");
  }
  await run("DELETE FROM login_otps WHERE id = ?", [row.id]);
  return { userId: row.user_id, orgId: row.org_id, email: row.email };
}
