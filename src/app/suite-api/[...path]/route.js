import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

function upstreamBase() {
  const explicit = process.env.SUITE_API_UPSTREAM;
  if (explicit) {
    return explicit.replace(/\/$/, "").replace("://0.0.0.0", "://127.0.0.1");
  }
  const port = process.env.APP_PORT || "8000";
  return `http://127.0.0.1:${port}`;
}

const UPSTREAM = upstreamBase();
const UPSTREAM_PORT = new URL(UPSTREAM).port || "8000";

function rewriteSetCookie(value) {
  let next = String(value || "").replace(/;\s*Domain=[^;]*/gi, "");
  next = next.replace(/;\s*Path=\/api\b[^;]*/gi, "; Path=/");
  if (!/;\s*Path=/i.test(next)) next = `${next}; Path=/`;
  return next.replace(/;\s*;/g, ";").replace(/^\s*;\s*/, "").trim();
}

function isConnectionRefused(error) {
  const seen = new Set();
  function walk(err) {
    if (!err || seen.has(err)) return false;
    seen.add(err);
    if (err.code === "ECONNREFUSED") return true;
    if (typeof err.message === "string" && err.message.includes("ECONNREFUSED")) return true;
    if (Array.isArray(err.errors) && err.errors.some(walk)) return true;
    return walk(err.cause);
  }
  return walk(error);
}

async function proxy(request, context) {
  const { path } = await context.params;
  const joined = (Array.isArray(path) ? path : []).map((segment) => encodeURIComponent(segment)).join("/");
  const target = `${UPSTREAM}/api/${joined}${request.nextUrl.search}`;
  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  const cookie = request.headers.get("cookie");
  const authorization = request.headers.get("authorization");
  const accept = request.headers.get("accept");
  if (contentType) headers.set("content-type", contentType);
  if (cookie) headers.set("cookie", cookie);
  if (authorization) headers.set("authorization", authorization);
  if (accept) headers.set("accept", accept);

  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  let upstream;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? await request.arrayBuffer() : undefined,
      redirect: "manual",
    });
  } catch (error) {
    if (isConnectionRefused(error)) {
      return NextResponse.json(
        { error: `Agentic API is not running on port ${UPSTREAM_PORT}.` },
        { status: 503 },
      );
    }
    const message = error instanceof Error ? error.message : "Agentic API request failed.";
    return NextResponse.json({ error: message }, { status: 502 });
  }

  const out = new Headers();
  const upstreamType = upstream.headers.get("content-type");
  if (upstreamType) out.set("content-type", upstreamType);
  const cache = upstream.headers.get("cache-control");
  if (cache) out.set("cache-control", cache);
  const disposition = upstream.headers.get("content-disposition");
  if (disposition) out.set("content-disposition", disposition);
  const cookies = typeof upstream.headers.getSetCookie === "function" ? upstream.headers.getSetCookie() : [];
  for (const item of cookies) out.append("set-cookie", rewriteSetCookie(item));

  return new Response(upstream.body, { status: upstream.status, headers: out });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
