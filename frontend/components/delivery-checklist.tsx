"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { getStoredUser } from "../lib/auth";
import { ArchitectureDiagram } from "./architecture-diagram";
import { Modal } from "./modal";

type RevertModal =
  | { kind: "execute" }
  | { kind: "request" }
  | { kind: "approve"; requestId: string };
type RevertRequest = {
  id: string;
  status: string;
  reason?: string;
  requested_by_name?: string;
  created_at?: string;
};
type DeliveryRun = {
  id: string;
  stage: string;
  status: string;
  checklist: ChecklistItem[];
  next_actions: string[];
  artifacts?: Record<string, unknown>;
};
type Artifact = {
  id: string;
  name: string;
  filename?: string;
  kind?: string;
  validation_status?: string;
  origin?: string;
  content_text?: string;
};
type Task = {
  id: string;
  title: string;
  description?: string;
  stage: string;
  stage_label?: string;
  status: string;
  priority?: string;
  blocked_reason?: string;
  required_artifacts?: Array<{ name?: string } | string>;
  missing_artifacts?: string[];
  artifacts?: Artifact[];
  validation_ok?: boolean;
  ai_recommendation?: string;
  depends_on?: string[];
  acceptance_criteria?: string[];
};

const ROLE_ORDER = ["viewer", "developer", "devops_engineer", "devops_lead", "org_admin", "super_admin"];
function hasMinRole(userRole: string | undefined, minimum?: string) {
  if (!minimum) return true;
  return ROLE_ORDER.indexOf(userRole || "viewer") >= ROLE_ORDER.indexOf(minimum);
}

const NEXT_STATUS: Record<string, string> = {
  not_started: "ready",
  ready: "in_progress",
  in_progress: "validation_required",
  validation_required: "ready_for_review",
  validation_failed: "in_progress",
  blocked: "ready",
  ready_for_review: "approved",
  approved: "completed",
};

