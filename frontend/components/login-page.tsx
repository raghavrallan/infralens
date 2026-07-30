"use client";

import { FormEvent, useEffect, useState } from "react";
import Image from "next/image";
import loginImage from "../assets/images/login.png";
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
          <span>Loading InfraLens…</span>
        </div>
      </div>
    );
  }

  return (
    <div>

    <div className="login-screen">

      <div className="login-layout">

        {/* ══ LEFT: Branding + Illustration ══ */}
        <div className="login-left" aria-hidden="true">
          {/* Brand */}
          <div className="login-brand">
            <span className="login-mark">IL</span>
            <span className="login-brand-name">InfraLens</span>
          </div>

          <h2 className="login-left-title">Welcome back!</h2>
          <p className="login-left-sub">Sign in to continue to your account</p>

          {/* Browser window illustration image */}
          <div className="login-illo-container" style={{ position: 'relative', width: '640px', marginTop: '40px', left: '-10px' }}>
            <Image 
              src={loginImage} 
              alt="Login Dashboard Illustration" 
              style={{ width: '100%', height: 'auto', objectFit: 'contain' }}
              priority 
            />
          </div>
        </div>

        {/* ══ RIGHT: Sign-in Card ══ */}
        <div className="login-right">
          <main className="login-panel">
            <div className="login-panel-header">
              <h1>Sign in</h1>
              <p>Enter your credentials to access your account</p>
            </div>

            <form className="login-form" onSubmit={onSubmit}>
              {/* Username */}
              <div className="login-field">
                <label htmlFor="login-username">Username</label>
                <div className="login-input-wrap">
                  <svg className="login-input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                    <circle cx="12" cy="8" r="4"/>
                    <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/>
                  </svg>
                  <input
                    id="login-username"
                    autoComplete="username"
                    autoFocus
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    required
                  />
                </div>
              </div>

              {/* Password */}
              <div className="login-field">
                <label htmlFor="login-password">Password</label>
                <div className="login-input-wrap">
                  <svg className="login-input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                    <rect x="3" y="11" width="18" height="11" rx="2"/>
                    <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
                  </svg>
                  <input
                    id="login-password"
                    type="password"
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                  />
                </div>
              </div>
              {error ? <p className="login-error" role="alert">{error}</p> : null}
              {/* Submit */}
              <button className="login-submit" type="submit" disabled={busy}>
                {busy ? "Signing in…" : (
                  <>
                    Sign in
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                      <path d="M5 12h14M12 5l7 7-7 7"/>
                    </svg>
                  </>
                )}
              </button>
            </form>
          </main>
        </div>

      </div>
    </div>
    </div>
  );
}
