"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useFeedback } from "@/components/Feedback";
import PasswordField from "@/components/PasswordField";

export default function SignupPage() {
  const router = useRouter();
  const [form, setForm] = useState({ name: "", orgName: "", email: "", password: "" });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const { notify, startBusy, stopBusy } = useFeedback();

  useEffect(() => {
    document.title = "Create organization · Infralens";
  }, []);

  function set(key, value) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function onSubmit(event) {
    event.preventDefault();
    setError("");
    setLoading(true);
    startBusy("Creating the organization…");
    const res = await fetch("/api/signup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(form),
    });
    const body = await res.json().catch(() => ({}));
    stopBusy();
    setLoading(false);
    if (!res.ok) {
      const message = body.message || "Could not create the organization.";
      setError(message);
      notify(message, "error");
      return;
    }
    router.push("/settings");
    router.refresh();
  }

  return (
    <main className="grid min-h-screen place-items-center bg-canvas px-4">
      <form onSubmit={onSubmit} className="w-full max-w-md rounded-3xl border border-line bg-white p-6">
        <div className="text-sm font-bold text-brand">Infralens</div>
        <h1 className="mt-2 text-2xl font-semibold">Create an organization</h1>
        <p className="mt-2 text-sm text-muted">This is a new client. Its Azure connection, projects, and members stay separate from every other organization.</p>
        {[
          ["name", "Your name", "text"],
          ["orgName", "Organization", "text"],
          ["email", "Email", "email"],
        ].map(([key, label, type]) => (
          <label key={key} className="mt-3 block text-xs font-semibold text-muted">
            {label}
            <input type={type} value={form[key]} onChange={(event) => set(key, event.target.value)} className="mt-1 h-11 w-full rounded-2xl border border-line px-3 text-sm outline-none focus:border-brand" />
          </label>
        ))}
        <PasswordField label="Password" autoComplete="new-password" value={form.password} onChange={(event) => set("password", event.target.value)} className="mt-3" />
        {error && <p className="mt-3 text-sm text-danger">{error}</p>}
        <button type="submit" disabled={loading} className="mt-5 h-11 w-full rounded-2xl bg-brand text-sm font-semibold text-white disabled:opacity-60">
          {loading ? "Creating…" : "Create organization"}
        </button>
        <p className="mt-4 text-sm text-muted">
          Already added by an admin? <Link href="/login" className="font-semibold text-brand">Sign in</Link>
        </p>
      </form>
    </main>
  );
}
