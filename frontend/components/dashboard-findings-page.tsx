"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import { prettyName } from "../lib/dashboard";
import type { Finding } from "../lib/types";
import { DashboardShell, useDashboardContext } from "./dashboard-shell";
import { useToast } from "./modal";
import { ThemedSelect } from "./themed-select";

const PAGE_SIZE = 25;

function truncate(text: string, max = 160) {
  const cleaned = text.replace(/\s+/g, " ").trim();
  if (cleaned.length <= max) return cleaned;
  return `${cleaned.slice(0, max - 1).trimEnd()}…`;
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
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const requestRef = useRef(0);
  const { showToast, Toast } = useToast();

  const modules = useMemo(() => catalog.modules || [], [catalog.modules]);

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
        setVisibleCount(PAGE_SIZE);
        setUpdated(new Date());
      } finally {
        if (requestId === requestRef.current) setLoading(false);
      }
    },
    [module, projectId, setLoading, setUpdated, severity, status, timeRange],
  );

  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [module, severity, status, timeRange, projectId]);

  useEffect(() => {
    void loadData(true);
    const timer = window.setInterval(() => {
      if (!document.hidden) void loadData(false);
    }, 15000);
    return () => window.clearInterval(timer);
  }, [loadData, refreshKey]);

  const visibleFindings = findings.slice(0, visibleCount);

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
    <section className="dash-page findings-page">
      <div className="dash-page-toolbar findings-toolbar" role="toolbar" aria-label="Findings filters">
        <ThemedSelect
          className="mini-select findings-module-select"
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
        <div className="filter-row findings-severity-row">
          {["", "critical", "high", "medium", "low"].map((value) => (
            <button
              type="button"
              key={value || "all"}
              className={`chip${value ? ` chip-${value}` : ""}${severity === value ? " active" : ""}`}
              onClick={() => setSeverity(value)}
            >
              {value ? prettyName(value) : "All"}
            </button>
          ))}
        </div>
        <ThemedSelect
          className="mini-select findings-status-select"
          value={status}
          ariaLabel="Status"
          onChange={setStatus}
          options={[
            { value: "open", label: "Open" },
            { value: "acknowledged", label: "Acknowledged" },
            { value: "resolved", label: "Resolved" },
            { value: "", label: "All statuses" },
          ]}
        />
        {findings.length ? (
          <span className="hint small">
            Showing {Math.min(visibleCount, findings.length)} of {findings.length}
          </span>
        ) : null}
      </div>

      <div className="dash-feed findings-feed findings-feed-compact">
        {!findings.length ? (
          <div className="dash-empty findings-empty">
            <h3>No findings match this filter</h3>
            <p>
              Try another module or severity, or run a workflow to populate findings.
            </p>
          </div>
        ) : (
          visibleFindings.map((finding) => {
            const expanded = expandedId === finding.id;
            const hasDetails = Boolean(finding.evidence || finding.recommended_action);
            return (
              <article
                className={`dash-item finding-card finding-card-compact sev-${finding.severity}${finding.status === "resolved" ? " resolved" : ""}`}
                key={finding.id}
              >
                <div className="finding-top">
                  <span className={`sev sev-${finding.severity}`}>{finding.severity}</span>
                  {finding.gate_label ? (
                    <span className={`gate-badge gate-${finding.gate_decision}`}>
                      {finding.gate_label}
                    </span>
                  ) : null}
                  {finding.module_label ? (
                    <span className="mini-pill">{finding.module_label}</span>
                  ) : null}
                  {finding.status !== "open" ? (
                    <span className={`mini-pill status-${finding.status}`}>
                      {finding.status}
                    </span>
                  ) : null}
                </div>
                <h3 className="finding-title">{finding.title}</h3>
                <div className="finding-meta">
                  <span>{prettyName(finding.skill)}</span>
                  {finding.resource ? (
                    <span title={finding.resource}>{truncate(finding.resource, 72)}</span>
                  ) : null}
                  <span>blast: {finding.blast_radius || "—"}</span>
                  {(finding.occurrence_count || 1) > 1 ? (
                    <span>Seen {finding.occurrence_count}×</span>
                  ) : null}
                </div>
                {expanded && hasDetails ? (
                  <div className="finding-body">
                    {finding.evidence ? (
                      <>
                        <span className="label">Evidence</span>
                        {finding.evidence}
                      </>
                    ) : null}
                    {finding.recommended_action ? (
                      <>
                        <span className="label">Recommended action</span>
                        {finding.recommended_action}
                      </>
                    ) : null}
                  </div>
                ) : null}
                <div className="finding-actions">
                  {hasDetails ? (
                    <button
                      type="button"
                      className="tiny-btn"
                      onClick={() =>
                        setExpandedId((current) =>
                          current === finding.id ? null : finding.id,
                        )
                      }
                    >
                      {expanded ? "Hide details" : "Show details"}
                    </button>
                  ) : null}
                  <button type="button" className="tiny-btn" onClick={() => explain(finding)}>
                    Chat to resolve
                  </button>
                  {finding.status === "open" ? (
                    <button
                      type="button"
                      className="tiny-btn"
                      onClick={() => void updateFinding(finding.id, "acknowledged")}
                    >
                      Acknowledge
                    </button>
                  ) : null}
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
              </article>
            );
          })
        )}
        {findings.length > visibleCount ? (
          <div className="dash-feed-more">
            <button
              type="button"
              className="tiny-btn"
              onClick={() => setVisibleCount((count) => count + PAGE_SIZE)}
            >
              Load {Math.min(PAGE_SIZE, findings.length - visibleCount)} more
            </button>
          </div>
        ) : null}
      </div>
      {Toast}
    </section>
  );
}

export function DashboardFindingsPage() {
  return (
    <DashboardShell title="Findings">
      <FindingsBody />
    </DashboardShell>
  );
}
