import type { JsonObject, StreamEvent } from "./types";

const TOKEN_KEY = "infralens_auth_token";
const USER_KEY = "infralens_auth_user";

/**
 * In local `next dev`, point at the FastAPI origin so /api calls do not go
 * through Next trailingSlash/rewrites (those were 404ing as /api/projects/).
 * In production static export served by FastAPI, keep relative /api paths.
 */
export function apiUrl(path: string): string {
  const base = (process.env.NEXT_PUBLIC_API_BASE || "").replace(/\/$/, "");
  if (!path.startsWith("/")) return `${base}/${path}`;
  return `${base}${path}`;
}

function readAuthHeaders(): Record<string, string> {
  if (typeof window === "undefined") return {};
  const token = window.localStorage.getItem(TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function clearAuthStorage(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
}

export async function api<T>(url: string, options?: RequestInit): Promise<T> {
  const isForm = typeof FormData !== "undefined" && options?.body instanceof FormData;
  let response: Response;
  try {
    response = await fetch(apiUrl(url), {
      ...options,
      headers: {
        ...(options?.body && !isForm ? { "Content-Type": "application/json" } : {}),
        ...readAuthHeaders(),
        ...options?.headers,
      },
    });
  } catch (error) {
    if (
      (error instanceof DOMException || error instanceof Error) &&
      error.name === "AbortError"
    ) {
      throw error;
    }
    throw new Error(
      "Cannot reach the API. Is the backend running on NEXT_PUBLIC_API_BASE?",
    );
  }
  if (response.status === 401 && !url.includes("/api/auth/login")) {
    clearAuthStorage();
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      window.location.replace("/login");
    }
    throw new Error("Not authenticated");
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: string };
      detail = body.detail || detail;
    } catch {
      // Keep the HTTP status when the response is not JSON.
    }
    throw new Error(detail);
  }
  return (response.status === 204 ? null : await response.json()) as T;
}

export class StreamIdleError extends Error {
  constructor(message = "The chat stream stalled. Try again.") {
    super(message);
    this.name = "StreamIdleError";
  }
}

function dispatchSseChunk(chunk: string, onEvent: (event: StreamEvent) => void) {
  const line = chunk.split("\n").find((item) => item.startsWith("data: "));
  if (!line) return;
  try {
    onEvent(JSON.parse(line.slice(6)) as StreamEvent);
  } catch {
    // Ignore incomplete or non-JSON server events.
  }
}

function readWithIdle(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  idleMs: number | undefined,
  signal: AbortSignal | undefined,
): Promise<ReadableStreamReadResult<Uint8Array>> {
  const read = reader.read();
  if (!idleMs && !signal) return read;
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = idleMs
      ? globalThis.setTimeout(() => {
          if (settled) return;
          settled = true;
          reject(new StreamIdleError());
        }, idleMs)
      : 0;
    const onAbort = () => {
      if (settled) return;
      settled = true;
      if (timer) globalThis.clearTimeout(timer);
      const reason = signal?.reason;
      reject(reason instanceof Error ? reason : new DOMException("Aborted", "AbortError"));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
    read.then(
      (value) => {
        if (settled) return;
        settled = true;
        if (timer) globalThis.clearTimeout(timer);
        signal?.removeEventListener("abort", onAbort);
        resolve(value);
      },
      (error) => {
        if (settled) return;
        settled = true;
        if (timer) globalThis.clearTimeout(timer);
        signal?.removeEventListener("abort", onAbort);
        reject(error);
      },
    );
  });
}

export async function consumeSse(
  response: Response,
  onEvent: (event: StreamEvent) => void,
  options?: { idleMs?: number; signal?: AbortSignal; onIdle?: () => void },
): Promise<void> {
  if (!response.body) throw new Error("The server returned no stream.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      if (options?.signal?.aborted) {
        const reason = options.signal.reason;
        throw reason instanceof Error ? reason : new DOMException("Aborted", "AbortError");
      }
      try {
        const { done, value } = await readWithIdle(reader, options?.idleMs, options?.signal);
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        const chunks = buffer.split("\n\n");
        buffer = chunks.pop() || "";
        for (const chunk of chunks) dispatchSseChunk(chunk, onEvent);
        if (done) break;
      } catch (error) {
        if (error instanceof StreamIdleError) options?.onIdle?.();
        throw error;
      }
    }
    if (buffer.trim()) dispatchSseChunk(buffer, onEvent);
  } finally {
    try {
      await reader.cancel();
    } catch {
      // Stream already closed.
    }
  }
}

export function jsonBody(body: JsonObject): RequestInit {
  return { method: "POST", body: JSON.stringify(body) };
}
