"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import { prettyName } from "../lib/dashboard";
import type { Finding } from "../lib/types";
import { DashboardShell, useDashboardContext } from "./dashboard-shell";
import { useToast } from "./modal";
import { ThemedSelect } from "./themed-select";

function getModuleIcon(key: string) {
  switch (key) {
    case "":
      return (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <rect x="3" y="3" width="7" height="7" />
          <rect x="14" y="3" width="7" height="7" />
          <rect x="14" y="14" width="7" height="7" />
          <rect x="3" y="14" width="7" height="7" />
        </svg>
      );
    case "pipeline_intelligence":
      return (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <line x1="8" y1="6" x2="21" y2="6" />
          <line x1="8" y1="12" x2="21" y2="12" />
          <line x1="8" y1="18" x2="21" y2="18" />
          <line x1="3" y1="6" x2="3.01" y2="6" />
          <line x1="3" y1="12" x2="3.01" y2="12" />
          <line x1="3" y1="18" x2="3.01" y2="18" />
        </svg>
      );
    case "release_confidence":
      return (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
          <polyline points="22 4 12 14.01 9 11.01" />
        </svg>
      );
    case "infrastructure_as_code":
      return (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <polyline points="16 18 22 12 16 6" />
          <polyline points="8 6 2 12 8 18" />
        </svg>
      );
    case "incident_response":
      return (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
          <line x1="12" y1="9" x2="12" y2="13" />
          <line x1="12" y1="17" x2="12.01" y2="17" />
        </svg>
      );
    case "security_patch":
      return (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
        </svg>
      );
    case "finops":
      return (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <line x1="12" y1="1" x2="12" y2="23" />
          <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
        </svg>
      );
    default:
      return (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="16" x2="12" y2="12" />
          <line x1="12" y1="8" x2="12.01" y2="8" />
        </svg>
      );
  }
}

