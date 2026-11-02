import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { HttpError, requireActor } from "./access.js";
import { COOKIE } from "./session.js";

export async function currentActor() {
  const jar = await cookies();
  return requireActor(jar.get(COOKIE)?.value || "");
}

export async function currentToken() {
  const jar = await cookies();
  return jar.get(COOKIE)?.value || "";
}

export function fail(err) {
  const status = err instanceof HttpError ? err.status : 500;
  const message = status === 500 ? "Something went wrong." : err.message;
  if (status === 500) console.error(err);
  return NextResponse.json({ ok: false, message }, { status });
}

export function ok(body) {
  return NextResponse.json(body);
}
