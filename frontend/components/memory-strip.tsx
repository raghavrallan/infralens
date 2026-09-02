"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { getStoredUser } from "../lib/auth";

type MemoryItem = {
  id: string;
  title?: string;
  summary?: string;
  source?: string;
  confidence?: string;
  status?: string;
  category?: string;
  last_verified_at?: string;
  stale?: boolean;
  created_at?: string;
  related_task_id?: string;
  related_adr?: string;
};

const FILTERS = ["", "architecture", "infrastructure", "security", "database", "cloud", "cicd", "deployment", "incident", "decision", "requirement"];

export function MemoryStrip({ projectId }: { projectId: string }) {
  const me = getStoredUser();
  const canVerify = ["devops_engineer", "devops_lead", "org_admin", "super_admin"].includes(me?.role || "");
  const canArchive = ["devops_lead", "org_admin", "super_admin"].includes(me?.role || "");
  const [rows, setRows] = useState<MemoryItem[]>([]);
  const [category, setCategory] = useState("");
  const [query, setQuery] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    if (!projectId) return;
    try {
      const params = new URLSearchParams({ project_id: projectId, limit: "40" });
      if (category) params.set("category", category);
      if (query) params.set("q", query);
      setRows(await api<MemoryItem[]>(`/api/engineering/memory?${params}`));
    } catch {
      // Keep the last good memory list if the API blips.
    }
  }, [projectId, category, query]);

  useEffect(() => {
    void load();
    const onRefresh = () => { void load(); };
    window.addEventListener("infralens-refresh", onRefresh);
    const timer = window.setInterval(onRefresh, 15000);
    return () => {
      window.removeEventListener("infralens-refresh", onRefresh);
      window.clearInterval(timer);
    };
  }, [load]);

  const setStatus = async (id: string, status: string) => {
    try {
      await api(`/api/engineering/memory/${id}/status`, { method: "POST", body: JSON.stringify({ status }) });
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Update failed");
    }
  };

  return (
    <section className="card" id="memory">
      <div className="card-head">
        <h3>Engineering memory</h3>
        <span className="pill off">{rows.length}</span>
      </div>
      <p style={{ margin: "8px 0 12px", fontSize: 13, color: "var(--muted)" }}>
        Decisions, requirements, and outcomes from this project — not a scratch pad.
      </p>
      <div className="eng-memory-tools">
        <select value={category} onChange={(e) => setCategory(e.target.value)}>
          {FILTERS.map((item) => (
            <option key={item || "all"} value={item}>{item || "All categories"}</option>
          ))}
        </select>
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search memory…" />
      </div>
      {!rows.length ? (
        <div style={{ textAlign: "center", padding: 16 }}>
          <strong style={{ display: "block", marginBottom: 4 }}>No memories yet</strong>
          <span className="muted">They appear after architecture, approvals, and delivery evidence.</span>
        </div>
      ) : (
        <ul className="memory-list eng-memory-list">
          {rows.map((row) => (
            <li key={row.id}>
              <div className="eng-memory-row">
                <strong>{row.title || row.summary}</strong>
                <span className={`eng-mem-status ${row.status}`}>{row.status}{row.stale ? " · stale" : ""}</span>
              </div>
              <small>{row.category} · {row.source} · {row.confidence} confidence</small>
              {row.related_adr || row.related_task_id ? (
                <small> Linked ADR/task</small>
              ) : null}
              <div className="eng-memory-actions">
                {canVerify && row.status !== "verified" && row.status !== "archived" && (
                  <button type="button" className="tiny-btn" onClick={() => void setStatus(row.id, "verified")}>Verify</button>
                )}
                {canArchive && row.status !== "archived" && (
                  <button type="button" className="tiny-btn" onClick={() => void setStatus(row.id, "archived")}>Archive</button>
                )}
                {canArchive && row.status === "active" && (
                  <button type="button" className="tiny-btn" onClick={() => void setStatus(row.id, "superseded")}>Supersede</button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      {message ? <div className="form-msg">{message}</div> : null}
    </section>
  );
}
