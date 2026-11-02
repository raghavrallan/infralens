"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useFeedback } from "@/components/Feedback";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const { notify, startBusy, stopBusy } = useFeedback();

  useEffect(() => {
    document.title = "Sign in · Infralens";
  }, []);

  async function onSubmit(event) {
    event.preventDefault();
    setError("");
    setLoading(true);
    startBusy("Signing in…");
    const res = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const body = await res.json().catch(() => ({}));
    stopBusy();
    setLoading(false);
    if (!res.ok) {
      const message = body.message || "Sign-in failed.";
      setError(message);
      notify(message, "error");
      return;
    }
    router.push("/dashboard");
    router.refresh();
  }

  return (
    <main className="grid min-h-screen place-items-center bg-canvas px-4">
      <form onSubmit={onSubmit} className="w-full max-w-md rounded-3xl border border-line bg-white p-6">
        <div className="text-sm font-bold text-brand">Infralens</div>
        <h1 className="mt-2 text-2xl font-semibold">Sign in</h1>
        <p className="mt-2 text-sm text-muted">Use the account an organization owner created for you. There is no shared demo tenant.</p>
        <label className="mt-5 block text-xs font-semibold text-muted">
          Email
          <input type="email" autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} className="mt-1 h-11 w-full rounded-2xl border border-line px-3 text-sm outline-none focus:border-brand" />
        </label>
        <label className="mt-3 block text-xs font-semibold text-muted">
          Password
          <input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} className="mt-1 h-11 w-full rounded-2xl border border-line px-3 text-sm outline-none focus:border-brand" />
        </label>
        {error && <p className="mt-3 text-sm text-danger">{error}</p>}
        <button type="submit" disabled={loading} className="mt-5 h-11 w-full rounded-2xl bg-brand text-sm font-semibold text-white disabled:opacity-60">
          {loading ? "Signing in…" : "Continue"}
        </button>
        <p className="mt-4 text-sm text-muted">
          New client? <Link href="/signup" className="font-semibold text-brand">Create an organization</Link>
        </p>
      </form>
    </main>
  );
}
