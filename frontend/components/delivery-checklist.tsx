"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { getStoredUser } from "../lib/auth";

type ChecklistItem = { stage: string; label: string; status: string; min_role?: string };
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

  const loadTasks = useCallback(async () => {
    if (!projectId) return;
    try {
      setTasks(await api<Task[]>(`/api/engineering/tasks?project_id=${encodeURIComponent(projectId)}`));
    } catch {
      setTasks([]);
    }
  }, [projectId]);

  const load = useCallback(async () => {
    if (!projectId) return;
    try {
      const runs = await api<DeliveryRun[]>(`/api/delivery/runs?project_id=${encodeURIComponent(projectId)}`);
      setRun(runs[0] || null);
    } catch {
      setRun(null);
    }
    await loadTasks();
  }, [projectId, loadTasks]);

  useEffect(() => {
    void load();
  }, [load]);

  const architectureStatus = String((run?.artifacts?.architecture_status as string) || "");
  const architectureProposal = run?.artifacts?.architecture_proposal as
    | { summary?: string; hld?: string; components?: string[]; notes?: string; tier?: string; mode?: string }
    | undefined;

  useEffect(() => {
    if (run?.stage !== "architecture" || architectureStatus !== "generating") return;
    const timer = window.setInterval(() => void load(), 2500);
    return () => window.clearInterval(timer);
  }, [run?.stage, architectureStatus, load]);

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

  const generateForTask = async (task: Task) => {
    setBusy(true);
    try {
      await api(`/api/engineering/tasks/${task.id}/generate`, {
        method: "POST",
        body: JSON.stringify({ kind: "terraform" }),
      });
      await loadTasks();
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
  const canAdvance = hasMinRole(me?.role, currentItem?.min_role)
    && !(run?.stage === "architecture" && architectureStatus === "generating");

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
              {architectureStatus === "generating" && <p className="empty-note">Generating architecture and delivery tasks…</p>}
              {architectureProposal?.summary && architectureStatus !== "generating" && (
                <p style={{ fontSize: 13 }}><strong>{architectureProposal.tier} {architectureProposal.mode}</strong> {architectureProposal.summary}</p>
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
                              {file.name} · {file.origin} · {file.validation_status || "pending"}
                            </li>
                          ))}
                        </ul>
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

          <div style={{ display: "flex", justifyContent: "space-between", paddingTop: 16, borderTop: "1px solid var(--border)" }}>
            <div style={{ fontSize: 13 }}><strong>Review plan</strong> gates still apply to stage moves</div>
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
            {run.stage !== "done" && !canAdvance && (
              <p style={{ fontSize: 13, color: "var(--muted)", margin: 0 }}>Needs {currentItem?.min_role || "higher"}+ role.</p>
            )}
          </div>
        </>
      )}
      {message && <div className="form-msg">{message}</div>}
    </section>
  );
}
