"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";

type Precedent = {
  id?: string;
  summary?: string;
  outcome?: string;
  created_at?: string;
};

export function MemoryStrip({ projectId }: { projectId: string }) {
  const [rows, setRows] = useState<Precedent[]>([]);

  const load = useCallback(async () => {
    if (!projectId) return;
    try {
      setRows(
        await api<Precedent[]>(
          `/api/memory/precedent?project_id=${encodeURIComponent(projectId)}&limit=5`,
        ),
      );
    } catch {
      setRows([]);
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section className="card">
      <div className="card-head">
        <h3>Engineering memory</h3>
        <span className="pill off">{rows.length}</span>
      </div>
      <p style={{ margin: '8px 0 24px', fontSize: '13px', lineHeight: '1.5', color: 'var(--text)' }}>
        Precedents appear after approvals and module actuations on this project.
      </p>
      {!rows.length ? (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', padding: '16px' }}>
          <div style={{ width: '56px', height: '56px', background: 'var(--primary-subtle)', color: 'var(--primary)', borderRadius: '16px', display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: '16px' }}>
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>
          </div>
          <strong style={{ fontSize: '14px', display: 'block', marginBottom: '4px' }}>No precedents yet</strong>
          <span style={{ fontSize: '13px', color: 'var(--muted)' }}>They will appear here once available.</span>
        </div>
      ) : (
        <ul className="memory-list">
          {rows.map((row, idx) => (
            <li key={row.id || idx}>
              <strong>{row.outcome || "recorded"}</strong>: {row.summary || "—"}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
