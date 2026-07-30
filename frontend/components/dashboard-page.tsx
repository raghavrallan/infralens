"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import { displayBrandText } from "../lib/branding";
import type {
  Approval,
  Catalog,
  Finding,
  Project,
  Run,
  Workflow,
} from "../lib/types";
import { Modal, useToast } from "./modal";
import { Shell } from "./shell";
import { ThemedSelect } from "./themed-select";
import { DeliveryChecklist } from "./delivery-checklist";
import { BreakGlassPanel } from "./break-glass-panel";
import { MemoryStrip } from "./memory-strip";
import { getStoredUser } from "../lib/auth";

type Summary = Record<string, unknown>;
type WorkflowDraft = {
  name: string;
  objective: string;
  module: string;
  environment: "dev" | "staging" | "prod";
  schedule_cron: string;
  skills: string[];
};
const TIME_RANGES = [
  { value: "all", label: "All time" },
  { value: "24h", label: "Last 24 hours" },
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
  { value: "90d", label: "Last 90 days" },
];

function numberValue(value: unknown) {
  return typeof value === "number" ? value : Number(value || 0);
}
function prettyName(value = "") {
  return value
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}
function timeAgo(iso?: string) {
  if (!iso) return "—";
  const seconds = Math.max(
    1,
    Math.round((Date.now() - new Date(iso).getTime()) / 1000),
  );
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}
function timeUntil(seconds?: number) {
  if (seconds == null) return "";
  if (seconds <= 0) return "expired";
  const hours = Math.round(seconds / 3600);
  return hours < 1
    ? `${Math.max(1, Math.round(seconds / 60))}m left`
    : `${hours}h left`;
}

