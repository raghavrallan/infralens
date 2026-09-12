"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import { prettyName, timeAgo, type WorkflowDraft } from "../lib/dashboard";
import type { Catalog, Run, Workflow } from "../lib/types";
import { DashboardShell, useDashboardContext } from "./dashboard-shell";
import { Modal, useToast } from "./modal";
import { ThemedSelect } from "./themed-select";

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

function WorkflowsBody({
  workflowModal,
  setWorkflowModal,
}: {
  workflowModal: Workflow | null | undefined;
  setWorkflowModal: (value: Workflow | null | undefined) => void;
}) {
  const {
    projectId,
    timeRange,
    catalog,
    setUpdated,
    setLoading,
    refreshKey,
  } = useDashboardContext();
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [runModal, setRunModal] = useState<Run | null>(null);
  const requestRef = useRef(0);
  const { showToast, Toast } = useToast();

  const loadData = useCallback(
    async (showLoader = true) => {
      if (!projectId) {
        setLoading(false);
        return;
      }
      const requestId = ++requestRef.current;
      if (showLoader) setLoading(true);
      const timeParams = new URLSearchParams({ time_range: timeRange });
      try {
        const [nextWorkflows, nextRuns] = await Promise.all([
          api<Workflow[]>(
            `/api/workflows?project_id=${encodeURIComponent(projectId)}`,
          ),
          api<Run[]>(
            `/api/runs?project_id=${encodeURIComponent(projectId)}&limit=12&${timeParams}`,
          ),
        ]);
        if (requestId !== requestRef.current) return;
        setWorkflows(nextWorkflows);
        setRuns(nextRuns);
        setUpdated(new Date());
      } finally {
        if (requestId === requestRef.current) setLoading(false);
      }
    },
    [projectId, setLoading, setUpdated, timeRange],
  );

  useEffect(() => {
    void loadData(true);
    const timer = window.setInterval(() => {
      if (!document.hidden) void loadData(false);
    }, 15000);
    return () => window.clearInterval(timer);
  }, [loadData, refreshKey]);

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

  return (
    <section className="dash-page">
      <div className="workflows-layout">
        <div className="workflows-column">
          <div className="dash-page-toolbar">
            <strong className="dash-panel-label">Definitions</strong>
            <span className="hint small">{workflows.length} workflows</span>
          </div>
          <div className="dash-feed">
            {!workflows.length ? (
              <div className="dash-empty">
                <h3>No workflows yet</h3>
                <p>Create one to start automated diagnostics.</p>
              </div>
            ) : (
              workflows.map((workflow) => (
                <article
                  className={`dash-item workflow-card${workflow.enabled ? "" : " disabled"}`}
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
                    {workflow.module_label || "Workflow"} · {workflow.environment} ·{" "}
                    {workflow.schedule_cron
                      ? `cron ${workflow.schedule_cron}`
                      : "manual"}
                  </div>
                  <div className="workflow-skills">
                    {workflow.skills.slice(0, 6).map((item) => (
                      <span className="mini-pill" key={item}>
                        {prettyName(item)}
                      </span>
                    ))}
                    {workflow.skills.length > 6 ? (
                      <span className="mini-pill">+{workflow.skills.length - 6}</span>
                    ) : null}
                  </div>
                  <div className="workflow-last">
                    Last:{" "}
                    {workflow.last_run
                      ? `${workflow.last_run.status} ${timeAgo(workflow.last_run.created_at)}`
                      : "never run"}
                  </div>
                  <div className="workflow-actions">
                    <button
                      type="button"
                      className="tiny-btn solid"
                      onClick={() => void runWorkflow(workflow.id)}
                    >
                      Run now
                    </button>
                    <button
                      type="button"
                      className="tiny-btn"
                      onClick={() => setWorkflowModal(workflow)}
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      className="tiny-btn"
                      onClick={() => void toggleWorkflow(workflow)}
                    >
                      {workflow.enabled ? "Disable" : "Enable"}
                    </button>
                    <button
                      type="button"
                      className="tiny-btn danger"
                      onClick={() => void deleteWorkflow(workflow)}
                    >
                      Delete
                    </button>
                  </div>
                </article>
              ))
            )}
          </div>
        </div>

        <div className="workflows-column">
          <div className="dash-page-toolbar">
            <strong className="dash-panel-label">Recent runs</strong>
            <span className="hint small">Click a run for its findings</span>
          </div>
          <div className="dash-feed run-list">
            {!runs.length ? (
              <div className="dash-empty">
                <h3>No runs yet</h3>
                <p>Queue a workflow to see run history here.</p>
              </div>
            ) : (
              runs.map((run) => (
                <button
                  type="button"
                  className="run-item dash-item"
                  key={run.id}
                  onClick={async () =>
                    setRunModal(await api<Run>(`/api/runs/${run.id}`))
                  }
                >
                  <div>
                    <div>{run.workflow_name || "Workflow"}</div>
                    <div className="run-meta">
                      {run.trigger} · {timeAgo(run.created_at)}
                      {run.finding_count ? ` · ${run.finding_count} findings` : ""}
                    </div>
                  </div>
                  <span className={`run-status ${run.status}`}>{run.status}</span>
                </button>
              ))
            )}
          </div>
        </div>
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
                    <div className="finding-title">{finding.title}</div>
                    <div className="finding-body">{finding.evidence}</div>
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
                type="button"
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
    </section>
  );
}

function WorkflowActions({ onCreate }: { onCreate: () => void }) {
  const { projectId } = useDashboardContext();
  return (
    <button
      type="button"
      className="primary"
      onClick={onCreate}
      disabled={!projectId}
    >
      + Workflow
    </button>
  );
}

export function DashboardWorkflowsPage() {
  const [workflowModal, setWorkflowModal] = useState<
    Workflow | null | undefined
  >(undefined);

  return (
    <DashboardShell
      title="Workflows"
      actions={<WorkflowActions onCreate={() => setWorkflowModal(null)} />}
    >
      <WorkflowsBody
        workflowModal={workflowModal}
        setWorkflowModal={setWorkflowModal}
      />
    </DashboardShell>
  );
}
