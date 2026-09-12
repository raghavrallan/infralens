"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import type { ArchitectRun } from "../lib/dashboard";
import { ArchitectureDiagram } from "./architecture-diagram";
import { DashboardShell, useDashboardContext } from "./dashboard-shell";

function ArchitectureBody() {
  const { projectId, setUpdated, setLoading, refreshKey } =
    useDashboardContext();
  const [architectRuns, setArchitectRuns] = useState<ArchitectRun[]>([]);
  const requestRef = useRef(0);

  const loadData = useCallback(
    async (showLoader = true) => {
      if (!projectId) {
        setLoading(false);
        return;
      }
      const requestId = ++requestRef.current;
      if (showLoader) setLoading(true);
      try {
        const nextArchitect = await api<ArchitectRun[]>(
          `/api/architecture/runs?project_id=${encodeURIComponent(projectId)}&limit=8`,
        ).catch(() => [] as ArchitectRun[]);
        if (requestId !== requestRef.current) return;
        setArchitectRuns(nextArchitect);
        setUpdated(new Date());
      } finally {
        if (requestId === requestRef.current) setLoading(false);
      }
    },
    [projectId, setLoading, setUpdated],
  );

  useEffect(() => {
    void loadData(true);
    const timer = window.setInterval(() => {
      if (!document.hidden) void loadData(false);
    }, 15000);
    return () => window.clearInterval(timer);
  }, [loadData, refreshKey]);

  return (
    <section className="dash-col">
      <div className="dash-section-head">
        <h3>Architecture</h3>
      </div>
      <div className="finding-list">
        {!architectRuns.length ? (
          <div className="empty-note">
            No architecture runs yet. Generate one from Solution Architect.
          </div>
        ) : (
          architectRuns.map((item) => (
            <article className="finding-card" key={item.id}>
              <div className="finding-card-top">
                <span className="gate-chip">
                  {item.tier} · {item.mode}
                </span>
                <span className="finding-meta">
                  {item.status} · {item.source}
                </span>
              </div>
              <h4>{item.objective || "Architecture run"}</h4>
              {item.architecture?.cloud ? (
                <p className="finding-meta">
                  {item.architecture.cloud}
                  {(item.architecture.stack?.frameworks || []).length
                    ? ` · ${(item.architecture.stack?.frameworks || []).join(", ")}`
                    : ""}
                </p>
              ) : null}
              <ArchitectureDiagram components={item.architecture?.components} />
              {item.architecture?.analysis?.brownfield ? (
                <p className="finding-evidence">
                  {item.architecture.analysis.brownfield}
                </p>
              ) : null}
              {(item.decisions || []).map((decision) => (
                <p key={decision.id} className="finding-evidence">
                  {decision.title}
                  {decision.gate_decision ? ` · ${decision.gate_decision}` : ""}
                </p>
              ))}
              {item.mermaid ? (
                <details>
                  <summary>Context diagram source</summary>
                  <pre style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>
                    {item.mermaid}
                  </pre>
                </details>
              ) : null}
            </article>
          ))
        )}
      </div>
    </section>
  );
}

export function DashboardArchitecturePage() {
  return (
    <DashboardShell title="Architecture">
      <ArchitectureBody />
    </DashboardShell>
  );
}
