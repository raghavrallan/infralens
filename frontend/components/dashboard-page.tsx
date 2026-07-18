"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import type { Approval, Catalog, Finding, Project, Run, Workflow } from "../lib/types";
import { Modal, useToast } from "./modal";
import { Shell } from "./shell";

type Summary = Record<string, unknown>;
type WorkflowDraft = { name: string; objective: string; module: string; environment: "dev" | "staging" | "prod"; schedule_cron: string; skills: string[] };

function numberValue(value: unknown) { return typeof value === "number" ? value : Number(value || 0); }
function prettyName(value = "") { return value.split("_").map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(" "); }
function timeAgo(iso?: string) {
  if (!iso) return "—";
  const seconds = Math.max(1, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
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
  return hours < 1 ? `${Math.max(1, Math.round(seconds / 60))}m left` : `${hours}h left`;
}

export function DashboardPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState("default");
  const [catalog, setCatalog] = useState<Catalog>({ skills: [], modules: [] });
  const [summary, setSummary] = useState<Summary>({});
  const [findings, setFindings] = useState<Finding[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [severity, setSeverity] = useState("");
  const [status, setStatus] = useState("open");
  const [module, setModule] = useState("");
  const [updated, setUpdated] = useState<Date | null>(null);
  const [workflowModal, setWorkflowModal] = useState<Workflow | null | undefined>(undefined);
  const [runModal, setRunModal] = useState<Run | null>(null);
  const { showToast, Toast } = useToast();

  const loadProjects = useCallback(async () => {
    const list = await api<Project[]>("/api/projects");
    setProjects(list);
    const saved = window.localStorage.getItem("projectId") || "default";
    setProjectId(list.some((project) => project.id === saved) ? saved : list[0]?.id || "default");
  }, []);
  const loadData = useCallback(async () => {
    const query = new URLSearchParams({ project_id: projectId });
    if (severity) query.set("severity", severity);
    if (status) query.set("status", status);
    if (module) query.set("module", module);
    const [nextSummary, nextFindings, nextApprovals, nextWorkflows, nextRuns] = await Promise.all([
      api<Summary>(`/api/dashboard/summary?project_id=${encodeURIComponent(projectId)}`),
      api<Finding[]>(`/api/findings?${query}`),
      api<Approval[]>(`/api/approvals?project_id=${encodeURIComponent(projectId)}&status=pending`),
      api<Workflow[]>(`/api/workflows?project_id=${encodeURIComponent(projectId)}`),
      api<Run[]>(`/api/runs?project_id=${encodeURIComponent(projectId)}&limit=12`),
    ]);
    setSummary(nextSummary); setFindings(nextFindings); setApprovals(nextApprovals); setWorkflows(nextWorkflows); setRuns(nextRuns); setUpdated(new Date());
  }, [module, projectId, severity, status]);

  useEffect(() => { void Promise.all([loadProjects(), api<Catalog>("/api/intelligence/catalog").then(setCatalog)]); }, [loadProjects]);
  useEffect(() => { void loadData(); const timer = window.setInterval(() => { if (!document.hidden) void loadData(); }, 15000); return () => window.clearInterval(timer); }, [loadData]);

  const selectProject = (id: string) => { setProjectId(id); window.localStorage.setItem("projectId", id); };
  const updateFinding = async (id: string, nextStatus: Finding["status"]) => { try { await api(`/api/findings/${id}`, { method: "PATCH", body: JSON.stringify({ status: nextStatus }) }); await loadData(); } catch (error) { showToast(error instanceof Error ? error.message : "Could not update finding", "error"); } };
  const decideApproval = async (approval: Approval, decision: "approved" | "rejected") => {
    const label = decision === "approved" ? "Approve" : "Reject";
    if (!window.confirm(`${label} this gated finding?`)) return;
    try { await api(`/api/approvals/${approval.id}/decide`, { method: "POST", body: JSON.stringify({ decision }) }); showToast(`Finding ${decision}.`, "ok"); await loadData(); } catch (error) { showToast(error instanceof Error ? error.message : "Could not decide approval", "error"); }
  };
  const explain = (finding?: Finding) => {
    if (!finding) return;
    window.localStorage.setItem("projectId", projectId);
    window.localStorage.setItem("pendingPrompt", `Explain this finding and how to fix it safely.\n\nSkill: ${prettyName(finding.skill)}\nSeverity: ${finding.severity}\nTitle: ${finding.title}\n${finding.evidence ? `Evidence: ${finding.evidence}` : ""}`);
    window.location.href = "/";
  };
  const runWorkflow = async (id: string) => { try { await api(`/api/workflows/${id}/run`, { method: "POST" }); showToast("Run queued.", "ok"); await loadData(); } catch (error) { showToast(error instanceof Error ? error.message : "Could not queue run", "error"); } };
  const toggleWorkflow = async (workflow: Workflow) => { await api(`/api/workflows/${workflow.id}`, { method: "PATCH", body: JSON.stringify({ enabled: !workflow.enabled }) }); await loadData(); };
  const deleteWorkflow = async (workflow: Workflow) => { if (!window.confirm("Delete this workflow and its findings?")) return; await api(`/api/workflows/${workflow.id}`, { method: "DELETE" }); await loadData(); };

  const pendingLive = approvals.filter((approval) => !approval.expired).length;
  const runCounts = (summary.runs_by_status || {}) as Record<string, unknown>;
  const severityCounts = (summary.findings_by_severity || {}) as Record<string, unknown>;
  const runTotal = Object.values(runCounts).reduce<number>((total, value) => total + numberValue(value), 0);
  const modules = useMemo(() => catalog.modules || [], [catalog.modules]);

  return <Shell subtitle="Intelligence Layer" scroll>
    <main className="dash">
      <div className="dash-head"><div><h2 className="page-title">DevOps Intelligence</h2><p className="page-sub">Skills run unattended in a queue. Every finding is gated by action class and blast radius — you gate entry into risk, never the escape.</p></div>
        <div className="dash-head-controls"><label className="control"><span>Project</span><select className="project-select" value={projectId} onChange={(event) => selectProject(event.target.value)}>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label><span className="updated-note">{updated ? `Updated ${timeAgo(updated.toISOString())}` : "Loading"}</span><button className="ghost" onClick={() => void loadData()}>Refresh</button><button className="primary" onClick={() => setWorkflowModal(null)}>+ Workflow</button></div>
      </div>
      <section className="dash-tiles"><div className="tile"><div className="tile-label">Open findings</div><div className="tile-value">{numberValue(summary.open_findings)}</div><div className="tile-sub">Unresolved across workflows</div><div className="tile-breakdown"><span className="sev sev-critical">{numberValue(severityCounts.critical)} crit</span><span className="sev sev-high">{numberValue(severityCounts.high)} high</span><span className="sev sev-medium">{numberValue(severityCounts.medium)} med</span><span className="sev sev-low">{numberValue(severityCounts.low)} low</span></div></div><div className={`tile${pendingLive ? " tile-warn" : ""}`}><div className="tile-label">Awaiting approval</div><div className="tile-value">{pendingLive}</div><div className="tile-sub">Gated: human or two-person</div></div><div className="tile"><div className="tile-label">Workflows</div><div className="tile-value">{numberValue(summary.workflows_enabled)}/{numberValue(summary.workflows_total)}</div><div className="tile-sub">Enabled / total</div></div><div className={`tile${numberValue(runCounts.failed) ? " tile-warn" : ""}`}><div className="tile-label">Runs</div><div className="tile-value">{runTotal}</div><div className="tile-sub">{numberValue(runCounts.running)} running · {numberValue(runCounts.failed)} failed</div></div></section>
      <div className="dash-grid"><section className="dash-col"><div className="dash-section-head"><h3>Findings</h3><div className="filter-stack"><div className="filter-row">{["", "critical", "high", "medium", "low"].map((value) => <button key={value || "all"} className={`chip${severity === value ? " active" : ""}`} onClick={() => setSeverity(value)}>{value ? prettyName(value) : "All severities"}</button>)}</div><div className="filter-row">{["open", "acknowledged", "resolved", ""].map((value) => <button key={value || "all"} className={`chip${status === value ? " active" : ""}`} onClick={() => setStatus(value)}>{value ? prettyName(value) : "All"}</button>)}<select className="mini-select" value={module} onChange={(event) => setModule(event.target.value)}><option value="">All modules</option>{modules.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}</select></div></div></div><div className="findings-feed">{!findings.length ? <div className="empty-note">No findings match this filter. Run a workflow to populate the dashboard.</div> : findings.map((finding) => <div className={`finding-card sev-${finding.severity}${finding.status === "resolved" ? " resolved" : ""}`} key={finding.id}><div className="finding-top"><span className={`sev sev-${finding.severity}`}>{finding.severity}</span><span className={`gate-badge gate-${finding.gate_decision}`}>{finding.gate_label}</span>{finding.module_label && <span className="mini-pill">{finding.module_label}</span>}{finding.status !== "open" && <span className={`mini-pill status-${finding.status}`}>{finding.status}</span>}</div><div className="finding-title">{finding.title}</div><div className="finding-meta"><span>{prettyName(finding.skill)}</span>{finding.resource && <span title={finding.resource}>{finding.resource}</span>}<span>blast: {finding.blast_radius || "—"}</span></div><div className="finding-body">{finding.evidence && <><span className="label">Evidence</span>{finding.evidence}</>}{finding.recommended_action && <><span className="label">Recommended action</span>{finding.recommended_action}</>}</div><div className="finding-actions"><button className="tiny-btn" onClick={() => explain(finding)}>Explain in chat</button>{finding.status === "open" && <button className="tiny-btn" onClick={() => void updateFinding(finding.id, "acknowledged")}>Acknowledge</button>}{finding.status !== "resolved" ? <button className="tiny-btn solid" onClick={() => void updateFinding(finding.id, "resolved")}>Resolve</button> : <button className="tiny-btn" onClick={() => void updateFinding(finding.id, "open")}>Reopen</button>}</div></div>)}</div></section>
        <aside className="dash-col dash-side"><div className="dash-section-head"><h3>Approvals</h3><span className={`pill ${pendingLive ? "warn" : "off"}`}>{pendingLive} pending</span></div><div className="approvals-list">{!approvals.length ? <div className="empty-note">No approvals waiting. Change-producing findings land here, time-boxed.</div> : approvals.map((approval) => <div className={`approval-card${approval.expired ? " expired" : ""}`} key={approval.id}><div className="approval-top"><span className={`gate-badge gate-${approval.gate}`}>{approval.gate_label}</span><span className={`sev sev-${approval.finding?.severity}`}>{approval.finding?.severity}</span><span className="approval-expiry">{approval.expired ? "expired" : timeUntil(approval.expires_in_seconds)}</span></div><div className="approval-title">{approval.finding?.title || "Finding"}</div><div className="finding-meta"><span>{prettyName(approval.finding?.skill)}</span><span>blast: {approval.finding?.blast_radius || "—"}</span></div><div className="approval-note">{approval.gate_label} required — approving records intent only; nothing is executed.</div><div className="finding-actions"><button className="tiny-btn" onClick={() => explain(approval.finding)}>Explain in chat</button><button className="tiny-btn danger" onClick={() => void decideApproval(approval, "rejected")}>Reject</button><button className="tiny-btn solid" onClick={() => void decideApproval(approval, "approved")}>Approve</button></div></div>)}</div>
          <div className="dash-section-head"><h3>Workflows</h3></div><div className="workflow-list">{!workflows.length ? <div className="empty-note">No workflows yet. Create one to start automated diagnostics.</div> : workflows.map((workflow) => <div className={`workflow-card${workflow.enabled ? "" : " disabled"}`} key={workflow.id}><div className="workflow-name"><span>{workflow.name}</span><span className={`run-status ${workflow.enabled ? "succeeded" : "queued"}`}>{workflow.enabled ? "on" : "off"}</span></div><div className="workflow-sub">{workflow.module_label || "Workflow"} · {workflow.environment} · {workflow.schedule_cron ? `cron ${workflow.schedule_cron}` : "manual"}</div><div className="workflow-skills">{workflow.skills.map((item) => <span className="mini-pill" key={item}>{prettyName(item)}</span>)}</div><div className="workflow-last">Last: {workflow.last_run ? `${workflow.last_run.status} ${timeAgo(workflow.last_run.created_at)}` : "never run"}</div><div className="workflow-actions"><button className="tiny-btn solid" onClick={() => void runWorkflow(workflow.id)}>Run now</button><button className="tiny-btn" onClick={() => setWorkflowModal(workflow)}>Edit</button><button className="tiny-btn" onClick={() => void toggleWorkflow(workflow)}>{workflow.enabled ? "Disable" : "Enable"}</button><button className="tiny-btn danger" onClick={() => void deleteWorkflow(workflow)}>Delete</button></div></div>)}</div>
          <div className="dash-section-head"><h3>Recent runs</h3><span className="hint small">Click a run for its findings</span></div><div className="run-list">{!runs.length ? <div className="empty-note">No runs yet.</div> : runs.map((run) => <button className="run-item" key={run.id} onClick={async () => setRunModal(await api<Run>(`/api/runs/${run.id}`))}><div><div>{run.workflow_name || "Workflow"}</div><div className="run-meta">{run.trigger} · {timeAgo(run.created_at)}{run.finding_count ? ` · ${run.finding_count} findings` : ""}</div></div><span className={`run-status ${run.status}`}>{run.status}</span></button>)}</div>
        </aside></div>
    </main>
    {workflowModal !== undefined && <WorkflowModal existing={workflowModal} catalog={catalog} projectId={projectId} onClose={() => setWorkflowModal(undefined)} onSaved={() => { setWorkflowModal(undefined); void loadData(); }} />}
    {runModal && <Modal wide eyebrow={`${runModal.trigger} run · ${runModal.status}`} title={runModal.workflow_name || "Workflow run"} description={`${timeAgo(runModal.created_at)} · ${(runModal.findings || []).length} finding(s)`} onClose={() => setRunModal(null)}><div className="modal-body"><div className="run-findings">{runModal.findings?.length ? runModal.findings.map((finding) => <div className="finding-card" key={finding.id}><div className="finding-title">{finding.title}</div><div className="finding-body">{finding.evidence}</div></div>) : <div className="empty-note">This run produced no findings{runModal.error ? ` — it failed: ${runModal.error}` : "."}</div>}</div><div className="modal-actions"><button className="modal-btn primary" onClick={() => setRunModal(null)}>Close</button></div></div></Modal>}
    {Toast}
  </Shell>;
}

function WorkflowModal({ existing, catalog, projectId, onClose, onSaved }: { existing: Workflow | null; catalog: Catalog; projectId: string; onClose: () => void; onSaved: () => void }) {
  const [draft, setDraft] = useState<WorkflowDraft>({ name: existing?.name || "", objective: existing?.objective || "", module: existing?.module || catalog.modules[0]?.key || "", environment: existing?.environment || "prod", schedule_cron: existing?.schedule_cron || "", skills: existing?.skills || [] });
  const update = <K extends keyof WorkflowDraft>(key: K, value: WorkflowDraft[K]) => setDraft((current) => ({ ...current, [key]: value }));
  const save = async (event: React.FormEvent) => { event.preventDefault(); if (!draft.skills.length) return; const options: RequestInit = { method: existing ? "PATCH" : "POST", body: JSON.stringify({ ...draft, enabled: existing?.enabled ?? true }) }; const url = existing ? `/api/workflows/${existing.id}` : `/api/workflows?project_id=${encodeURIComponent(projectId)}`; await api(url, options); onSaved(); };
  return <Modal eyebrow={existing ? "Edit workflow" : "New workflow"} title={existing ? "Update this workflow" : "Automate diagnose skills"} description="Only read-only skills can run unattended. Pick the skills, an optional schedule, and the environment used to gate findings." onClose={onClose}><form className="modal-body" onSubmit={(event) => void save(event)}><label className="modal-label"><span>Name</span><input value={draft.name} onChange={(event) => update("name", event.target.value)} placeholder="Nightly Posture Sweep" /></label><label className="modal-label"><span>Objective</span><input value={draft.objective} onChange={(event) => update("objective", event.target.value)} placeholder="Review posture and drift" /></label><label className="modal-label"><span>Module</span><select className="modal-select" value={draft.module} onChange={(event) => update("module", event.target.value)}>{catalog.modules.map((item) => <option value={item.key} key={item.key}>{item.label}</option>)}</select></label><label className="modal-label"><span>Environment</span><select className="modal-select" value={draft.environment} onChange={(event) => update("environment", event.target.value as WorkflowDraft["environment"])}><option value="prod">Production</option><option value="staging">Staging</option><option value="dev">Dev</option></select></label><label className="modal-label"><span>Schedule (cron, optional)</span><input value={draft.schedule_cron} onChange={(event) => update("schedule_cron", event.target.value)} placeholder="0 2 * * *" /></label><div className="modal-label"><span>Skills</span><div className="modal-skill-grid">{catalog.skills.map((skill) => <label className="modal-skill" key={skill.name}><input type="checkbox" checked={draft.skills.includes(skill.name)} onChange={(event) => update("skills", event.target.checked ? [...draft.skills, skill.name] : draft.skills.filter((item) => item !== skill.name))} />{prettyName(skill.name)}</label>)}</div></div><div className="modal-actions"><button type="button" className="modal-btn ghost" onClick={onClose}>Cancel</button><button type="submit" className="modal-btn primary">{existing ? "Save" : "Create"}</button></div></form></Modal>;
}
