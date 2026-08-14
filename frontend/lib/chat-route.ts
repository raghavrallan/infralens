const CHAT_ID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function asChatId(value: string | null | undefined): string | null {
  const id = (value || "").trim();
  return CHAT_ID_RE.test(id) ? id : null;
}

export function readChatIdFromUrl(): string | null {
  if (typeof window === "undefined") return null;
  const fromQuery = asChatId(new URLSearchParams(window.location.search).get("chat"));
  if (fromQuery) return fromQuery;
  const path = window.location.pathname.replace(/\/+$/, "") || "/";
  const match = path.match(/^\/c\/([^/]+)$/);
  return asChatId(match?.[1] ? decodeURIComponent(match[1]) : null);
}

export function chatHref(chatId: string | null): string {
  return chatId ? `/?chat=${encodeURIComponent(chatId)}` : "/";
}

export function syncChatUrl(chatId: string | null, mode: "push" | "replace" = "push") {
  if (typeof window === "undefined") return;
  const next = new URL(chatHref(chatId), window.location.origin);
  const currentPath = window.location.pathname.replace(/\/+$/, "") || "/";
  const nextPath = next.pathname.replace(/\/+$/, "") || "/";
  if (currentPath === nextPath && window.location.search === next.search) return;
  if (mode === "replace") {
    window.history.replaceState({ chatId }, "", next.pathname + next.search);
  } else {
    window.history.pushState({ chatId }, "", next.pathname + next.search);
  }
}