export function DeliveryChecklist({ projectId }: { projectId: string }) {
  const me = getStoredUser();
  const [run, setRun] = useState<DeliveryRun | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [docs, setDocs] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [openId, setOpenId] = useState<string>("");
  const [viewing, setViewing] = useState<{ id: string; name: string; content: string } | null>(null);
  const [revertRequests, setRevertRequests] = useState<RevertRequest[]>([]);
  const [revertModal, setRevertModal] = useState<RevertModal | null>(null);
  const [revertReason, setRevertReason] = useState("");

  const loadTasks = useCallback(async () => {
    if (!projectId) return;
    try {
      setTasks(await api<Task[]>(`/api/engineering/tasks?project_id=${encodeURIComponent(projectId)}`));
    } catch {
      // Keep the last good checklist instead of flashing empty on a blip.
    }
  }, [projectId]);

  const loadRevertRequests = useCallback(async (runId: string) => {
    try {
      setRevertRequests(
        await api<RevertRequest[]>(`/api/delivery/runs/${runId}/terraform/revert/requests`),
      );
    } catch {
      setRevertRequests([]);
    }
  }, []);

  const load = useCallback(async () => {
    if (!projectId) return;
    try {
      const runs = await api<DeliveryRun[]>(`/api/delivery/runs?project_id=${encodeURIComponent(projectId)}`);
      setRun(runs[0] || null);
      if (runs[0]?.id) await loadRevertRequests(runs[0].id);
    } catch {
      setRun(null);
    }
    await loadTasks();
  }, [projectId, loadTasks, loadRevertRequests]);

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

  const architectureStatus = String((run?.artifacts?.architecture_status as string) || "");
  const architectureProposal = run?.artifacts?.architecture_proposal as
    | {
        summary?: string;
        hld?: string;
        components?: string[];
        notes?: string;
        tier?: string;
        mode?: string;
        mermaid?: string;
        architecture?: {
          cloud?: string;
          stack?: { frameworks?: string[]; languages?: string[] };
          components?: Array<{ name?: string; service?: string; purpose?: string; provider?: string }>;
          iac_strategy?: string;
          analysis?: {
            security?: string[];
            scaling?: string[];
            cost?: string[];
            availability?: string[];
            brownfield?: string;
          };
        };
        analysis?: {
          security?: string[];
          scaling?: string[];
          cost?: string[];
          availability?: string[];
          brownfield?: string;
        };
      }
    | undefined;
  const architectureProgress = String((run?.artifacts?.architecture_progress as string) || "");
  const analysis = architectureProposal?.architecture?.analysis || architectureProposal?.analysis;

  useEffect(() => {
    if (run?.stage !== "architecture" || architectureStatus !== "generating") return;
    const timer = window.setInterval(() => void load(), 2500);
    return () => window.clearInterval(timer);
  }, [run?.stage, architectureStatus, load]);

  useEffect(() => {
    const repairingNow = String((run?.artifacts?.terraform_repair as { status?: string } | undefined)?.status || "") === "running";
    if (!repairingNow) return;
    const timer = window.setInterval(() => void load(), 2500);
    return () => window.clearInterval(timer);
  }, [run?.artifacts?.terraform_repair, load]);

  const start = async () => {
    setBusy(true);
    setMessage("");
    try {
      setRun(await api<DeliveryRun>("/api/delivery/runs", { method: "POST", body: JSON.stringify({ project_id: projectId }) }));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not start delivery");
    } finally {
      setBusy(false);
    }
  };

  const saveDocs = async () => {
    if (!run) return;
    setBusy(true);
    try {
      setRun(await api<DeliveryRun>(`/api/delivery/runs/${run.id}/docs`, { method: "POST", body: JSON.stringify({ docs }) }));
      setMessage("Docs ingested into project context.");
      await loadTasks();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Ingest failed");
    } finally {
      setBusy(false);
    }
  };

  const uploadIngest = async (file: File) => {
    if (!run) return;
    setBusy(true);
    try {
      const form = new FormData();
      form.append("project_id", projectId);
      form.append("delivery_run_id", run.id);
      form.append("file", file);
      await api("/api/engineering/artifacts/upload", { method: "POST", body: form });
      const text = await file.text().catch(() => "");
      if (text) setDocs((prev) => (prev ? `${prev}\n\n${text.slice(0, 20000)}` : text.slice(0, 20000)));
      setMessage(`Attached ${file.name}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  };

  const advance = async (toStage: string, artifactKey?: string, artifactValue?: unknown) => {
    if (!run) return null;
    setBusy(true);
    setMessage("");
    try {
      const updated = await api<DeliveryRun>(`/api/delivery/runs/${run.id}/transition`, {
        method: "POST",
        body: JSON.stringify({ to_stage: toStage, artifact_key: artifactKey, artifact_value: artifactValue }),
      });
      setRun(updated);
      await loadTasks();
      return updated;
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Transition failed");
      return null;
    } finally {
      setBusy(false);
    }
  };

  const moveTask = async (task: Task, status: string) => {
    setBusy(true);
    setMessage("");
    try {
      await api(`/api/engineering/tasks/${task.id}/transition`, {
        method: "POST",
        body: JSON.stringify({ status }),
      });
      await loadTasks();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Task update failed");
    } finally {
      setBusy(false);
    }
  };

  const attachToTask = async (task: Task, file: File) => {
    setBusy(true);
    try {
      const form = new FormData();
      form.append("project_id", projectId);
      form.append("task_id", task.id);
      form.append("delivery_run_id", run?.id || "");
      form.append("file", file);
      await api("/api/engineering/artifacts/upload", { method: "POST", body: form });
      await loadTasks();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  };

  const runIsolated = async (path: string, body?: Record<string, unknown>) => {
    if (!run) return;
    setBusy(true);
    setMessage("");
    const poll = window.setInterval(() => void load(), 2500);
    try {
      const updated = await api<DeliveryRun>(`/api/delivery/runs/${run.id}/${path}`, {
        method: "POST",
        body: JSON.stringify(body || {}),
      });
      setRun(updated);
      await loadTasks();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Action failed");
      await load();
    } finally {
      window.clearInterval(poll);
      setBusy(false);
    }
  };

  const requestOrRunRevert = async (reason = "", execute = false) => {
    if (!run) return;
    const canExecute = execute || hasMinRole(me?.display_role || me?.role, "org_admin");
    if (!canExecute && !reason.trim()) {
      setMessage("Add a reason so Org Admin / Super Admin can review the revert request.");
      return;
    }
    setBusy(true);
    setMessage("");
    const poll = window.setInterval(() => void load(), 2500);
    try {
      const result = await api<{ mode?: string; run?: DeliveryRun; request?: RevertRequest }>(
        `/api/delivery/runs/${run.id}/terraform/revert`,
        {
          method: "POST",
          body: JSON.stringify({ confirm: canExecute, reason }),
        },
      );
      if (result.run) setRun(result.run);
      if (result.mode === "requested") {
        setMessage("Revert request sent. Org Admin or Super Admin can approve it.");
      } else {
        setMessage("Revert finished.");
      }
      setRevertModal(null);
      setRevertReason("");
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Revert failed");
      await load();
    } finally {
      window.clearInterval(poll);
      setBusy(false);
    }
  };

  const decideRevert = async (requestId: string, approve: boolean) => {
    if (!run) return;
    setBusy(true);
    setMessage("");
    const poll = window.setInterval(() => void load(), 2500);
    try {
      const result = await api<{ run?: DeliveryRun }>(
        `/api/delivery/runs/${run.id}/terraform/revert/requests/${requestId}/decide`,
        {
          method: "POST",
          body: JSON.stringify({ approve, confirm: approve }),
        },
      );
      if (result.run) setRun(result.run);
      setMessage(approve ? "Revert approved and executed." : "Revert request rejected.");
      setRevertModal(null);
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not decide revert");
      await load();
    } finally {
      window.clearInterval(poll);
      setBusy(false);
    }
  };

  const viewArtifact = async (file: Artifact) => {
    setBusy(true);
    try {
      const row = await api<Artifact>(`/api/engineering/artifacts/${file.id}`);
      setViewing({
        id: row.id,
        name: row.filename || row.name,
        content: row.content_text || "// Empty file",
      });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not open file");
    } finally {
      setBusy(false);
    }
  };

  const generateForTask = async (task: Task) => {
    setBusy(true);
    try {
      const result = await api<{ artifacts?: Artifact[] }>(`/api/engineering/tasks/${task.id}/generate`, {
        method: "POST",
        body: JSON.stringify({ kind: "terraform" }),
      });
      await loadTasks();
      const first = (result.artifacts || []).find((item) => item.id);
      if (first) await viewArtifact(first);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Generate failed");
    } finally {
      setBusy(false);
    }
  };

  const currentItem = run?.checklist?.find((item) => item.status === "current");
  const nextStage = () => {
    if (!run?.checklist || !currentItem) return null;
    const idx = run.checklist.findIndex((item) => item.stage === currentItem.stage);
    return run.checklist[idx + 1]?.stage || "done";
  };
  const retryArchitecture = async () => {
    if (!run) return;
    setBusy(true);
    setMessage("");
    try {
      setRun(
        await api<DeliveryRun>(`/api/delivery/runs/${run.id}/architecture/retry`, {
          method: "POST",
        }),
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Retry failed");
    } finally {
      setBusy(false);
    }
  };

  const userRole = me?.display_role || me?.role;
  const generatingArchitecture = run?.stage === "architecture" && architectureStatus === "generating";
  const architectureFailed = run?.stage === "architecture" && architectureStatus === "failed";
  const architectureReady = run?.stage !== "architecture" || architectureStatus === "ready";
  const canAdvance = hasMinRole(userRole, currentItem?.min_role) && !generatingArchitecture && architectureReady;
  const terraformInit = (run?.artifacts?.terraform_init || {}) as { status?: string; stderr?: string };
  const terraformRepair = (run?.artifacts?.terraform_repair || {}) as {
    status?: string;
    phase?: string;
    progress?: string;
    last_diagnosis?: string;
    turns?: Array<{ phase?: string; attempt?: number; diagnosis?: string; files?: string[] }>;
  };
  const terraformProgress = String((run?.artifacts?.terraform_progress as string) || terraformRepair.progress || "");
  const initPassed = terraformInit.status === "passed";
  const planPassed = String((run?.artifacts?.action_diff as { status?: string } | undefined)?.status || "") === "passed";
  const applyStatus = String((run?.artifacts?.apply_result as { status?: string } | undefined)?.status || "");
  const canExecuteRevert = hasMinRole(userRole, "org_admin");
  const canShowIac = ["terraform", "plan", "apply", "code", "done"].includes(run?.stage || "");
  const canRevertStack = ["applied", "failed", "reverted"].includes(applyStatus);
  const pendingRevert = revertRequests.find((item) => item.status === "pending");
  const repairing = terraformRepair.status === "running" || busy;

  return (
    <section className="card delivery-checklist" id="delivery" style={{ padding: "24px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "24px" }}>
        <div>
          <h3 style={{ margin: "0 0 4px 0", fontSize: "18px" }}>Delivery checklist</h3>
          <p style={{ margin: 0, color: "var(--muted)", fontSize: "14px" }}>
            Architecture generates real tasks. Complete only with artifacts, validation, and approval.
          </p>
        </div>
        {!run ? (
          <button type="button" className="tiny-btn solid" disabled={busy} onClick={() => void start()}>Start delivery</button>
        ) : (
          <div style={{ background: "var(--success-subtle)", padding: "6px 12px", borderRadius: "8px", display: "flex", flexDirection: "column", alignItems: "flex-end" }}>
            <span style={{ color: "var(--success)", fontSize: "11px", fontWeight: 600 }}>Current stage</span>
            <strong style={{ color: "var(--success)" }}>{run.stage}</strong>
          </div>
        )}
      </div>

      {!run ? (
        <p className="empty-note">Docs → architecture → generated tasks → gated apply. Nothing completes on a click alone.</p>
      ) : (
        <>
          <div style={{ display: "flex", alignItems: "flex-start", marginBottom: "36px" }}>
            {run.checklist.map((item, i) => {
              const isDone = item.status === "done";
              const isCurrent = item.status === "current";
              const color = isDone || isCurrent ? "var(--primary)" : "var(--muted)";
              return (
                <div key={item.stage} style={{ display: "flex", alignItems: "center", flex: i === run.checklist.length - 1 ? "none" : 1 }}>
                  <div style={{ display: "flex", flexDirection: "column", alignItems: "center", position: "relative" }}>
                    <div style={{ width: 32, height: 32, borderRadius: "50%", border: `2px solid ${isDone || isCurrent ? "var(--primary)" : "var(--border)"}`, background: isDone ? "var(--primary)" : "transparent", color: isDone ? "#fff" : color, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13 }}>{isDone ? "✓" : i + 1}</div>
                    <span style={{ position: "absolute", top: 40, fontSize: 12, color, whiteSpace: "nowrap" }}>{item.label}</span>
                  </div>
                  {i < run.checklist.length - 1 && <div style={{ flex: 1, borderTop: "2px dashed var(--border)", margin: "0 10px" }} />}
                </div>
              );
            })}
          </div>

          {run.stage === "ingest" && (
            <div className="delivery-docs">
              <textarea value={docs} onChange={(e) => setDocs(e.target.value)} placeholder="Paste requirements, or upload PDF/DOCX/TF/YAML…" rows={4} />
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button type="button" className="tiny-btn" disabled={busy} onClick={() => void saveDocs()}>Save docs</button>
                <label className="tiny-btn" style={{ cursor: "pointer" }}>
                  Upload file
                  <input type="file" hidden onChange={(e) => { const file = e.target.files?.[0]; if (file) void uploadIngest(file); e.target.value = ""; }} />
                </label>
              </div>
            </div>
          )}
          {run.stage === "architecture" && (
            <div className="delivery-docs" style={{ marginBottom: 16 }}>
              {architectureStatus === "generating" && (
                <p className="empty-note">
                  {architectureProgress || "Generating architecture and delivery tasks…"}
                </p>
              )}
              {architectureStatus === "failed" && (
                <p className="form-msg">{architectureProposal?.summary || "Architecture generation failed."}</p>
              )}
              {architectureProposal?.summary && architectureStatus !== "generating" && architectureStatus !== "failed" && (
                <div style={{ fontSize: 13 }}>
                  <p>
                    <strong>{architectureProposal.tier} {architectureProposal.mode}</strong>
                    {architectureProposal.architecture?.cloud ? ` · ${architectureProposal.architecture.cloud}` : ""}
                    {" "}{architectureProposal.summary}
                  </p>
                  <ArchitectureDiagram components={architectureProposal.architecture?.components} />
                  {analysis?.brownfield ? <p className="muted">{analysis.brownfield}</p> : null}
                  {analysis && (analysis.security || analysis.cost) ? (
                    <div className="arch-analysis">
                      {analysis.security?.length ? (
                        <div>
                          <h5>Security</h5>
                          <ul>{analysis.security.slice(0, 3).map((item) => <li key={item}>{item}</li>)}</ul>
                        </div>
                      ) : null}
                      {analysis.cost?.length ? (
                        <div>
                          <h5>Cost</h5>
                          <ul>{analysis.cost.slice(0, 2).map((item) => <li key={item}>{item}</li>)}</ul>
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                  {architectureProposal.mermaid ? (
                    <details style={{ marginTop: 8 }}>
                      <summary>Context diagram source</summary>
                      <pre className="eng-criteria" style={{ whiteSpace: "pre-wrap" }}>{architectureProposal.mermaid}</pre>
                    </details>
                  ) : null}
                  {architectureProposal.architecture?.iac_strategy ? (
                    <p className="muted">{architectureProposal.architecture.iac_strategy}</p>
                  ) : null}
                </div>
              )}
            </div>
          )}

          {tasks.length > 0 && (
            <div className="eng-task-list">
              <h4 style={{ margin: "8px 0 12px" }}>Executable tasks ({tasks.filter((t) => t.status === "completed").length}/{tasks.length})</h4>
              {tasks.map((task) => {
                const next = NEXT_STATUS[task.status];
                const required = (task.required_artifacts || []).map((item) => typeof item === "string" ? item : item.name || "").filter(Boolean);
                return (
                  <article key={task.id} className={`eng-task ${task.status}`}>
                    <button type="button" className="eng-task-head" onClick={() => setOpenId(openId === task.id ? "" : task.id)}>
                      <span className="eng-task-status">{task.status.replaceAll("_", " ")}</span>
                      <strong>{task.title}</strong>
                      <small>{task.stage_label || task.stage}</small>
                    </button>
                    {openId === task.id && (
                      <div className="eng-task-body">
                        {task.description ? <p>{task.description}</p> : null}
                        {task.blocked_reason ? <p className="eng-blocked">Blocked by: {task.blocked_reason}</p> : null}
                        {task.ai_recommendation ? <p className="muted">AI: {task.ai_recommendation}</p> : null}
                        {required.length > 0 && (
                          <p className="muted">Required: {required.join(", ")}{task.missing_artifacts?.length ? ` — missing ${task.missing_artifacts.join(", ")}` : ""}</p>
                        )}
                        <ul className="eng-files">
                          {(task.artifacts || []).map((file) => (
                            <li key={file.id}>
                              <button type="button" className="eng-file-link" disabled={busy} onClick={() => void viewArtifact(file)}>
                                {file.name}
                              </button>
                              {" · "}{file.origin}{" · "}{file.validation_status || "pending"}
                            </li>
                          ))}
                        </ul>
                        {viewing && (task.artifacts || []).some((file) => file.id === viewing.id) && (
                          <div className="eng-file-view">
                            <div className="eng-file-view-head">
                              <strong>{viewing.name}</strong>
                              <button type="button" className="tiny-btn" onClick={() => setViewing(null)}>Close</button>
                            </div>
                            <pre>{viewing.content}</pre>
                          </div>
                        )}
                        <div className="eng-task-actions">
                          <label className="tiny-btn">
                            Upload file
                            <input type="file" hidden onChange={(e) => { const file = e.target.files?.[0]; if (file) void attachToTask(task, file); e.target.value = ""; }} />
                          </label>
                          <button type="button" className="tiny-btn" disabled={busy} onClick={() => void generateForTask(task)}>Generate artifact</button>
                          {next && (
                            <button type="button" className="tiny-btn solid" disabled={busy} onClick={() => void moveTask(task, next)}>
                              {next === "completed" ? "Complete (gated)" : next.replaceAll("_", " ")}
                            </button>
                          )}
                        </div>
                        {(task.acceptance_criteria || []).length > 0 && (
                          <ul className="eng-criteria">
                            {task.acceptance_criteria?.map((item) => <li key={item}>{item}</li>)}
                          </ul>
                        )}
                      </div>
                    )}
                  </article>
                );
              })}
            </div>
          )}

          {canShowIac && (
            <div className="delivery-docs" style={{ marginBottom: 16 }}>
              {run.artifacts?.iac_workspace ? (
                <p className="muted">
                  Isolated workspace: {String((run.artifacts.iac_workspace as { workspace?: string }).workspace || "synced")}
                </p>
              ) : null}
              {run.artifacts?.terraform_pr && typeof run.artifacts.terraform_pr === "object" ? (
                <p className="muted">
                  GitHub: {String((run.artifacts.terraform_pr as { repo?: string }).repo || "")}{" "}
                  {(run.artifacts.terraform_pr as { pr_url?: string }).pr_url ? (
                    <a href={String((run.artifacts.terraform_pr as { pr_url?: string }).pr_url)} target="_blank" rel="noreferrer">
                      open PR
                    </a>
                  ) : (
                    String((run.artifacts.terraform_pr as { branch?: string }).branch || "")
                  )}
                </p>
              ) : null}
              <p className="muted">
                Init: {terraformInit.status || "not started"}
                {terraformInit.stderr ? ` — ${terraformInit.stderr.slice(0, 240)}` : ""}
              </p>
              {run.artifacts?.action_diff && typeof run.artifacts.action_diff === "object" ? (
                <p className="muted">
                  Plan: {String((run.artifacts.action_diff as { plan_summary?: string }).plan_summary || "")}
                </p>
              ) : null}
              {run.artifacts?.apply_result && typeof run.artifacts.apply_result === "object" ? (
                <p className="muted">
                  Apply: {String((run.artifacts.apply_result as { status?: string }).status || "")} —{" "}
                  {String((run.artifacts.apply_result as { message?: string }).message || "")}
                </p>
              ) : null}
              {run.artifacts?.revert_result && typeof run.artifacts.revert_result === "object" ? (
                <p className="muted">
                  Revert: {String((run.artifacts.revert_result as { status?: string }).status || "")} —{" "}
                  {String((run.artifacts.revert_result as { message?: string }).message || "")}
                </p>
              ) : null}
              {(terraformProgress || (terraformRepair.turns || []).length > 0) && (
                <div className="tf-repair">
                  {terraformProgress ? <p className="empty-note">{terraformProgress}</p> : null}
                  {(terraformRepair.turns || []).slice(-6).map((turn, index) => (
                    <p key={`${turn.phase}-${turn.attempt}-${index}`} className="muted">
                      {turn.phase} #{turn.attempt}: {turn.diagnosis || "repaired"}
                      {(turn.files || []).length ? ` · ${(turn.files || []).join(", ")}` : ""}
                    </p>
                  ))}
                </div>
              )}
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button type="button" className="tiny-btn" disabled={repairing} onClick={() => void runIsolated("github/push")}>
                  Push IaC to GitHub
                </button>
                <button type="button" className="tiny-btn solid" disabled={repairing} onClick={() => void runIsolated("terraform/init")}>
                  Init workspace
                </button>
                <button
                  type="button"
                  className="tiny-btn"
                  disabled={repairing || !initPassed}
                  title={initPassed ? "Run isolated plan" : "Init must pass before plan"}
                  onClick={() => void runIsolated("terraform/plan")}
                >
                  Run isolated plan
                </button>
                {hasMinRole(userRole, "devops_lead") && (
                  <button
                    type="button"
                    className="tiny-btn solid"
                    disabled={repairing || !planPassed}
                    title={planPassed ? "Apply with project credentials" : "Plan must pass before apply"}
                    onClick={() => {
                      const destroy = Number((run.artifacts?.action_diff as { destroy?: number } | undefined)?.destroy || 0);
                      if (destroy > 0 && !window.confirm(`Plan destroys ${destroy} resources. Apply anyway?`)) return;
                      void runIsolated("terraform/apply", { confirm_destroy: destroy > 0 });
                    }}
                  >
                    Apply with project credentials
                  </button>
                )}
                {canRevertStack && (
                  <button
                    type="button"
                    className="tiny-btn danger"
                    disabled={repairing || Boolean(pendingRevert && !canExecuteRevert)}
                    title={
                      canExecuteRevert
                        ? "Destroy isolated stack with project credentials"
                        : pendingRevert
                          ? "A revert request is waiting for Org Admin / Super Admin"
                          : "Ask Org Admin or Super Admin to revert this isolated apply"
                    }
                    onClick={() => {
                      const canExecute = hasMinRole(me?.display_role || me?.role, "org_admin");
                      setRevertReason("");
                      setRevertModal(canExecute ? { kind: "execute" } : { kind: "request" });
                    }}
                  >
                    {canExecuteRevert ? "Revert isolated stack" : pendingRevert ? "Revert requested" : "Request revert"}
                  </button>
                )}
              </div>
              {revertRequests.length > 0 && (
                <div className="tf-repair" style={{ marginTop: 10 }}>
                  {revertRequests.slice(0, 4).map((item) => (
                    <p key={item.id} className="muted" style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                      Revert {item.status}
                      {item.requested_by_name ? ` · ${item.requested_by_name}` : ""}
                      {item.reason ? ` — ${item.reason.slice(0, 140)}` : ""}
                      {canExecuteRevert && item.status === "pending" && (
                        <>
                          <button type="button" className="tiny-btn solid" disabled={repairing} onClick={() => setRevertModal({ kind: "approve", requestId: item.id })}>
                            Approve revert
                          </button>
                          <button type="button" className="tiny-btn" disabled={repairing} onClick={() => void decideRevert(item.id, false)}>
                            Reject
                          </button>
                        </>
                      )}
                    </p>
                  ))}
                </div>
              )}
            </div>
          )}

          <div style={{ display: "flex", justifyContent: "space-between", paddingTop: 16, borderTop: "1px solid var(--border)" }}>
            <div style={{ fontSize: 13 }}><strong>Review plan</strong> gates still apply to stage moves</div>
            {architectureFailed && (
              <button type="button" className="tiny-btn solid" disabled={busy} onClick={() => void retryArchitecture()}>
                Retry architecture
              </button>
            )}
            {run.stage !== "done" && canAdvance && (
              <button type="button" className="ghost" disabled={busy} onClick={() => {
                const next = nextStage();
                if (!next) return;
                if (run.stage === "architecture") {
                  void (async () => {
                    const accepted = await advance("architecture", "architecture_accepted", true);
                    if (accepted) await advance(next);
                  })();
                  return;
                }
                void advance(next);
              }}>Advance stage →</button>
            )}
            {run.stage !== "done" && !canAdvance && !architectureFailed && (
              <p style={{ fontSize: 13, color: "var(--muted)", margin: 0 }}>
                {generatingArchitecture
                  ? "Generating architecture…"
                  : `Needs ${currentItem?.min_role || "higher"}+ role.`}
              </p>
            )}
          </div>
        </>
      )}
      {message && <div className="form-msg">{message}</div>}
      {revertModal && (
        <Modal
          eyebrow="Dangerous live change"
          title={
            revertModal.kind === "request"
              ? "Request a revert?"
              : revertModal.kind === "approve"
                ? "Approve this revert?"
                : "Revert this isolated stack?"
          }
          description={
            revertModal.kind === "request"
              ? "Org Admin or Super Admin must approve before terraform destroy runs. Describe why this isolated apply should be torn down."
              : "This destroys resources created by this isolated apply, using this project's cloud credentials. GitHub PRs are not merged or closed."
          }
          onClose={() => {
            if (!busy) setRevertModal(null);
          }}
        >
          {revertModal.kind === "request" && (
            <label className="modal-label">
              <span>Reason</span>
              <textarea
                className="objective-textarea"
                rows={4}
                value={revertReason}
                onChange={(event) => setRevertReason(event.target.value)}
                placeholder="Why should this isolated stack be reverted?"
              />
            </label>
          )}
          {message && <p className="form-msg error">{message}</p>}
          <div className="modal-actions">
            <button
              type="button"
              className="modal-btn ghost"
              disabled={busy}
              onClick={() => setRevertModal(null)}
            >
              Cancel
            </button>
            {revertModal.kind === "request" ? (
              <button
                type="button"
                className="modal-btn primary"
                disabled={busy || !revertReason.trim()}
                onClick={() => void requestOrRunRevert(revertReason)}
              >
                {busy ? "Sending…" : "Send request"}
              </button>
            ) : (
              <button
                type="button"
                className="modal-btn danger"
                disabled={busy}
                onClick={() => {
                  if (revertModal.kind === "approve") {
                    void decideRevert(revertModal.requestId, true);
                    return;
                  }
                  void requestOrRunRevert("", true);
                }}
              >
                {busy ? "Reverting…" : revertModal.kind === "approve" ? "Approve and revert" : "Revert stack"}
              </button>
            )}
          </div>
        </Modal>
      )}
    </section>
  );
}
