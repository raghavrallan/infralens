import { spawn } from "child_process";
import { closeSync, existsSync, mkdirSync, openSync, statSync, unlinkSync, writeSync } from "fs";
import path from "path";
import { recordAzCall } from "./calls.js";
import { isGuid } from "../ids.js";

const queues = new Map();

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function enqueue(key, work) {
  const previous = queues.get(key) || Promise.resolve();
  const run = previous.catch(() => {}).then(work);
  queues.set(key, run);
  return run.finally(() => {
    if (queues.get(key) === run) queues.delete(key);
  });
}

async function withProfileLock(profile, work) {
  mkdirSync(profile, { recursive: true });
  const lock = path.join(profile, ".sandbox.lock");
  const started = Date.now();
  while (Date.now() - started < 200000) {
    try {
      const fd = openSync(lock, "wx");
      writeSync(fd, String(process.pid));
      closeSync(fd);
      try {
        return await work();
      } finally {
        try {
          unlinkSync(lock);
        } catch {
          // Another owner already cleared a stale lock.
        }
      }
    } catch (err) {
      if (err.code !== "EEXIST") throw err;
      try {
        if (Date.now() - statSync(lock).mtimeMs > 200000) unlinkSync(lock);
      } catch {
        // The owner released the lock between the checks.
      }
      await sleep(400);
    }
  }
  throw new Error("This project's Azure sandbox is busy. The next scheduled run will try again.");
}

const ALLOWED = new Set([
  "version",
  "login",
  "account",
  "rest",
  "resource",
  "vm",
  "group",
  "databricks",
  "storage",
  "containerapp",
  "aks",
  "webapp",
  "datafactory",
  "advisor",
  "monitor",
]);

function launcher() {
  if (process.env.AZURE_CLI_PYTHON && existsSync(process.env.AZURE_CLI_PYTHON)) {
    return { command: process.env.AZURE_CLI_PYTHON, prefix: ["-IBm", "azure.cli"] };
  }
  const windows = "C:\\Program Files\\Microsoft SDKs\\Azure\\CLI2\\python.exe";
  if (process.platform === "win32" && existsSync(windows)) {
    return { command: windows, prefix: ["-IBm", "azure.cli"] };
  }
  return { command: "az", prefix: [] };
}

export function profileDir(connectionId) {
  if (!/^[a-f0-9]{32}$/.test(connectionId)) throw new Error("Invalid connection.");
  return path.join(process.cwd(), "data", "azure-profiles", connectionId);
}

export function redact(text, secret) {
  let out = String(text || "");
  if (secret) out = out.split(secret).join("[redacted]");
  return out.replace(/Bearer\s+\S+/gi, "Bearer [redacted]").replace(/\s+/g, " ").trim().slice(0, 700);
}

export function runAz(profile, args, options = {}) {
  if (!ALLOWED.has(args[0])) throw new Error("That Azure CLI command is not allowed.");
  return enqueue(profile, () => withProfileLock(profile, () => spawnAz(profile, args, options)));
}

function describeAzArgs(args) {
  const command = String(args[0] || "az");
  if (command === "login") return { command, method: "", route: "az login --service-principal" };
  if (command === "rest") {
    const methodAt = args.indexOf("--method");
    const urlAt = args.indexOf("--url");
    const method = String(args[methodAt + 1] || "get").toUpperCase();
    try {
      const url = new URL(String(args[urlAt + 1] || ""));
      const api = url.searchParams.get("api-version");
      return { command, method, route: `${url.host}${url.pathname}${api ? `?api-version=${api}` : ""}`.slice(0, 500) };
    } catch {
      return { command, method, route: "az rest" };
    }
  }
  const hidden = new Set(["--password", "--username", "--tenant", "--body", "-o"]);
  const parts = [];
  for (let index = 0; index < args.length; index += 1) {
    if (hidden.has(args[index])) {
      index += 1;
      continue;
    }
    parts.push(String(args[index]));
  }
  return { command, method: "", route: parts.join(" ").slice(0, 500) };
}

function noteAzCall(profile, args, status, started, detail, secret) {
  const described = describeAzArgs(args);
  void recordAzCall({
    profile,
    ...described,
    status,
    durationMs: Date.now() - started,
    detail: redact(detail, secret).slice(0, 180),
  }).catch(() => {});
}

