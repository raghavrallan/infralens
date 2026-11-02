const TOKEN_KEY = "infralens_auth_token";
const USER_KEY = "infralens_auth_user";
const PROJECT_KEY = "projectId";

export const SUITE_DOWN =
  "The skills API is not running, start it with `python scripts/run_local_api.py` from the repo root (Postgres and Redis via docker compose).";

export function suitePath(path) {
  const raw = String(path || "");
  const rest = raw.startsWith("/api") ? raw.slice(4) : raw;
  const normalized = rest.startsWith("/") ? rest : `/${rest}`;
  return `/suite-api${normalized}`;
}

export function suiteToken() {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(TOKEN_KEY) || "";
}

export function getSuiteToken() {
  return suiteToken();
}

export function suiteUser() {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function saveSuiteSession(session) {
  if (!session?.token || typeof window === "undefined") return;
  window.localStorage.setItem(TOKEN_KEY, session.token);
  if (session.user) window.localStorage.setItem(USER_KEY, JSON.stringify(session.user));
  window.localStorage.removeItem(PROJECT_KEY);
}

export function clearSuiteSession() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
}

export function rememberSuiteUser(user) {
  if (!user || typeof window === "undefined") return;
  window.localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function prettyName(value = "") {
  return String(value)
    .split("_")
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export function timeAgo(iso) {
  if (!iso) return "never";
  const seconds = Math.max(1, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export function timeUntil(seconds) {
  if (seconds == null) return "";
  if (seconds <= 0) return "expired";
  const hours = Math.round(seconds / 3600);
  return hours < 1 ? `${Math.max(1, Math.round(seconds / 60))}m left` : `${hours}h left`;
}

const ROLE_ORDER = ["viewer", "developer", "devops_engineer", "devops_lead", "org_admin", "super_admin"];

export function hasMinRole(role, minimum) {
  if (!minimum) return true;
  return ROLE_ORDER.indexOf(role || "viewer") >= ROLE_ORDER.indexOf(minimum);
}

export function suiteDetail(data, fallback = "Request failed") {
  if (typeof data?.detail === "string" && data.detail) return data.detail;
  if (Array.isArray(data?.detail)) {
    return data.detail.map((item) => item?.msg || String(item)).join(" ");
  }
  return data?.error || data?.message || fallback;
}

export function isSuiteDown(error) {
  return error?.status === 503 || String(error?.message || "") === SUITE_DOWN;
}

export function suiteDownMessage(error) {
  if (error instanceof Error && error.message) return error.message;
  return SUITE_DOWN;
}

export function getSuiteUser() {
  return suiteUser();
}

export function getSuiteProjectId() {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(PROJECT_KEY) || "";
}

export function setSuiteProjectId(id) {
  if (typeof window === "undefined") return;
  if (id) window.localStorage.setItem(PROJECT_KEY, id);
  else window.localStorage.removeItem(PROJECT_KEY);
}

export async function suiteFetch(path, options = {}) {
  const headers = new Headers(options.headers || {});
  let body = options.body;
  const isForm = typeof FormData !== "undefined" && body instanceof FormData;
  const isBinary =
    typeof Blob !== "undefined" && (body instanceof Blob || body instanceof URLSearchParams || body instanceof ArrayBuffer || ArrayBuffer.isView(body));
  if (body && typeof body === "object" && !isForm && !isBinary) {
    if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    body = JSON.stringify(body);
  }
  if (typeof window !== "undefined" && !headers.has("Authorization")) {
    const token = window.localStorage.getItem(TOKEN_KEY);
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }
  return fetch(suitePath(path), {
    ...options,
    headers,
    body,
    credentials: "include",
    cache: options.cache || "no-store",
  });
}

export async function readSuite(response) {
  if (response.status === 204) return null;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const proxyDown =
      response.status === 503 &&
      /^Agentic API is not running on port \d+\.$/.test(data.error || "");
    const error = new Error(proxyDown ? SUITE_DOWN : suiteDetail(data, response.statusText || "Request failed"));
    error.status = response.status;
    error.body = data;
    throw error;
  }
  return data;
}

export async function suiteJson(path, options) {
  const response = await suiteFetch(path, options);
  return readSuite(response);
}

export async function consumeSse(response, onEvent) {
  if (!response.ok) {
    await readSuite(response);
    return;
  }
  if (!response.body) throw new Error("The server returned no stream.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const flush = (chunk) => {
    const line = chunk.split("\n").find((item) => item.startsWith("data: "));
    if (!line) return;
    try {
      onEvent(JSON.parse(line.slice(6)));
    } catch {
      // Incomplete SSE frame.
    }
  };
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() || "";
    chunks.forEach(flush);
    if (done) break;
  }
  if (buffer.trim()) flush(buffer);
}
