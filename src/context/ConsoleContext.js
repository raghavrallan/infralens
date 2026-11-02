"use client";

import { createContext, useContext, useEffect, useRef, useState } from "react";
import { useFeedback } from "@/components/Feedback";
import { ESTATE_PARTS, estateMessage } from "@/lib/estate-messages";

const ConsoleContext = createContext(null);

export function ConsoleProvider({ children }) {
  const [projectId, setProjectId] = useState("");
  const [rangeId, setRangeId] = useState("mtd");
  const [nonce, setNonce] = useState(0);
  const fresh = useRef(false);
  const loaded = useRef("");
  const [model, setModel] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [now, setNow] = useState(null);
  const { notify: pushToast } = useFeedback();

  useEffect(() => {
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const isFresh = fresh.current;
    fresh.current = false;
    const poll = { id: 0, stop: 0 };

    function query(opened) {
      const params = new URLSearchParams({ range: rangeId });
      if (projectId) params.set("projectId", projectId);
      if (opened) params.set("open", "1");
      if (isFresh && opened) params.set("fresh", "1");
      return params;
    }

    async function readParts(params) {
      const settled = await Promise.all(ESTATE_PARTS.map(async (name) => {
        const res = await fetch(`/api/estate/${name}?${params}`, { cache: "no-store" });
        const body = await res.json().catch(() => ({}));
        if (!res.ok) return { error: body.message || estateMessage(`${name}.failed`) };
        return { body };
      }));
      const merged = {
        kpis: { spend: null, currency: "USD", forecast: null, resourceCount: 0, vmCount: 0, vmRunning: 0, groupCount: 0 },
        trend: { points: [] },
        services: [],
        groups: [],
        databricks: { series: [], points: [] },
        resources: [],
        vms: [],
        hosting: [],
        workspaces: [],
        storage: [],
        pipelines: [],
        activity: [],
        operations: [],
        alerts: [],
        advisor: [],
        warnings: [],
        subscriptions: [],
      };
      const extra = [];
      for (const item of settled) {
        if (item.body) Object.assign(merged, item.body);
        if (item.error) extra.push(item.error);
      }
      if (extra.length) merged.warnings = [...(merged.warnings || []), ...extra];
      return merged;
    }

    async function read(opened) {
      const params = query(opened);
      const res = await fetch(`/api/estate/status?${params}`, { cache: "no-store" });
      const shell = await res.json().catch(() => ({}));
      if (cancelled) return null;
      if (res.status === 401) {
        window.location.href = "/login";
        return null;
      }
      if (!res.ok) {
        const message = shell.message || estateMessage("status.failed");
        setError(message);
        pushToast(message, "error");
        return null;
      }
      setError("");
      if (shell.status === "error" && shell.message) pushToast(shell.message, "error");
      const sig = shell.syncedAt ? `${shell.project?.id}:${shell.range?.id}:${shell.syncedAt}` : "";
      if (!sig) {
        loaded.current = "";
        setModel({ ...shell, partsReady: shell.status === "setup" });
        return shell;
      }
      if (loaded.current === sig) {
        setModel((current) => (current ? {
          ...current,
          refreshing: shell.refreshing,
          schedule: shell.schedule,
          message: shell.message,
          workspace: shell.workspace,
          status: shell.status,
        } : shell));
        return shell;
      }
      const partParams = new URLSearchParams({ range: rangeId });
      if (projectId) partParams.set("projectId", projectId);
      const parts = await readParts(partParams);
      if (cancelled) return shell;
      loaded.current = sig;
      const clean = { ...parts };
      delete clean.part;
      setModel({
        ...clean,
        ...shell,
        warnings: [...new Set([...(shell.warnings || []), ...(clean.warnings || [])])],
        partsReady: true,
      });
      return shell;
    }

    async function load() {
      setLoading(true);
      try {
        const body = await read(true);
        if (!body?.refreshing || cancelled) return;
        poll.stop = window.setTimeout(() => window.clearInterval(poll.id), 3 * 60 * 1000);
        poll.id = window.setInterval(async () => {
          const next = await read(false);
          if (!next || cancelled || !next.refreshing) {
            window.clearInterval(poll.id);
            window.clearTimeout(poll.stop);
          }
        }, 4000);
      } catch {
        if (!cancelled) {
          const message = estateMessage("network.failed");
          setError(message);
          pushToast(message, "error");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
      window.clearInterval(poll.id);
      window.clearTimeout(poll.stop);
    };
  }, [projectId, rangeId, nonce, pushToast]);

  function notify(message, tone = "info") {
    pushToast(message, tone);
  }

  function selectProject(id) {
    if (id && id !== projectId) setProjectId(id);
  }

  function selectRange(id) {
    if (id && id !== rangeId) setRangeId(id);
  }

  function reloadNow() {
    fresh.current = true;
    setNonce((value) => value + 1);
  }

  async function saveSchedule(cadence) {
    const res = await fetch("/api/estate/schedule", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ projectId: model?.project?.id || projectId, cadence }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      notify(body.message || "Could not save the schedule.", "error");
      return false;
    }
    setModel((current) => (current ? { ...current, schedule: { cadence: body.cadence } } : current));
    notify("Sync schedule saved.", "ok");
    return true;
  }

  async function switchOrg(orgId) {
    const res = await fetch("/api/session/org", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ orgId }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      notify(body.message || "Could not switch organization.", "error");
      return;
    }
    setProjectId("");
    setModel(null);
    reloadNow();
  }

  return (
    <ConsoleContext.Provider
      value={{ model, projectId: projectId || model?.project?.id || "", rangeId, now, loading, error, notify, selectProject, selectRange, refresh: reloadNow, reloadNow, saveSchedule, switchOrg }}
    >
      {children}
    </ConsoleContext.Provider>
  );
}

export function useConsole() {
  const ctx = useContext(ConsoleContext);
  if (!ctx) throw new Error("useConsole must be used inside ConsoleProvider");
  return ctx;
}
