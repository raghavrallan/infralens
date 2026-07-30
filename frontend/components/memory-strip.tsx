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
      {!rows.length ? (
        <p className="empty-note">
          Precedents appear after approvals and module actuations on this project.
        </p>
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
