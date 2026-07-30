"use client";

import { FormEvent, useEffect, useState } from "react";
import { getStoredUser, getToken, login as doLogin } from "../lib/auth";

export function LoginPage() {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    if (getToken() && getStoredUser()) {
      // AuthGate on destination will send incomplete users to /onboarding.
      window.location.replace("/dashboard");
      return;
    }
    setChecking(false);
  }, []);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      await doLogin(username.trim(), password);
      // Landing on dashboard; AuthGate redirects to /onboarding when needed.
      window.location.href = "/dashboard";
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed");
      setBusy(false);
    }
  }

  if (checking) {
    return (
      <div className="login-screen" aria-busy="true">
        <div className="login-check">
          <span className="login-mark">IL</span>
          <span>Loading InfraLens</span>
        </div>
      </div>
    );
  }

  return (
    <div className="login-screen">
      <div className="login-atmosphere" aria-hidden="true" />
      <main className="login-panel">
        <header className="login-brand">
          <span className="login-mark">IL</span>
          <div>
            <h1>InfraLens</h1>
            <p>Sign in to continue</p>
          </div>
        </header>

        <form className="login-form" onSubmit={onSubmit}>
          <label className="login-field">
            <span>Username</span>
            <input
              autoComplete="username"
              autoFocus
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </label>
          <label className="login-field">
            <span>Password</span>
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
          {error ? <p className="login-error" role="alert">{error}</p> : null}
          <button className="login-submit" type="submit" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </main>
    </div>
  );
}
