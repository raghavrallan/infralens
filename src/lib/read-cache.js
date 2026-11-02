import { createHash } from "node:crypto";
import { redisCommand } from "./redis.js";

const HOUR = 60 * 60;
const WEEK = 7 * 24 * 60 * 60;
const inflight = new Map();

const PER_RESOURCE = new Set(["network", "revisions", "layout", "catalog"]);

function fingerprint(action, serviceId, input) {
  const body = { action, serviceId };
  if (action === "metrics") {
    body.metric = input.metric || "";
    body.window = input.window || "1h";
    body.ids = [...(input.resourceIds || [])].map((item) => String(item).toLowerCase()).sort();
  } else if (action === "kql") {
    body.clause = input.clause || "";
  } else if (action === "billing") {
    body.from = input.from || "";
    body.to = input.to || "";
  } else if (action === "invoices") {
    body.scope = "invoices";
  } else if (PER_RESOURCE.has(action)) {
    body.name = String(input.name || "").toLowerCase();
    body.group = String(input.group || "");
  }
  return createHash("sha256").update(JSON.stringify(body)).digest("hex").slice(0, 32);
}

function stampRead(action, input, payload) {
  if (!payload || typeof payload !== "object" || !PER_RESOURCE.has(action)) return payload;
  return {
    ...payload,
    subject: { name: String(input?.name || ""), group: String(input?.group || "") },
  };
}

function keysFor(orgId, projectId, id) {
  return {
    data: `il:read:data:${orgId}:${projectId}:${id}`,
    replay: `il:read:replay:${orgId}:${projectId}:${id}`,
    index: `il:read:index:${orgId}:${projectId}`,
  };
}

async function readJson(key) {
  try {
    const text = await redisCommand(["GET", key]);
    return text ? JSON.parse(text) : null;
  } catch {
    return null;
  }
}

export async function rememberRead({ orgId, projectId, action, serviceId, input, fresh, cacheOnly, load }) {
  const id = fingerprint(action, serviceId, input);
  const keys = keysFor(orgId, projectId, id);
  if (!fresh) {
    const hit = await readJson(keys.data);
    if (hit?.payload) return { ...hit.payload, cached: true, cachedAt: hit.at };
    if (cacheOnly) return { cacheMiss: true, cached: false, cachedAt: null };
    const pending = inflight.get(keys.data);
    if (pending) return pending;
  }
  const run = (async () => {
    const payload = stampRead(action, input, await load());
    const at = Date.now();
    const replay = JSON.stringify({ at, action, serviceId, input });
    try {
      await redisCommand(["SET", keys.data, JSON.stringify({ at, payload }), "EX", String(HOUR)]);
      await redisCommand(["SET", keys.replay, replay, "EX", String(WEEK)]);
      await redisCommand(["SADD", keys.index, id]);
      await redisCommand(["EXPIRE", keys.index, String(WEEK)]);
    } catch {
      // Redis being down still returns the Azure read. The next ask tries again.
    }
    return { ...payload, cached: false, cachedAt: at };
  })();
  if (!fresh) {
    inflight.set(keys.data, run);
    try {
      return await run;
    } finally {
      inflight.delete(keys.data);
    }
  }
  return run;
}

export async function listReplays(orgId, projectId) {
  let ids = [];
  try {
    ids = await redisCommand(["SMEMBERS", `il:read:index:${orgId}:${projectId}`]) || [];
  } catch {
    return [];
  }
  const rows = [];
  for (const id of ids) {
    if (!/^[a-f0-9]{32}$/.test(id)) continue;
    const replay = await readJson(`il:read:replay:${orgId}:${projectId}:${id}`);
    if (!replay?.action || replay.action === "logs") continue;
    const data = await readJson(`il:read:data:${orgId}:${projectId}:${id}`);
    rows.push({ id, ...replay, at: data?.at || replay.at || 0 });
  }
  return rows.sort((a, b) => a.at - b.at);
}

