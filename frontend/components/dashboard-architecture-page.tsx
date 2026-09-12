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
  const [expandedId, setExpandedId] = useState<string | null>(null);
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
    <section className="dash-page">
      <div className="dash-page-toolbar">
        <span className="hint small">
          Architecture runs from Solution Architect and delivery. Open a run for
          the diagram and decisions.
        </span>
      </div>
      <div className="dash-feed">
        {!architectRuns.length ? (
          <div className="dash-empty">
            <h3>No architecture runs yet</h3>
            <p>
              Generate one from Solution Architect in Chat or the Delivery
              checklist.
            </p>
          </div>
        ) : (
          architectRuns.map((item) => {
            const expanded = expandedId === item.id;
            const frameworks = item.architecture?.stack?.frameworks || [];
            return (
              <article className="dash-item finding-card" key={item.id}>
                <div className="finding-card-top">
                  <span className="gate-chip">
                    {item.tier || "—"} · {item.mode || "—"}
                  </span>
                  <span className="finding-meta">
                    {item.status || "unknown"}
                    {item.source ? ` · ${item.source}` : ""}
                  </span>
                </div>
                <h3 className="finding-title">
                  {item.objective || "Architecture run"}
                </h3>
                {item.architecture?.cloud ? (
                  <p className="finding-meta">
                    {item.architecture.cloud}
                    {frameworks.length ? ` · ${frameworks.join(", ")}` : ""}
                  </p>
                ) : null}
                {expanded ? (
                  <div className="architecture-details">
                    <ArchitectureDiagram
                      components={item.architecture?.components}
                    />
                    {item.architecture?.analysis?.brownfield ? (
                      <p className="finding-evidence">
                        {item.architecture.analysis.brownfield}
                      </p>
                    ) : null}
                    {(item.decisions || []).map((decision) => (
                      <p key={decision.id} className="finding-evidence">
                        {decision.title}
                        {decision.gate_decision
                          ? ` · ${decision.gate_decision}`
                          : ""}
                      </p>
                    ))}
                    {item.mermaid ? (
                      <details>
                        <summary>Context diagram source</summary>
                        <pre className="architecture-mermaid">{item.mermaid}</pre>
                      </details>
                    ) : null}
                  </div>
                ) : null}
                <div className="finding-actions">
                  <button
                    type="button"
                    className="tiny-btn"
                    onClick={() =>
                      setExpandedId((current) =>
                        current === item.id ? null : item.id,
                      )
                    }
                  >
                    {expanded ? "Hide details" : "Show diagram & decisions"}
                  </button>
                </div>
              </article>
            );
          })
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
