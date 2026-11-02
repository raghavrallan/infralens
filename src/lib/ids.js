import { createHash, randomBytes, scryptSync, timingSafeEqual } from "crypto";

export function id() {
  return randomBytes(16).toString("hex");
}

export function slugify(value) {
  const base = String(value || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48);
  return base || "item";
}

const GUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isGuid(value) {
  return GUID.test(String(value || "").trim());
}

export function hashPassword(password) {
  const salt = randomBytes(16).toString("hex");
  const hash = scryptSync(password, salt, 32).toString("hex");
  return `${salt}:${hash}`;
}

export function verifyPassword(password, stored) {
  const [salt, hash] = String(stored || "").split(":");
  if (!salt || !hash) return false;
  const next = scryptSync(String(password), salt, 32);
  const prev = Buffer.from(hash, "hex");
  if (prev.length !== next.length) return false;
  return timingSafeEqual(prev, next);
}

export function usernameFor(email, userId) {
  const clean = String(email || "").trim().toLowerCase();
  if (clean.length > 0 && clean.length <= 64) return clean;
  return `${clean.slice(0, 48)}-${String(userId || "").slice(0, 8)}`.slice(0, 64);
}

export function sha256(value) {
  return createHash("sha256").update(String(value)).digest("hex");
}
