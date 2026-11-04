"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useFeedback } from "@/components/Feedback";
import PasswordField from "@/components/PasswordField";

const field = "mt-1.5 h-12 w-full rounded-2xl border border-line bg-white px-3.5 text-sm font-normal outline-none focus:border-brand";
const passwordField = "h-12 w-full rounded-2xl border border-line bg-white px-3.5 pr-11 text-sm font-normal outline-none focus:border-brand";

const STEPS = [
  ["Account", "Email or username, then your password."],
  ["Code", "A 6-digit code is emailed before the session starts."],
  ["Notice", "After you sign in, we email where it happened."],
];

function digitsOnly(value) {
  return String(value || "").replace(/\D/g, "").slice(0, 6);
}

export default function LoginPage() {
  const router = useRouter();
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [challengeId, setChallengeId] = useState("");
  const [emailHint, setEmailHint] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const { notify, startBusy, stopBusy } = useFeedback();

  useEffect(() => {
    document.title = challengeId ? "Check your email · Infralens" : "Sign in · Infralens";
  }, [challengeId]);

  async function onSubmit(event) {
    event.preventDefault();
    setError("");
    setLoading(true);
    startBusy(challengeId ? "Checking the code…" : "Sending a sign-in code…");
    const res = await fetch(challengeId ? "/api/login/otp" : "/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(challengeId ? { challengeId, code } : { login, password }),
    });
    const body = await res.json().catch(() => ({}));
    stopBusy();
    setLoading(false);
    if (!res.ok) {
      const message = body.message || "Sign-in failed.";
      setError(message);
      notify(message, "error");
      if (res.status === 410) {
        setChallengeId("");
        setCode("");
      }
      return;
    }
    if (body.step === "otp") {
      setChallengeId(body.challengeId);
      setEmailHint(body.emailHint || login);
      setCode("");
      notify("Sign-in code sent.", "ok");
      return;
    }
    router.push("/dashboard");
    router.refresh();
  }

  async function resend() {
    setError("");
    setLoading(true);
    const res = await fetch("/api/login/otp", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ challengeId, resend: true }),
    });
    const body = await res.json().catch(() => ({}));
    setLoading(false);
    if (!res.ok) {
      const message = body.message || "Could not send another code.";
      setError(message);
      notify(message, "error");
      return;
    }
    notify("A new code is on the way.", "ok");
  }

  const step = challengeId ? 2 : 1;
  const accountLabel = login.includes("@") ? "Email" : login.trim() ? "Username" : "Email or username";

  return (
    <main className="min-h-screen bg-canvas lg:grid lg:grid-cols-[minmax(320px,0.9fr)_minmax(420px,1.1fr)]">
      <section className="relative hidden flex-col justify-between overflow-hidden bg-ink px-10 py-10 text-white lg:flex xl:px-14">
        <div className="absolute inset-x-0 top-0 h-1 bg-brand" />
        <div className="flex items-center gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-brand text-sm font-bold">IF</span>
          <span className="text-lg font-semibold tracking-tight">Infralens</span>
        </div>
        <div className="max-w-md">
          <p className="text-sm font-semibold uppercase tracking-[0.16em] text-white/50">Organization sign-in</p>
          <h2 className="mt-4 text-4xl font-semibold leading-tight tracking-tight">Your estate stays with your organization.</h2>
          <ol className="mt-10 space-y-5">
            {STEPS.map(([title, detail], index) => {
              const done = step === 2 && index === 0;
              const active = index + 1 === step;
              return (
                <li key={title} className="flex gap-4">
                  <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-full text-sm font-semibold ${active ? "bg-brand text-white" : done ? "bg-white/20 text-white" : "bg-white/10 text-white/50"}`}>{index + 1}</span>
                  <span>
                    <span className="block text-sm font-semibold">{title}</span>
                    <span className="mt-0.5 block text-sm leading-5 text-white/60">{detail}</span>
                  </span>
                </li>
              );
            })}
          </ol>
        </div>
        <p className="text-sm text-white/50">Projects, connections, and members are not shared across organizations.</p>
      </section>

      <section className="flex min-h-screen flex-col px-5 py-8 sm:px-8 lg:justify-center lg:bg-white lg:px-16 xl:px-24">
        <div className="mb-10 flex items-center gap-2.5 lg:hidden">
          <span className="grid h-9 w-9 place-items-center rounded-xl bg-brand text-sm font-bold text-white">IF</span>
          <span className="font-semibold">Infralens</span>
        </div>
        <form onSubmit={onSubmit} className="mx-auto w-full max-w-[420px]">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-brand">Step {step} of 2</p>
          <h1 className="mt-3 text-[32px] font-semibold leading-none tracking-tight">{challengeId ? "Check your email" : "Sign in"}</h1>
          <p className="mt-3 text-sm leading-6 text-muted">
            {challengeId
              ? `Enter the code sent to ${emailHint}. It expires in 10 minutes.`
              : "Use the email or username for your organization account."}
          </p>

          {!challengeId && (
            <div className="mt-8 space-y-4">
              <label className="block text-xs font-semibold text-muted">
                {accountLabel}
                <input
                  type="text"
                  autoFocus
                  autoComplete="username"
                  autoCapitalize="none"
                  spellCheck={false}
                  value={login}
                  onChange={(event) => setLogin(event.target.value)}
                  className={field}
                />
              </label>
              <PasswordField label="Password" value={password} onChange={(event) => setPassword(event.target.value)} inputClassName={passwordField} />
            </div>
          )}

          {challengeId && (
            <div className="mt-8">
              <label htmlFor="sign-in-code" className="text-xs font-semibold text-muted">Code</label>
              <CodeBoxes id="sign-in-code" value={code} onChange={setCode} />
              <p className="mt-3 text-xs leading-5 text-muted">Paste the whole code. Spaces from the email are ignored.</p>
            </div>
          )}

          {error && <p className="mt-4 rounded-2xl bg-[#fdecec] px-3 py-2 text-sm text-danger">{error}</p>}

          <button type="submit" disabled={loading} className="mt-6 h-12 w-full rounded-2xl bg-brand text-sm font-semibold text-white disabled:opacity-60">
            {loading ? "Please wait…" : challengeId ? "Sign in" : "Continue"}
          </button>

          {challengeId ? (
            <div className="mt-5 flex items-center justify-between text-sm">
              <button type="button" className="font-semibold text-brand disabled:opacity-60" disabled={loading} onClick={() => void resend()}>Send a new code</button>
              <button type="button" className="text-muted" onClick={() => { setChallengeId(""); setCode(""); setError(""); }}>Different account</button>
            </div>
          ) : (
            <p className="mt-5 text-sm text-muted">
              New client? <Link href="/signup" className="font-semibold text-brand">Create an organization</Link>
            </p>
          )}
        </form>
      </section>
    </main>
  );
}

function CodeBoxes({ id, value, onChange }) {
  const cells = Array.from({ length: 6 }, (_, index) => value[index] || "");
  return (
    <div className="relative mt-1.5 h-14">
      <div className="pointer-events-none absolute inset-0 flex gap-2" aria-hidden="true">
        {cells.map((digit, index) => (
          <span
            key={index}
            className={`grid flex-1 place-items-center rounded-2xl border text-xl font-semibold ${digit ? "border-brand bg-[#fff6f1] text-brand-deep" : "border-line bg-white text-ink"} ${!digit && index === value.length ? "border-brand" : ""}`}
          >
            {digit}
          </span>
        ))}
      </div>
      <input
        id={id}
        autoFocus
        inputMode="numeric"
        autoComplete="one-time-code"
        pattern="[0-9]{6}"
        value={value}
        aria-label="6-digit sign-in code"
        onPaste={(event) => {
          const pasted = event.clipboardData?.getData("text") ?? "";
          event.preventDefault();
          onChange(digitsOnly(pasted));
        }}
        onChange={(event) => onChange(digitsOnly(event.target.value))}
        className="absolute inset-0 h-full w-full cursor-text rounded-2xl bg-transparent text-transparent caret-transparent outline-none"
      />
    </div>
  );
}