export function DashboardPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [catalog, setCatalog] = useState<Catalog>({ skills: [], modules: [] });
  const [summary, setSummary] = useState<Summary>({});
  const [findings, setFindings] = useState<Finding[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [severity, setSeverity] = useState("");
  const [status, setStatus] = useState("open");
  const [module, setModule] = useState("");
  const [timeRange, setTimeRange] = useState("all");
  const [updated, setUpdated] = useState<Date | null>(null);
  const [loading, setLoading] = useState(true);
  const requestRef = useRef(0);
  const [workflowModal, setWorkflowModal] = useState<
    Workflow | null | undefined
  >(undefined);
  const [runModal, setRunModal] = useState<Run | null>(null);
  const { showToast, Toast } = useToast();
  const [statusDropdownOpen, setStatusDropdownOpen] = useState(false);

  const loadProjects = useCallback(async () => {
    const list = await api<Project[]>("/api/projects");
    setProjects(list);
    const saved = window.localStorage.getItem("projectId");
    const selected =
      saved && list.some((project) => project.id === saved)
        ? saved
        : list.find((project) => project.is_default)?.id || list[0]?.id || null;
    setProjectId(selected);
    if (!selected) setLoading(false);
  }, []);
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
      const timeParams = new URLSearchParams({ time_range: timeRange });
      if (module) timeParams.set("module", module);
      try {
        const [
          nextSummary,
          nextFindings,
          nextApprovals,
          nextWorkflows,
          nextRuns,
        ] = await Promise.all([
          api<Summary>(
            `/api/dashboard/summary?project_id=${encodeURIComponent(projectId)}&${timeParams}`,
          ),
          api<Finding[]>(`/api/findings?${query}`),
          api<Approval[]>(
            `/api/approvals?project_id=${encodeURIComponent(projectId)}&status=pending&${timeParams}`,
          ),
          api<Workflow[]>(
            `/api/workflows?project_id=${encodeURIComponent(projectId)}${module ? `&module=${encodeURIComponent(module)}` : ""}`,
          ),
          api<Run[]>(
            `/api/runs?project_id=${encodeURIComponent(projectId)}&limit=12&${timeParams}`,
          ),
        ]);
        if (requestId !== requestRef.current) return;
        setSummary(nextSummary);
        setFindings(nextFindings);
        setApprovals(nextApprovals);
        setWorkflows(nextWorkflows);
        setRuns(nextRuns);
        setUpdated(new Date());
      } finally {
        if (requestId === requestRef.current) setLoading(false);
      }
    },
    [module, projectId, severity, status, timeRange],
  );

  useEffect(() => {
    void Promise.all([
      loadProjects(),
      api<Catalog>("/api/intelligence/catalog").then(setCatalog),
    ]);
  }, [loadProjects]);
  useEffect(() => {
    void loadData(true);
    const timer = window.setInterval(() => {
      if (!document.hidden) void loadData(false);
    }, 15000);
    return () => window.clearInterval(timer);
  }, [loadData]);

  const selectProject = (id: string) => {
    setSummary({});
    setFindings([]);
    setApprovals([]);
    setWorkflows([]);
    setRuns([]);
    setUpdated(null);
    setLoading(true);
    setProjectId(id);
    window.localStorage.setItem("projectId", id);
  };
  const selectModule = (value: string) => {
    setLoading(true);
    setModule(value);
  };
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
  const decideApproval = async (
    approval: Approval,
    decision: "approved" | "rejected",
  ) => {
    const label = decision === "approved" ? "Approve" : "Reject";
    if (!window.confirm(`${label} this gated finding?`)) return;
    try {
      await api(`/api/approvals/${approval.id}/decide`, {
        method: "POST",
        body: JSON.stringify({ decision }),
      });
      showToast(`Finding ${decision}.`, "ok");
      await loadData();
    } catch (error) {
      showToast(
        error instanceof Error ? error.message : "Could not decide approval",
        "error",
      );
    }
  };
  const explain = (finding?: Finding) => {
    if (!finding) return;
    if (!projectId) return;
    window.localStorage.setItem("projectId", projectId);
    window.localStorage.setItem(
      "pendingPrompt",
      `Explain this finding and how to fix it safely.\n\nSkill: ${prettyName(finding.skill)}\nSeverity: ${finding.severity}\nTitle: ${displayBrandText(finding.title)}\n${finding.evidence ? `Evidence: ${displayBrandText(finding.evidence)}` : ""}`,
    );
    window.location.href = "/";
  };
  const runWorkflow = async (id: string) => {
    try {
      await api(`/api/workflows/${id}/run`, { method: "POST" });
      showToast("Run queued.", "ok");
      await loadData();
    } catch (error) {
      showToast(
        error instanceof Error ? error.message : "Could not queue run",
        "error",
      );
    }
  };
  const toggleWorkflow = async (workflow: Workflow) => {
    await api(`/api/workflows/${workflow.id}`, {
      method: "PATCH",
      body: JSON.stringify({ enabled: !workflow.enabled }),
    });
    await loadData();
  };
  const deleteWorkflow = async (workflow: Workflow) => {
    if (!window.confirm("Delete this workflow and its findings?")) return;
    await api(`/api/workflows/${workflow.id}`, { method: "DELETE" });
    await loadData();
  };

  const pendingLive = approvals.filter((approval) => !approval.expired).length;
  const runCounts = (summary.runs_by_status || {}) as Record<string, unknown>;
  const severityCounts = (summary.findings_by_severity || {}) as Record<
    string,
    unknown
  >;
  const runTotal = Object.values(runCounts).reduce<number>(
    (total, value) => total + numberValue(value),
    0,
  );
  const modules = useMemo(() => catalog.modules || [], [catalog.modules]);
  const activeModuleLabel = module
    ? modules.find((item) => item.key === module)?.label || prettyName(module)
    : "All Modules";
  const moduleTabs = [
    {
      key: "",
      label: "All Modules",
      description:
        "View Findings, Approvals, Workflows, and runs across every Intelligence Module.",
    },
    ...modules,
  ];
  const activeModule = modules.find((item) => item.key === module);
  const activeModuleDescription =
    activeModule?.description ||
    "View findings, approvals, workflows, and runs across every intelligence module.";

  return (
    <Shell subtitle="Intelligence Layer" scroll loading={loading}>
      <div className="dash-layout">
        <aside className="dash-sidebar-nav">
          <h3 className="nav-heading">Modules</h3>
          <nav
            className="module-tabs"
            aria-label="Dashboard modules"
            role="tablist"
          >
            {moduleTabs.map((item) => (
              <button
                type="button"
                role="tab"
                key={item.key || "all"}
                className={`module-tab${module === item.key ? " active" : ""}`}
                aria-selected={module === item.key}
                title={item.description || "All intelligence modules"}
                onClick={() => selectModule(item.key)}
              >
                {item.label}
              </button>
            ))}
          </nav>
        </aside>
        <main className="dash">
          <div className="dash-head">
            <div className="dash-context">
            <span className="dash-context-label">Dashboard Module</span>
            <strong>{activeModuleLabel}</strong>
          </div>
          <div className="dash-head-controls">
            <label className="control">
              <span>Project</span>
              <ThemedSelect
                className="project-select"
                value={projectId || ""}
                ariaLabel="Project"
                onChange={selectProject}
                options={projects.map((project) => ({
                  value: project.id,
                  label: `${displayBrandText(project.name)}${project.is_default ? " (default)" : ""}`,
                }))}
              />
            </label>
            <label className="control">
              <span>Time</span>
              <ThemedSelect
                className="time-select"
                value={timeRange}
                ariaLabel="Time range"
                onChange={setTimeRange}
                options={TIME_RANGES}
              />
            </label>
            <span className="updated-note">
              {updated
                ? `Updated ${timeAgo(updated.toISOString())}`
                : projectId
                  ? "Loading"
                  : "Selecting project"}
            </span>
            <button
              className="ghost"
              onClick={() => void loadData()}
              disabled={!projectId}
            >
              Refresh
            </button>
            <button
              className="primary"
              onClick={() => setWorkflowModal(null)}
              disabled={!projectId}
            >
              + Workflow
            </button>
          </div>
        </div>
        <section className="module-definition" aria-live="polite">
          <div className="module-definition-heading">
            <span className="dash-context-label">What this module covers</span>
            <strong>{activeModuleLabel}</strong>
          </div>
          <p>{activeModuleDescription}</p>
          {activeModule?.skills?.length ? (
            <div className="module-definition-skills">
              {activeModule.skills.map((skill) => (
                <span className="mini-pill" key={skill}>
                  {prettyName(skill)}
                </span>
              ))}
            </div>
          ) : null}
        </section>
        <section className="dash-tiles">
          {/* Open Findings */}
          <div className="tile">
            <div className="tile-top">
              <div className="tile-icon tile-icon-blue">
                <svg
                  width="30"
                  height="30"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <rect x="3" y="3" width="7" height="7" rx="1" />
                  <rect x="14" y="3" width="7" height="7" rx="1" />
                  <rect x="3" y="14" width="7" height="7" rx="1" />
                  <rect x="14" y="14" width="7" height="7" rx="1" />
                </svg>
              </div>
              <div>
                <div className="tile-label">Open Findings</div>
                <div className="tile-value">
                  {numberValue(summary.open_findings)}
                </div>
                <div className="tile-sub">
                  <span className="tile-trend up">
                    ↑ {numberValue(severityCounts.critical)} from yesterday
                  </span>
                </div>
              </div>
            </div>
            <div className="tile-breakdown">
              <span className="sev sev-critical">
                {numberValue(severityCounts.critical)} Critical
              </span>
              <span className="sev sev-high">
                {numberValue(severityCounts.high)} High
              </span>
              <span className="sev sev-medium">
                {numberValue(severityCounts.medium)} Medium
              </span>
              <span className="sev sev-low">
                {numberValue(severityCounts.low)} Low
              </span>
            </div>
          </div>

          {/* Awaiting Approval */}
          <div className={`tile${pendingLive ? " tile-warn" : ""}`}>
            <div className="tile-top">
              <div className="tile-icon tile-icon-orange">
                <svg
                  width="30"
                  height="30"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <circle cx="12" cy="12" r="10" />
                  <polyline points="12 6 12 12 16 14" />
                </svg>
              </div>
              <div>
                <div className="tile-label">Awaiting Approval</div>
                <div className="tile-value">{pendingLive}</div>
                <div className="tile-sub">
                  <span className="tile-trend up">
                    ↑ {pendingLive} from yesterday
                  </span>
                </div>
              </div>
            </div>
          </div>

          {/* Workflows */}
          <div className="tile">
            <div className="tile-top">
              <div className="tile-icon tile-icon-green">
                <svg
                  width="30"
                  height="30"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <circle cx="12" cy="12" r="10" />
                  <polyline points="9 12 11 14 15 10" />
                </svg>
              </div>
              <div>
                <div className="tile-label">Workflows</div>
                <div className="tile-value">
                  {numberValue(summary.workflows_enabled)}
                  <span className="tile-value-denom">
                    /{numberValue(summary.workflows_total)}
                  </span>
                </div>
                <div className="tile-sub">Enabled / Total</div>
              </div>
            </div>
          </div>

          {/* Runs */}
          <div
            className={`tile${numberValue(runCounts.failed) ? " tile-warn" : ""}`}
          >
            <div className="tile-top">
              <div className="tile-icon tile-icon-blue">
                <svg
                  width="30"
                  height="30"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
                </svg>
              </div>
              <div>
                <div className="tile-label">Runs</div>
                 <div className="tile-value">{runTotal}</div>
            <div className="tile-sub">
              {numberValue(runCounts.running)} running ·{" "}
              {numberValue(runCounts.failed)} failed
            </div>

              </div>
              
            </div>
           
          </div>
        </section>
        <div className="dash-grid">
          <section className="dash-col">
            <div className="dash-section-head">
              <h3>Findings</h3>
              <div className="filter-stack">
                <div className="filter-row">
                  <div className="filter-dropdown-wrap">
                    <button
                      className={`filter-icon-btn${statusDropdownOpen || status ? " active" : ""}`}
                      onClick={() => setStatusDropdownOpen((o) => !o)}
                      aria-label="Filter by status"
                      title={status ? prettyName(status) : "Filter by status"}
                    >
                      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                        <line x1="4" y1="6" x2="20" y2="6"/>
                        <line x1="8" y1="12" x2="16" y2="12"/>
                        <line x1="11" y1="18" x2="13" y2="18"/>
                      </svg>
                      {status && <span className="filter-icon-label">{prettyName(status)}</span>}
                    </button>
                    {statusDropdownOpen && (
                      <>
                        <div className="filter-dropdown-backdrop" onClick={() => setStatusDropdownOpen(false)} />
                        <div className="filter-dropdown">
                          {["open", "acknowledged", "resolved", ""].map((value) => (
                            <button
                              key={value || "all"}
                              className={`filter-dropdown-item${status === value ? " active" : ""}`}
                              onClick={() => { setStatus(value); setStatusDropdownOpen(false); }}
                            >
                              <span className={`filter-dropdown-dot status-dot-${value || "all"}`} />
                              {value ? prettyName(value) : "All"}
                              {status === value && (
                                <svg className="filter-dropdown-check" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                                  <polyline points="20 6 9 17 4 12"/>
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
                    onChange={setModule}
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
                      key={value || "all"}
                      className={`chip${value ? ` chip-${value}` : ""}${severity === value ? " active" : ""}`}
                      onClick={() => setSeverity(value)}
                    >
                      {value ? prettyName(value) : "All severities"}
                    </button>
                  ))}
                </div>
            </div>
            <div className="findings-feed">
              {!findings.length ? (
                <div className="empty-note">
                  No findings match this filter. Run a workflow to populate the
                  dashboard.
                </div>
              ) : (
                findings.map((finding) => (
                  <div
                    className={`finding-card sev-${finding.severity}${finding.status === "resolved" ? " resolved" : ""}`}
                    key={finding.id}
                  >
                    <div className="finding-top">
                      <span className={`sev sev-${finding.severity}`}>
                        {finding.severity}
                      </span>
                      <span
                        className={`gate-badge gate-${finding.gate_decision}`}
                      >
                        {finding.gate_label}
                      </span>
                      {finding.module_label && (
                        <span className="mini-pill">
                          {finding.module_label}
                        </span>
                      )}
                      {finding.status !== "open" && (
                        <span className={`mini-pill status-${finding.status}`}>
                          {finding.status}
                        </span>
                      )}
                    </div>
                    <div className="finding-title">{displayBrandText(finding.title)}</div>
                    <div className="finding-meta">
                      <span>{prettyName(finding.skill)}</span>
                      {finding.resource && (
                        <span title={displayBrandText(finding.resource)}>{displayBrandText(finding.resource)}</span>
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
                          {displayBrandText(finding.evidence)}
                        </>
                      )}
                      {finding.recommended_action && (
                        <>
                          <span className="label">Recommended action</span>
                          {displayBrandText(finding.recommended_action)}
                        </>
                      )}
                    </div>
                    <div className="finding-actions">
                      <button
                        className="tiny-btn"
                        onClick={() => explain(finding)}
                      >
                        Chat to resolve
                      </button>
                      {finding.status === "open" && (
                        <button
                          className="tiny-btn"
                          onClick={() =>
                            void updateFinding(finding.id, "acknowledged")
                          }
                        >
                          Acknowledge
                        </button>
                      )}
                      {finding.status !== "resolved" ? (
                        <button
                          className="tiny-btn solid"
                          onClick={() =>
                            void updateFinding(finding.id, "resolved")
                          }
                        >
                          Resolve
                        </button>
                      ) : (
                        <button
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
          <aside className="dash-col dash-side">
            {projectId && <DeliveryChecklist projectId={projectId} />}
            {projectId && <BreakGlassPanel projectId={projectId} />}
            {projectId && <MemoryStrip projectId={projectId} />}
            <div className="dash-section-head">
              <h3>Approvals</h3>
              <span className={`pill ${pendingLive ? "warn" : "off"}`}>
                {pendingLive} pending
              </span>
            </div>
            <div className="approvals-list">
              {!approvals.length ? (
                <div className="empty-note">
                  No approvals waiting. Change-producing findings land here,
                  time-boxed.
                </div>
              ) : (
                approvals.map((approval) => (
                  <div
                    className={`approval-card${approval.expired ? " expired" : ""}`}
                    key={approval.id}
                  >
                    <div className="approval-top">
                      <span className={`gate-badge gate-${approval.gate}`}>
                        {approval.gate_label}
                      </span>
                      <span className={`sev sev-${approval.finding?.severity}`}>
                        {approval.finding?.severity}
                      </span>
                      <span className="approval-expiry">
                        {approval.expired
                          ? "expired"
                          : timeUntil(approval.expires_in_seconds)}
                      </span>
                    </div>
                    <div className="approval-title">
                      {approval.finding?.title || "Finding"}
                    </div>
                    <div className="finding-meta">
                      <span>{prettyName(approval.finding?.skill)}</span>
                      <span>
                        blast: {approval.blast_radius || approval.finding?.blast_radius || "—"}
                      </span>
                      {approval.min_role_label && (
                        <span>min role: {approval.min_role_label}</span>
                      )}
                    </div>
                    {approval.gate_rationale && (
                      <div className="approval-note">{approval.gate_rationale}</div>
                    )}
                    {approval.evidence || approval.finding?.evidence ? (
                      <div className="approval-note">
                        Evidence: {approval.evidence || approval.finding?.evidence}
                      </div>
                    ) : null}
                    {approval.rollback && (
                      <div className="approval-note">Rollback: {approval.rollback}</div>
                    )}
                    {approval.preflight?.summary && (
                      <div className="approval-note">{approval.preflight.summary}</div>
                    )}
                    {!!approval.precedent?.length && (
                      <div className="approval-note">
                        Precedent:{" "}
                        {approval.precedent
                          .slice(0, 2)
                          .map((p) => `${p.outcome}: ${p.summary}`)
                          .join(" · ")}
                      </div>
                    )}
                    <div className="approval-note">
                      {approval.gate_label} required — approving records intent
                      only; nothing is executed.
                      {approval.break_glass_applied ? " Break-glass downgrade active." : ""}
                    </div>
                    <div className="finding-actions">
                      <button
                        className="tiny-btn"
                        onClick={() => explain(approval.finding)}
                      >
                        Chat to resolve
                      </button>
                      <button
                        className="tiny-btn danger"
                        onClick={() =>
                          void decideApproval(approval, "rejected")
                        }
                      >
                        Reject
                      </button>
                      {(() => {
                        const me = getStoredUser();
                        const order = [
                          "viewer",
                          "developer",
                          "devops_engineer",
                          "devops_lead",
                          "org_admin",
                          "super_admin",
                        ];
                        const min = approval.min_role || "devops_engineer";
                        const ok =
                          order.indexOf(me?.role || "viewer") >= order.indexOf(min);
                        if (!ok) {
                          return (
                            <span className="empty-note">
                              Needs {approval.min_role_label || min}+
                            </span>
                          );
                        }
                        return (
                          <button
                            className="tiny-btn solid"
                            onClick={() =>
                              void decideApproval(approval, "approved")
                            }
                            title={
                              approval.min_role_label
                                ? `Requires ${approval.min_role_label}+`
                                : undefined
                            }
                          >
                            Approve
                          </button>
                        );
                      })()}
                    </div>
                  </div>
                ))
              )}
            </div>
            <div className="dash-section-head">
              <h3>Workflows</h3>
            </div>
            <div className="workflow-list">
              {!workflows.length ? (
                <div className="empty-note">
                  No workflows yet. Create one to start automated diagnostics.
                </div>
              ) : (
                workflows.map((workflow) => (
                  <div
                    className={`workflow-card${workflow.enabled ? "" : " disabled"}`}
                    key={workflow.id}
                  >
                    <div className="workflow-name">
                      <span>{workflow.name}</span>
                      <span
                        className={`run-status ${workflow.enabled ? "succeeded" : "queued"}`}
                      >
                        {workflow.enabled ? "on" : "off"}
                      </span>
                    </div>
                    <div className="workflow-sub">
                      {workflow.module_label || "Workflow"} ·{" "}
                      {workflow.environment} ·{" "}
                      {workflow.schedule_cron
                        ? `cron ${workflow.schedule_cron}`
                        : "manual"}
                    </div>
                    <div className="workflow-skills">
                      {workflow.skills.map((item) => (
                        <span className="mini-pill" key={item}>
                          {prettyName(item)}
                        </span>
                      ))}
                    </div>
                    <div className="workflow-last">
                      Last:{" "}
                      {workflow.last_run
                        ? `${workflow.last_run.status} ${timeAgo(workflow.last_run.created_at)}`
                        : "never run"}
                    </div>
                    <div className="workflow-actions">
                      <button
                        className="tiny-btn solid"
                        onClick={() => void runWorkflow(workflow.id)}
                      >
                        Run now
                      </button>
                      <button
                        className="tiny-btn"
                        onClick={() => setWorkflowModal(workflow)}
                      >
                        Edit
                      </button>
                      <button
                        className="tiny-btn"
                        onClick={() => void toggleWorkflow(workflow)}
                      >
                        {workflow.enabled ? "Disable" : "Enable"}
                      </button>
                      <button
                        className="tiny-btn danger"
                        onClick={() => void deleteWorkflow(workflow)}
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>
            <div className="dash-section-head">
              <h3>Recent runs</h3>
              <span className="hint small">Click a run for its findings</span>
            </div>
            <div className="run-list">
              {!runs.length ? (
                <div className="empty-note">No runs yet.</div>
              ) : (
                runs.map((run) => (
                  <button
                    className="run-item"
                    key={run.id}
                    onClick={async () =>
                      setRunModal(await api<Run>(`/api/runs/${run.id}`))
                    }
                  >
                    <div>
                      <div>{run.workflow_name || "Workflow"}</div>
                      <div className="run-meta">
                        {run.trigger} · {timeAgo(run.created_at)}
                        {run.finding_count
                          ? ` · ${run.finding_count} findings`
                          : ""}
                      </div>
                    </div>
                    <span className={`run-status ${run.status}`}>
                      {run.status}
                    </span>
                  </button>
                ))
              )}
            </div>
          </aside>
        </div>
        </main>
      </div>
      {workflowModal !== undefined && projectId && (
        <WorkflowModal
          existing={workflowModal}
          catalog={catalog}
          projectId={projectId}
          onClose={() => setWorkflowModal(undefined)}
          onSaved={() => {
            setWorkflowModal(undefined);
            void loadData();
          }}
        />
      )}
      {runModal && (
        <Modal
          wide
          eyebrow={`${runModal.trigger} run · ${runModal.status}`}
          title={runModal.workflow_name || "Workflow run"}
          description={`${timeAgo(runModal.created_at)} · ${(runModal.findings || []).length} finding(s)`}
          onClose={() => setRunModal(null)}
        >
          <div className="modal-body">
            <div className="run-findings">
              {runModal.findings?.length ? (
                runModal.findings.map((finding) => (
                  <div className="finding-card" key={finding.id}>
                    <div className="finding-title">{displayBrandText(finding.title)}</div>
                    <div className="finding-body">{displayBrandText(finding.evidence)}</div>
                  </div>
                ))
              ) : (
                <div className="empty-note">
                  This run produced no findings
                  {runModal.error ? ` — it failed: ${runModal.error}` : "."}
                </div>
              )}
            </div>
            <div className="modal-actions">
              <button
                className="modal-btn primary"
                onClick={() => setRunModal(null)}
              >
                Close
              </button>
            </div>
          </div>
        </Modal>
      )}
      {Toast}
    </Shell>
  );
}

function WorkflowModal({
  existing,
  catalog,
  projectId,
  onClose,
  onSaved,
}: {
  existing: Workflow | null;
  catalog: Catalog;
  projectId: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const initialModule = existing?.module || catalog.modules[0]?.key || "";
  const initialModuleSkills =
    catalog.modules.find((item) => item.key === initialModule)?.skills || [];
  const [draft, setDraft] = useState<WorkflowDraft>({
    name: existing?.name || "",
    objective: existing?.objective || "",
    module: initialModule,
    environment: existing?.environment || "prod",
    schedule_cron: existing?.schedule_cron || "",
    skills: initialModuleSkills.length
      ? [...initialModuleSkills]
      : existing?.skills || [],
  });
  const compatibleSkills = useMemo(
    () =>
      new Set(
        catalog.modules.find((item) => item.key === draft.module)?.skills || [],
      ),
    [catalog.modules, draft.module],
  );
  const update = <K extends keyof WorkflowDraft>(
    key: K,
    value: WorkflowDraft[K],
  ) => setDraft((current) => ({ ...current, [key]: value }));
  const selectModule = (value: string) => {
    const skills =
      catalog.modules.find((item) => item.key === value)?.skills || [];
    setDraft((current) => ({ ...current, module: value, skills: [...skills] }));
  };
  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!draft.skills.length) return;
    const options: RequestInit = {
      method: existing ? "PATCH" : "POST",
      body: JSON.stringify({ ...draft, enabled: existing?.enabled ?? true }),
    };
    const url = existing
      ? `/api/workflows/${existing.id}`
      : `/api/workflows?project_id=${encodeURIComponent(projectId)}`;
    await api(url, options);
    onSaved();
  };
  return (
    <Modal
      wide
      eyebrow={existing ? "Edit workflow" : "New workflow"}
      title={existing ? "Update this workflow" : "Automate diagnose skills"}
      description="Only read-only skills can run unattended. Pick the skills, an optional schedule, and the environment used to gate findings."
      onClose={onClose}
    >
      <form className="modal-body" onSubmit={(event) => void save(event)}>
        <label className="modal-label">
          <span>Name</span>
          <input
            value={draft.name}
            onChange={(event) => update("name", event.target.value)}
            placeholder="Nightly Posture Sweep"
          />
        </label>
        <label className="modal-label">
          <span>Objective</span>
          <textarea
            className="objective-textarea"
            value={draft.objective}
            onChange={(event) => update("objective", event.target.value)}
            placeholder="Review posture and drift"
            rows={4}
          />
        </label>
        <label className="modal-label">
          <span>Module</span>
          <ThemedSelect
            className="modal-select"
            value={draft.module}
            ariaLabel="Module"
            onChange={selectModule}
            options={catalog.modules.map((item) => ({
              value: item.key,
              label: item.label,
            }))}
          />
        </label>
        <label className="modal-label">
          <span>Environment</span>
          <ThemedSelect
            className="modal-select"
            value={draft.environment}
            ariaLabel="Environment"
            onChange={(value) =>
              update("environment", value as WorkflowDraft["environment"])
            }
            options={[
              { value: "prod", label: "Production" },
              { value: "staging", label: "Staging" },
              { value: "dev", label: "Dev" },
            ]}
          />
        </label>
        <label className="modal-label">
          <span>Schedule (cron, optional)</span>
          <input
            value={draft.schedule_cron}
            onChange={(event) => update("schedule_cron", event.target.value)}
            placeholder="0 2 * * *"
          />
        </label>
        <div className="modal-label">
          <span>Skills</span>
          <div className="modal-skill-grid">
            {catalog.skills.map((skill) => {
              const compatible = compatibleSkills.has(skill.name);
              return (
                <label
                  className={`modal-skill${compatible ? "" : " disabled"}`}
                  key={skill.name}
                >
                  <input
                    type="checkbox"
                    checked={compatible && draft.skills.includes(skill.name)}
                    disabled={!compatible}
                    onChange={(event) =>
                      update(
                        "skills",
                        event.target.checked
                          ? [...draft.skills, skill.name]
                          : draft.skills.filter((item) => item !== skill.name),
                      )
                    }
                  />
                  {prettyName(skill.name)}
                </label>
              );
            })}
          </div>
        </div>
        <div className="modal-actions">
          <button type="button" className="modal-btn ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="modal-btn primary">
            {existing ? "Save" : "Create"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
