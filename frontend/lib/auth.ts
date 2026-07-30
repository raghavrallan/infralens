import { api } from "./api";

const TOKEN_KEY = "infralens_auth_token";
const USER_KEY = "infralens_auth_user";

export type AuthUser = {
  id?: string;
  username: string;
  name: string;
  email?: string;
  role?: string;
  role_label?: string;
  display_role?: string;
  org_role?: string | null;
  is_active?: boolean;
  org_ids?: string[];
  primary_org_id?: string;
};

export type AuthSession = {
  token: string;
  token_type?: string;
  user: AuthUser;
  expires_at?: number;
};

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function getStoredUser(): AuthUser | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AuthUser;
  } catch {
    return null;
  }
}

export function saveSession(session: AuthSession): void {
  window.localStorage.setItem(TOKEN_KEY, session.token);
  window.localStorage.setItem(USER_KEY, JSON.stringify(session.user));
}

export function clearSession(): void {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
  window.localStorage.removeItem("projectId");
}

export function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function login(username: string, password: string): Promise<AuthSession> {
  // Clear previous user's project selection so isolation is not broken by localStorage.
  window.localStorage.removeItem("projectId");
  const session = await api<AuthSession>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  saveSession(session);
  return session;
}

export async function fetchCurrentUser(): Promise<AuthUser | null> {
  const token = getToken();
  if (!token) return null;
  try {
    const body = await api<{ user: AuthUser }>("/api/auth/me");
    window.localStorage.setItem(USER_KEY, JSON.stringify(body.user));
    return body.user;
  } catch (error) {
    // Only drop the session on real auth failures — not network/CORS blips.
    const message = error instanceof Error ? error.message : "";
    if (message === "Not authenticated" || /not authenticated|401/i.test(message)) {
      clearSession();
    }
    return null;
  }
}

export function logout(): void {
  clearSession();
  window.location.href = "/login";
}
