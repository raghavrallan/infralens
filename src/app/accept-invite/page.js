"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

const field = "mt-1 h-11 w-full rounded-2xl border border-line px-3 text-sm outline-none focus:border-brand";

export default function AcceptInvitePage() {
  const [token, setToken] = useState("");
  const [peek, setPeek] = useState(null);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [message, setMessage] = useState("");
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    document.title = "Set your password · Infralens";
    const inviteToken = new URLSearchParams(window.location.search).get("token") || "";
    const timer = window.setTimeout(() => setToken(inviteToken), 0);
    if (!inviteToken) {
      setMessage("This invite link is missing its token.");
      setLoading(false);
      return () => window.clearTimeout(timer);
    }
    let cancel = false;
    fetch(`/api/invites/peek?token=${encodeURIComponent(inviteToken)}`)
      .then(async (res) => {
        const body = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(body.message || "This invite link is not valid.");
        return body;
      })
      .then((data) => {
        if (cancel) return;
        setPeek(data);
        setName(data.name || "");
      })
      .catch((error) => {
        if (!cancel) setMessage(error.message);
      })
      .finally(() => {
        if (!cancel) setLoading(false);
      });
    return () => {
      cancel = true;
      window.clearTimeout(timer);
    };
  }, []);

  async function accept(event) {
    event.preventDefault();
    if (password !== confirm) {
      setMessage("Passwords do not match.");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const res = await fetch("/api/invites/accept", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, name, password }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.message || "Could not accept this invite.");
      setDone(true);
    } catch (error) {
      setMessage(error.message);
      setBusy(false);
    }
  }

  return (
    <main className="grid min-h-screen place-items-center bg-canvas px-4 py-10">
      <div className="w-full max-w-md rounded-3xl border border-line bg-white p-6">
        <div className="text-sm font-bold text-brand">Infralens</div>
        <h1 className="mt-2 text-2xl font-semibold">Set your password</h1>
        <p className="mt-2 text-sm text-muted">This invite lasts 15 minutes. You choose the password. Infralens does not create one for you.</p>
        {loading && <p className="mt-4 text-sm text-muted">Checking the invite…</p>}
        {peek && !done && (
          <>
            <dl className="mt-4 space-y-1 text-sm">
              <div className="flex justify-between gap-3"><dt className="text-muted">Organization</dt><dd className="font-semibold">{peek.orgName}</dd></div>
              {peek.projectName && <div className="flex justify-between gap-3"><dt className="text-muted">Project</dt><dd>{peek.projectName}</dd></div>}
              <div className="flex justify-between gap-3"><dt className="text-muted">Role</dt><dd>{peek.role}</dd></div>
              <div className="flex justify-between gap-3"><dt className="text-muted">Email</dt><dd>{peek.email}</dd></div>
            </dl>
            <form className="mt-4" onSubmit={accept}>
              <label className="block text-xs font-semibold text-muted">Your name<input className={field} value={name} onChange={(event) => setName(event.target.value)} required /></label>
              <label className="mt-3 block text-xs font-semibold text-muted">{peek.accountExists ? "Your password" : "Choose a password"}<input type="password" minLength={8} autoComplete="new-password" className={field} value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
              <label className="mt-3 block text-xs font-semibold text-muted">Confirm password<input type="password" minLength={8} autoComplete="new-password" className={field} value={confirm} onChange={(event) => setConfirm(event.target.value)} required /></label>
              {peek.accountExists && <p className="mt-3 text-sm text-muted">This email already has an Infralens password. Enter it to join. It will not be replaced.</p>}
              {message && <p className="mt-3 text-sm text-danger">{message}</p>}
              <button type="submit" disabled={busy} className="mt-5 h-11 w-full rounded-2xl bg-brand text-sm font-semibold text-white disabled:opacity-60">
                {busy ? "Saving…" : "Save password and join"}
              </button>
            </form>
          </>
        )}
        {!loading && !peek && <p className="mt-4 text-sm text-danger">{message || "This invite link is invalid or has expired."}</p>}
        {done && <p className="mt-4 text-sm text-ink">Your password is set. Sign in with {peek?.email}.</p>}
        <p className="mt-4 text-sm text-muted">
          <Link href="/login" className="font-semibold text-brand">Sign in</Link>
        </p>
      </div>
    </main>
  );
}