function endpointLabel(replay) {
  const input = replay.input || {};
  const service = replay.serviceId || "service";
  if (replay.action === "metrics") return `${service} · ${input.metric || "metric"} · ${input.window || "1h"}`;
  if (replay.action === "kql") return `${service} · ${input.clause || "default query"}`;
  if (replay.action === "billing") return `billing · ${input.from || ""} – ${input.to || ""}`;
  if (replay.action === "invoices") return "billing · invoices";
  if (replay.action === "network") return `${service} · ${input.name || "network"}`;
  if (replay.action === "revisions") return `${service} · ${input.name || "revisions"}`;
  if (replay.action === "containers") return `${service} · containers`;
  if (replay.action === "layout") return `${service} · ${input.name || "detail"}`;
  if (replay.action === "catalog") return `${service} · ${input.name || "catalog"}`;
  return `${service} · ${replay.action || "read"}`;
}

async function memoryOf(key) {
  try {
    const usage = await redisCommand(["MEMORY", "USAGE", key]);
    if (typeof usage === "number" && usage >= 0) return usage;
  } catch {
    // Older Redis builds can refuse MEMORY USAGE. The string length is the fallback.
  }
  try {
    const length = await redisCommand(["STRLEN", key]);
    return Number(length) || 0;
  } catch {
    return 0;
  }
}

export async function cacheReport(orgId, projectId) {
  const index = `il:read:index:${orgId}:${projectId}`;
  let ids = [];
  try {
    ids = await redisCommand(["SMEMBERS", index]) || [];
  } catch {
    return { bytes: 0, count: 0, entries: [] };
  }
  const entries = [];
  let bytes = 0;
  for (const id of ids) {
    if (!/^[a-f0-9]{32}$/.test(id)) continue;
    const keys = keysFor(orgId, projectId, id);
    const replay = await readJson(keys.replay);
    if (!replay?.action) {
      try {
        await redisCommand(["SREM", index, id]);
      } catch {
        // A stale index member can wait for the next read.
      }
      continue;
    }
    const dataBytes = await memoryOf(keys.data);
    const replayBytes = await memoryOf(keys.replay);
    let ttl = -2;
    try {
      ttl = Number(await redisCommand(["TTL", keys.data]));
    } catch {
      ttl = -2;
    }
    const size = dataBytes + replayBytes;
    bytes += size;
    entries.push({
      id,
      action: replay.action,
      serviceId: replay.serviceId || "",
      endpoint: endpointLabel(replay),
      at: Number(replay.at) || 0,
      bytes: size,
      ttl,
    });
  }
  entries.sort((a, b) => b.at - a.at);
  return { bytes, count: entries.length, entries };
}

export async function deleteCachedRead(orgId, projectId, id) {
  if (!/^[a-f0-9]{32}$/.test(id)) return false;
  const keys = keysFor(orgId, projectId, id);
  await redisCommand(["DEL", keys.data, keys.replay]);
  await redisCommand(["SREM", keys.index, id]);
  return true;
}

export async function deleteProjectCache(orgId, projectId) {
  const index = `il:read:index:${orgId}:${projectId}`;
  let ids = [];
  try {
    ids = await redisCommand(["SMEMBERS", index]) || [];
  } catch {
    return 0;
  }
  let removed = 0;
  for (const id of ids) {
    if (!/^[a-f0-9]{32}$/.test(id)) continue;
    await deleteCachedRead(orgId, projectId, id);
    removed += 1;
  }
  try {
    await redisCommand(["DEL", index]);
  } catch {
    // The members are already gone.
  }
  return removed;
}

export async function storeRead(orgId, projectId, replay, payload) {
  const id = fingerprint(replay.action, replay.serviceId, replay.input);
  const keys = keysFor(orgId, projectId, id);
  const at = Date.now();
  const stamped = stampRead(replay.action, replay.input, payload);
  await redisCommand(["SET", keys.data, JSON.stringify({ at, payload: stamped }), "EX", String(HOUR)]);
  await redisCommand(["SET", keys.replay, JSON.stringify({ at, action: replay.action, serviceId: replay.serviceId, input: replay.input }), "EX", String(WEEK)]);
  await redisCommand(["SADD", keys.index, id]);
  await redisCommand(["EXPIRE", keys.index, String(WEEK)]);
  return at;
}
