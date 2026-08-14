"use client";

import { FormEvent, useEffect, useState } from "react";
import Image from "next/image";
import loginImage from "../public/assets/images/login.png";
import { api } from "../lib/api";
import { saveSession, type AuthSession } from "../lib/auth";
import { ThemeToggle } from "./theme-toggle";

type Peek = {
  email: string;
  org_name: string;
  invited_role: string;
};

const ROLE_LABELS: Record<string, string> = {
  super_admin: "Super Admin",
  org_admin: "Org Admin",
  devops_lead: "DevOps Lead",
  developer: "Developer",
  viewer: "Viewer",
};

function roleLabel(role: string) {
  return ROLE_LABELS[role] || role.replace(/_/g, " ");
}

export function AcceptInvitePage() {
  const [token, setToken] = useState("");
  const [peek, setPeek] = useState<Peek | null>(null);
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [username, setUsername] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const t = params.get("token") || "";
    setToken(t);
    if (!t) {
      setMessage("Missing invite token.");
      setLoading(false);
      return;
    }
    void api<Peek>(`/api/invites/peek?token=${encodeURIComponent(t)}`)
      .then((data) => {
        setPeek(data);
        const seed = data.email.split("@")[0] || "";
        setUsername(seed);
        setDisplayName(seed);
      })
      .catch((error) => {
        setMessage(error instanceof Error ? error.message : "Invalid invite");
      })
      .finally(() => setLoading(false));
  }, []);

  const accept = async (event: FormEvent) => {
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
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <div className="login-screen" aria-busy="true">
        <ThemeToggle variant="floating" />
        <div className="login-check">
          <span className="login-mark">IL</span>
          <span>Loading invite…</span>
        </div>
      </div>
    );
  }

  return (
    <div className="login-screen">
      <ThemeToggle variant="floating" />
      <div className="login-layout invite-layout">
        <div className="login-left" aria-hidden="true">
          <div className="login-brand">
            <span className="login-mark">IL</span>
            <span className="login-brand-name">InfraLens</span>
          </div>

          <h2 className="login-left-title">You&apos;re invited</h2>
          <p className="login-left-sub">
            Create your account and join your team on InfraLens.
          </p>

          <div className="login-illo-container invite-illo">
            <Image
              src={loginImage}
              alt=""
              style={{ width: "100%", height: "auto", objectFit: "contain" }}
              priority
            />
          </div>
        </div>

        <div className="login-right">
          <main className="login-panel invite-panel">
            <div className="login-panel-header">
              <p className="invite-eyebrow">Accept invitation</p>
              <h1>Join your org</h1>
              <p>Set your profile and password to get started.</p>
            </div>

            {peek ? (
              <div className="invite-meta" aria-label="Invitation details">
                <div className="invite-meta-row">
                  <span className="invite-meta-label">Organization</span>
                  <span className="invite-meta-value">{peek.org_name}</span>
                </div>
                <div className="invite-meta-row">
                  <span className="invite-meta-label">Role</span>
                  <span className="invite-role">{roleLabel(peek.invited_role)}</span>
                </div>
                <div className="invite-meta-row">
                  <span className="invite-meta-label">Email</span>
                  <span className="invite-meta-value invite-meta-email">{peek.email}</span>
                </div>
              </div>
            ) : null}

            {peek ? (
              <form className="login-form" onSubmit={(e) => void accept(e)}>
                <div className="login-field">
                  <label htmlFor="invite-display-name">Display name</label>
                  <div className="login-input-wrap">
                    <svg
                      className="login-input-icon"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      aria-hidden="true"
                    >
                      <circle cx="12" cy="8" r="4" />
                      <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" />
                    </svg>
                    <input
                      id="invite-display-name"
                      autoComplete="name"
                      autoFocus
                      value={displayName}
                      onChange={(e) => setDisplayName(e.target.value)}
                      required
                    />
                  </div>
                </div>

                <div className="login-field">
                  <label htmlFor="invite-username">Username</label>
                  <div className="login-input-wrap">
                    <svg
                      className="login-input-icon"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      aria-hidden="true"
                    >
                      <path d="M4 7h16M4 12h10M4 17h14" />
                    </svg>
                    <input
                      id="invite-username"
                      autoComplete="username"
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      required
                    />
                  </div>
                </div>

                <div className="login-field">
                  <label htmlFor="invite-password">Password</label>
                  <div className="login-input-wrap">
                    <svg
                      className="login-input-icon"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      aria-hidden="true"
                    >
                      <rect x="3" y="11" width="18" height="11" rx="2" />
                      <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                    </svg>
                    <input
                      id="invite-password"
                      type="password"
                      autoComplete="new-password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      minLength={6}
                      required
                      placeholder="At least 6 characters"
                    />
                  </div>
                </div>

                {message ? (
                  <p className="login-error" role="alert">
                    {message}
                  </p>
                ) : null}

                <button className="login-submit" type="submit" disabled={busy}>
                  {busy ? (
                    "Creating account…"
                  ) : (
                    <>
                      Accept &amp; sign in
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
                        <path d="M5 12h14M12 5l7 7-7 7" />
                      </svg>
                    </>
                  )}
                </button>
              </form>
            ) : (
              <div className="invite-invalid">
                <p className="login-error" role="alert">
                  {message || "This invite link is invalid or has expired."}
                </p>
                <a className="invite-back-link" href="/login">
                  Back to sign in
                </a>
              </div>
            )}
          </main>
        </div>
      </div>
    </div>
  );
}