function FindingsBody() {
  const {
    projectId,
    timeRange,
    catalog,
    setUpdated,
    setLoading,
    refreshKey,
  } = useDashboardContext();
  const [findings, setFindings] = useState<Finding[]>([]);
  const [severity, setSeverity] = useState("");
  const [status, setStatus] = useState("open");
  const [module, setModule] = useState("");
  const [statusDropdownOpen, setStatusDropdownOpen] = useState(false);
  const requestRef = useRef(0);
  const { showToast, Toast } = useToast();

  const modules = useMemo(() => catalog.modules || [], [catalog.modules]);
  const moduleTabs = useMemo(
    () => [
      {
        key: "",
        label: "All Modules",
        description: "View findings across every Intelligence Module.",
      },
      ...modules,
    ],
    [modules],
  );

  const loadData = useCallback(
    async (showLoader = true) => {
      if (!projectId) {
        setLoading(false);
        return;
      }
      const requestId = ++requestRef.current;
      if (showLoader) setLoading(true);
      const query = new URLSearchParams({ project_id: projectId });
      if (severity) query.set("severity", severity);
      if (status) query.set("status", status);
      if (module) query.set("module", module);
      query.set("time_range", timeRange);
      try {
        const nextFindings = await api<Finding[]>(`/api/findings?${query}`);
        if (requestId !== requestRef.current) return;
        setFindings(nextFindings);
        setUpdated(new Date());
      } finally {
        if (requestId === requestRef.current) setLoading(false);
      }
    },
    [module, projectId, setLoading, setUpdated, severity, status, timeRange],
  );

  useEffect(() => {
    void loadData(true);
    const timer = window.setInterval(() => {
      if (!document.hidden) void loadData(false);
    }, 15000);
    return () => window.clearInterval(timer);
  }, [loadData, refreshKey]);

  const updateFinding = async (id: string, nextStatus: Finding["status"]) => {
    try {
      await api(`/api/findings/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: nextStatus }),
      });
      await loadData();
    } catch (error) {
      showToast(
        error instanceof Error ? error.message : "Could not update finding",
        "error",
      );
    }
  };

  const explain = (finding?: Finding) => {
    if (!finding || !projectId) return;
    window.localStorage.setItem("projectId", projectId);
    window.localStorage.setItem(
      "pendingPrompt",
      `Explain this finding and how to fix it safely.\n\nSkill: ${prettyName(finding.skill)}\nSeverity: ${finding.severity}\nTitle: ${finding.title}\n${finding.evidence ? `Evidence: ${finding.evidence}` : ""}`,
    );
    window.location.href = "/";
  };

  return (
    <>
      <nav className="module-tabs" aria-label="Findings modules" role="tablist">
        {moduleTabs.map((item) => (
          <button
            type="button"
            role="tab"
            key={item.key || "all"}
            className={`module-tab${module === item.key ? " active" : ""}`}
            aria-selected={module === item.key}
            title={item.description || "All intelligence modules"}
            onClick={() => {
              setLoading(true);
              setModule(item.key);
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
              {getModuleIcon(item.key)}
              <span>{item.label}</span>
            </div>
          </button>
        ))}
      </nav>

      <section className="dash-col" style={{ marginTop: 16 }}>
        <div className="dash-section-head">
          <h3>Findings</h3>
          <div className="filter-stack">
            <div className="filter-row">
              <div className="filter-dropdown-wrap">
                <button
                  type="button"
                  className={`filter-icon-btn${statusDropdownOpen || status ? " active" : ""}`}
                  onClick={() => setStatusDropdownOpen((open) => !open)}
                  aria-label="Filter by status"
                  title={status ? prettyName(status) : "Filter by status"}
                >
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                    <line x1="4" y1="6" x2="20" y2="6" />
                    <line x1="8" y1="12" x2="16" y2="12" />
                    <line x1="11" y1="18" x2="13" y2="18" />
                  </svg>
                  {status && <span className="filter-icon-label">{prettyName(status)}</span>}
                </button>
                {statusDropdownOpen && (
                  <>
                    <div
                      className="filter-dropdown-backdrop"
                      onClick={() => setStatusDropdownOpen(false)}
                    />
                    <div className="filter-dropdown">
                      {["open", "acknowledged", "resolved", ""].map((value) => (
                        <button
                          type="button"
                          key={value || "all"}
                          className={`filter-dropdown-item${status === value ? " active" : ""}`}
                          onClick={() => {
                            setStatus(value);
                            setStatusDropdownOpen(false);
                          }}
                        >
                          <span className={`filter-dropdown-dot status-dot-${value || "all"}`} />
                          {value ? prettyName(value) : "All"}
                          {status === value && (
                            <svg className="filter-dropdown-check" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                              <polyline points="20 6 9 17 4 12" />
                            </svg>
                          )}
                        </button>
                      ))}
                    </div>
                  </>
                )}
              </div>
              <ThemedSelect
                className="mini-select"
                value={module}
                ariaLabel="Module"
                onChange={(value) => {
                  setLoading(true);
                  setModule(value);
                }}
                options={[
                  { value: "", label: "All modules" },
                  ...modules.map((item) => ({
                    value: item.key,
                    label: item.label,
                  })),
                ]}
              />
            </div>
          </div>
        </div>
        <div>
          <div className="filter-row">
            {["", "critical", "high", "medium", "low"].map((value) => (
              <button
                type="button"
                key={value || "all"}
                className={`chip${value ? ` chip-${value}` : ""}${severity === value ? " active" : ""}`}
                onClick={() => setSeverity(value)}
              >
                {value ? prettyName(value) : "All severities"}
              </button>
            ))}
          </div>
        </div>
        <div
          className="findings-feed"
          style={{ maxHeight: "calc(3 * 220px)", overflowY: "auto", paddingRight: "8px" }}
        >
          {!findings.length ? (
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                padding: "64px 24px",
                textAlign: "center",
                background: "var(--panel)",
                borderRadius: "var(--radius)",
                border: "1px solid var(--border)",
                width: "100%",
              }}
            >
              <div
                style={{
                  width: "80px",
                  height: "80px",
                  borderRadius: "50%",
                  border: "1px dashed var(--border-strong)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  marginBottom: "16px",
                }}
              >
                <div
                  style={{
                    width: "56px",
                    height: "56px",
                    borderRadius: "12px",
                    background: "var(--primary-subtle)",
                    color: "var(--primary)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
                    <circle cx="14" cy="13" r="3" />
                    <line x1="16.5" y1="15.5" x2="19" y2="18" />
                  </svg>
                </div>
              </div>
              <h3 style={{ margin: "0 0 8px 0", fontSize: "16px", fontWeight: "600" }}>
                No findings match this filter.
              </h3>
              <p style={{ margin: 0, color: "var(--muted)", fontSize: "14px", maxWidth: "320px" }}>
                Try adjusting the severity filter or run a workflow to populate the dashboard.
              </p>
            </div>
          ) : (
            findings.map((finding) => (
              <div
                className={`finding-card sev-${finding.severity}${finding.status === "resolved" ? " resolved" : ""}`}
                key={finding.id}
              >
                <div className="finding-top">
                  <span className={`sev sev-${finding.severity}`}>{finding.severity}</span>
                  <span className={`gate-badge gate-${finding.gate_decision}`}>
                    {finding.gate_label}
                  </span>
                  {finding.module_label && (
                    <span className="mini-pill">{finding.module_label}</span>
                  )}
                  {finding.status !== "open" && (
                    <span className={`mini-pill status-${finding.status}`}>
                      {finding.status}
                    </span>
                  )}
                </div>
                <div className="finding-title">{finding.title}</div>
                <div className="finding-meta">
                  <span>{prettyName(finding.skill)}</span>
                  {finding.resource && (
                    <span title={finding.resource}>{finding.resource}</span>
                  )}
                  <span>blast: {finding.blast_radius || "—"}</span>
                  {(finding.occurrence_count || 1) > 1 && (
                    <span title="Times this issue was seen across workflow runs">
                      Seen {finding.occurrence_count}×
                    </span>
                  )}
                </div>
                <div className="finding-body">
                  {finding.evidence && (
                    <>
                      <span className="label">Evidence</span>
                      {finding.evidence}
                    </>
                  )}
                  {finding.recommended_action && (
                    <>
                      <span className="label">Recommended action</span>
                      {finding.recommended_action}
                    </>
                  )}
                </div>
                <div className="finding-actions">
                  <button type="button" className="tiny-btn" onClick={() => explain(finding)}>
                    Chat to resolve
                  </button>
                  {finding.status === "open" && (
                    <button
                      type="button"
                      className="tiny-btn"
                      onClick={() => void updateFinding(finding.id, "acknowledged")}
                    >
                      Acknowledge
                    </button>
                  )}
                  {finding.status !== "resolved" ? (
                    <button
                      type="button"
                      className="tiny-btn solid"
                      onClick={() => void updateFinding(finding.id, "resolved")}
                    >
                      Resolve
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="tiny-btn"
                      onClick={() => void updateFinding(finding.id, "open")}
                    >
                      Reopen
                    </button>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      </section>
      {Toast}
    </>
  );
}

export function DashboardFindingsPage() {
  return (
    <DashboardShell title="Findings">
      <FindingsBody />
    </DashboardShell>
  );
}
