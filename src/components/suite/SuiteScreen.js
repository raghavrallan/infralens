"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { clearSuiteSession, rememberSuiteUser, SUITE_DOWN, suiteFetch, suiteJson } from "@/lib/suite";

const SuiteContext = createContext(null);

export function useSuite() {
  return useContext(SuiteContext);
}

export const fieldClass = "mt-1 h-10 w-full rounded-2xl border border-line bg-white px-3 text-sm outline-none focus:border-brand";
export const primaryBtn = "inline-flex h-10 items-center justify-center rounded-2xl bg-brand px-4 text-sm font-semibold text-white disabled:opacity-60";
export const ghostBtn = "inline-flex h-10 items-center justify-center rounded-2xl border border-line bg-white px-3 text-sm font-semibold text-ink disabled:opacity-60";
export const dangerBtn = "inline-flex h-10 items-center justify-center rounded-2xl border border-red-200 bg-white px-3 text-sm font-semibold text-danger disabled:opacity-60";

export function SuiteDown() {
  return <p className="text-sm text-muted">{SUITE_DOWN}</p>;
}

export function SuiteGate({ children }) {
  const [phase, setPhase] = useState("loading");
  const [user, setUser] = useState(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let cancel = false;
    (async () => {
      let health;
      try {
        health = await suiteFetch("/api/health");
      } catch {
        if (!cancel) setPhase("down");
        return;
      }
      if (cancel) return;
      if (health.status === 503) {
        setPhase("down");
        return;
      }
      const me = await suiteFetch("/api/auth/me");
      if (cancel) return;
      if (me.status === 401) {
        clearSuiteSession();
        setUser(null);
        setPhase("signedOut");
        return;
      }
      if (me.status === 503) {
        setPhase("down");
        return;
      }
      const body = await me.json().catch(() => ({}));
      if (!me.ok) {
        setPhase("signedOut");
        return;
      }
      rememberSuiteUser(body.user);
      setUser(body.user || null);
      setPhase("ready");
    })();
    return () => {
      cancel = true;
    };
  }, [nonce]);

  if (phase === "loading") return <p className="text-sm text-muted">Checking the agentic API…</p>;
  if (phase === "down") return <SuiteDown />;
  if (phase === "signedOut") {
    return <p className="text-sm text-muted">Sign in with your organization account. The agentic pages use that same login.</p>;
  }
  return <SuiteContext.Provider value={{ user, reload: () => setNonce((value) => value + 1) }}>{children}</SuiteContext.Provider>;
}

export function useSuiteProject() {
  const [projects, setProjects] = useState([]);
  const [projectId, setProjectId] = useState("");
  const [error, setError] = useState("");
  const [down, setDown] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancel = false;
    suiteJson("/api/projects")
      .then((list) => {
        if (cancel) return;
        const items = Array.isArray(list) ? list : [];
        setProjects(items);
        const saved = window.localStorage.getItem("projectId");
        const next = saved && items.some((item) => item.id === saved) ? saved : items.find((item) => item.is_default)?.id || items[0]?.id || "";
        setProjectId(next);
        if (next) window.localStorage.setItem("projectId", next);
      })
      .catch((err) => {
        if (cancel) return;
        if (err.status === 503) setDown(true);
        else setError(err.message);
      })
      .finally(() => {
        if (!cancel) setLoading(false);
      });
    return () => {
      cancel = true;
    };
  }, []);

  function selectProject(id) {
    setProjectId(id);
    if (id) window.localStorage.setItem("projectId", id);
  }

  return { projects, projectId, selectProject, setProjects, error, down, loading };
}

export function SuiteProjectBar({ projects, projectId, onChange, onCreated, loading = false, loadError = "" }) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  if (loading) return <p className="text-sm text-muted">Loading skills projects…</p>;
  if (loadError && !projects.length) return <p className="text-sm text-danger">{loadError}</p>;

  async function createProject(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const created = await suiteJson("/api/projects", { method: "POST", body: { name } });
      setName("");
      onCreated(created);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (!projects.length) {
    return (
      <form onSubmit={createProject} className="flex max-w-xl flex-wrap items-end gap-2">
        <label className="min-w-[220px] flex-1 text-xs font-semibold text-muted">
          Skills project
          <input className={fieldClass} value={name} onChange={(event) => setName(event.target.value)} placeholder="Project name" required />
        </label>
        <button type="submit" className={primaryBtn} disabled={busy}>
          {busy ? "Creating…" : "Create skills project"}
        </button>
        {error && <p className="w-full text-sm text-danger">{error}</p>}
      </form>
    );
  }

  return (
    <label className="block max-w-xs text-xs font-semibold text-muted">
      Skills project
      <select className={fieldClass} value={projectId} onChange={(event) => onChange(event.target.value)}>
        {projects.map((item) => (
          <option key={item.id} value={item.id}>
            {item.name}
            {item.is_default ? " (default)" : ""}
          </option>
        ))}
      </select>
    </label>
  );
}
