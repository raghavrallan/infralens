"use client";

import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { saveSession, type AuthSession } from "../lib/auth";

type Peek = {
  email: string;
  org_name: string;
  invited_role: string;
};

export function AcceptInvitePage() {
  const [token, setToken] = useState("");
  const [peek, setPeek] = useState<Peek | null>(null);
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [username, setUsername] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const t = params.get("token") || "";
    setToken(t);
    if (!t) {
      setMessage("Missing invite token.");
      return;
    }
    void api<Peek>(`/api/invites/peek?token=${encodeURIComponent(t)}`)
      .then((data) => {
        setPeek(data);
        setUsername(data.email.split("@")[0] || "");
        setDisplayName(data.email.split("@")[0] || "");
      })
      .catch((error) => {
        setMessage(error instanceof Error ? error.message : "Invalid invite");
      });
  }, []);

  const accept = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      const result = await api<{
        session?: AuthSession;
        needs_onboarding?: boolean;
      }>("/api/invites/accept", {
        method: "POST",
        body: JSON.stringify({
          token,
          password,
          display_name: displayName,
          username: username || undefined,
        }),
      });
      if (result.session) {
        saveSession(result.session);
        window.localStorage.removeItem("projectId");
        window.localStorage.removeItem("onboarding_skipped");
        if (result.session.user?.id) {
          window.localStorage.removeItem(`onboarding_skipped:${result.session.user.id}`);
        }
      }
      window.location.href = result.needs_onboarding ? "/onboarding" : "/dashboard";
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not accept invite");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page login-page">
      <main className="login-card">
        <h1>Accept invite</h1>
        {peek ? (
          <p>
            Join <strong>{peek.org_name}</strong> as <strong>{peek.invited_role}</strong> (
            {peek.email})
          </p>
        ) : (
          <p className="empty-note">Loading invite…</p>
        )}
        <form onSubmit={(e) => void accept(e)}>
          <label>
            Display name
            <input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              required
            />
          </label>
          <label>
            Username
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </label>
          <label>
            Password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={6}
              required
            />
          </label>
          <button type="submit" className="modal-btn primary" disabled={busy || !peek}>
            {busy ? "Creating account…" : "Accept & sign in"}
          </button>
        </form>
        {message && <div className="form-msg">{message}</div>}
      </main>
    </div>
  );
}
