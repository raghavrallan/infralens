import { randomBytes } from "crypto";
import { one, run } from "./db.js";
import { sha256 } from "./ids.js";

const MAX_AGE = 60 * 60 * 12;

export const COOKIE = "il_session";

export function cookieOptions() {
  return { httpOnly: true, sameSite: "lax", path: "/", maxAge: MAX_AGE };
}

export async function createSession(userId, orgId) {
  const token = randomBytes(32).toString("hex");
  await run(
    "INSERT INTO sessions (token_hash, user_id, org_id, expires_at) VALUES (?, ?, ?, ?)",
    [sha256(token), userId, orgId, Date.now() + MAX_AGE * 1000],
  );
  return token;
}

export async function readSession(token) {
  if (!token) return null;
  const row = await one("SELECT token_hash, user_id, org_id, expires_at FROM sessions WHERE token_hash = ?", [sha256(token)]);
  if (!row || Number(row.expires_at) < Date.now()) return null;
  return row;
}

export async function setSessionOrg(token, orgId) {
  await run("UPDATE sessions SET org_id = ? WHERE token_hash = ?", [orgId, sha256(token)]);
}

export async function destroySession(token) {
  if (!token) return;
  await run("DELETE FROM sessions WHERE token_hash = ?", [sha256(token)]);
}
