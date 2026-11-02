import { createCipheriv, createDecipheriv, randomBytes, scryptSync } from "crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "fs";
import path from "path";

function secretMaterial() {
  if (process.env.APP_SECRET && process.env.APP_SECRET.trim()) return process.env.APP_SECRET.trim();
  const file = path.join(process.cwd(), "data", "app-secret");
  if (!existsSync(file)) {
    mkdirSync(path.dirname(file), { recursive: true });
    writeFileSync(file, randomBytes(32).toString("hex"), { mode: 0o600 });
  }
  return readFileSync(file, "utf8").trim();
}

function key() {
  return scryptSync(secretMaterial(), "infralens-live-v1", 32);
}

export function encrypt(plain) {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key(), iv);
  const body = Buffer.concat([cipher.update(String(plain), "utf8"), cipher.final()]);
  const tag = cipher.getAuthTag();
  return `${iv.toString("base64")}.${tag.toString("base64")}.${body.toString("base64")}`;
}

export function decrypt(payload) {
  const [ivB64, tagB64, bodyB64] = String(payload || "").split(".");
  if (!ivB64 || !tagB64 || !bodyB64) throw new Error("Stored Azure secret could not be read.");
  const decipher = createDecipheriv("aes-256-gcm", key(), Buffer.from(ivB64, "base64"));
  decipher.setAuthTag(Buffer.from(tagB64, "base64"));
  return Buffer.concat([decipher.update(Buffer.from(bodyB64, "base64")), decipher.final()]).toString("utf8");
}
