import { HttpError } from "./access.js";
import { ESTATE_MESSAGES, EstateError } from "./estate-messages.js";
import { NextResponse } from "next/server";

function entryFor(code) {
  return ESTATE_MESSAGES[code] || ESTATE_MESSAGES.unknown;
}

export function estateErrorResponse(scope, err) {
  if (err instanceof EstateError) {
    const entry = entryFor(err.code);
    return NextResponse.json({ ok: false, code: err.code, part: scope, message: entry.message }, { status: err.status || entry.status });
  }
  if (err instanceof HttpError && err.status === 401) {
    const entry = entryFor("auth.required");
    return NextResponse.json({ ok: false, code: "auth.required", part: scope, message: entry.message }, { status: 401 });
  }
  if (err instanceof HttpError && err.status === 403) {
    const entry = entryFor("auth.forbidden");
    return NextResponse.json({ ok: false, code: "auth.forbidden", part: scope, message: entry.message }, { status: 403 });
  }
  if (err instanceof HttpError) {
    return NextResponse.json({ ok: false, code: `${scope}.failed`, part: scope, message: err.message }, { status: err.status });
  }
  const code = ESTATE_MESSAGES[`${scope}.failed`] ? `${scope}.failed` : "unknown";
  console.error(err);
  return NextResponse.json({ ok: false, code, part: scope, message: entryFor(code).message }, { status: entryFor(code).status });
}

export function estateHandler(scope, load) {
  return async function GET(request) {
    try {
      return NextResponse.json(await load(request));
    } catch (err) {
      return estateErrorResponse(scope, err);
    }
  };
}