function spawnAz(profile, args, { secret, timeoutMs = 180000 } = {}) {
  mkdirSync(profile, { recursive: true });
  const started = Date.now();
  let noted = false;
  const note = (status, detail) => {
    if (noted) return;
    noted = true;
    noteAzCall(profile, args, status, started, detail, secret);
  };
  const { command, prefix } = launcher();
  const env = {
    ...process.env,
    AZURE_CONFIG_DIR: profile,
    AZURE_CORE_COLLECT_TELEMETRY: "0",
    AZURE_CORE_NO_COLOR: "1",
  };
  for (const key of ["AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET", "AZURE_TENANT_ID", "AZURE_CLIENT_CERTIFICATE_PATH", "AZURE_SUBSCRIPTION_ID", "AZURE_USERNAME", "AZURE_PASSWORD"]) {
    delete env[key];
  }
  return new Promise((resolve, reject) => {
    let child;
    try {
      child = spawn(command, [...prefix, ...args], { shell: false, windowsHide: true, env });
    } catch (err) {
      const message = err.code === "ENOENT" ? "Azure CLI is not installed on this server." : err.message;
      note("fail", message);
      reject(err.code === "ENOENT" ? new Error(message) : err);
      return;
    }
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      note("fail", "Azure CLI timed out.");
      child.kill();
      reject(new Error("Azure CLI timed out."));
    }, timeoutMs);
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });
    child.on("error", (err) => {
      clearTimeout(timer);
      const message = err.code === "ENOENT" ? "Azure CLI is not installed on this server." : err.message;
      note("fail", message);
      reject(err.code === "ENOENT" ? new Error("Azure CLI is not installed on this server.") : err);
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      if (code !== 0) {
        const message = redact(stderr || stdout || `Azure CLI exited ${code}`, secret) || "Azure CLI failed.";
        note("fail", message);
        reject(new Error(message));
        return;
      }
      note("ok", "");
      const text = stdout.trim();
      if (!text || text === "null") {
        resolve(null);
        return;
      }
      try {
        resolve(JSON.parse(text));
      } catch {
        resolve(text);
      }
    });
  });
}

export async function ensureLogin(profile, creds) {
  try {
    const token = await runAz(profile, ["account", "get-access-token", "--resource", "https://management.azure.com", "-o", "json"]);
    const expires = Date.parse(token?.expiresOn || token?.expires_on || "");
    if (Number.isFinite(expires) && expires - Date.now() > 5 * 60 * 1000) return;
  } catch {
    // The isolated profile has no usable token yet.
  }
  await runAz(
    profile,
    ["login", "--service-principal", "--username", creds.clientId, "--password", creds.clientSecret, "--tenant", creds.tenantId, "-o", "none"],
    { secret: creds.clientSecret }
  );
}

export async function listSubscriptions(profile) {
  const rows = await runAz(profile, ["account", "list", "--refresh", "-o", "json"]);
  return (Array.isArray(rows) ? rows : [])
    .map((row) => ({ id: row.id, name: row.name || row.id, state: row.state || "" }))
    .filter((row) => isGuid(row.id));
}

export function assertSubscription(subscriptionId) {
  if (!isGuid(subscriptionId)) throw new Error("Invalid subscription.");
  return subscriptionId;
}

export async function costQuery(profile, subscriptionId, body) {
  const id = assertSubscription(subscriptionId);
  const url = `https://management.azure.com/subscriptions/${id}/providers/Microsoft.CostManagement/query?api-version=2023-11-01`;
  return runAz(profile, ["rest", "--method", "post", "--url", url, "--body", JSON.stringify(body), "-o", "json"]);
}

export async function azJson(profile, args) {
  const rows = await runAz(profile, [...args, "-o", "json"]);
  return Array.isArray(rows) ? rows : [];
}

const locks = new Map();

export function withLock(key, work) {
  const previous = locks.get(key) || Promise.resolve();
  const run = previous.catch(() => {}).then(work);
  locks.set(key, run);
  return run.finally(() => {
    if (locks.get(key) === run) locks.delete(key);
  });
}
