"use client";

import { useCallback, useEffect, useState } from "react";
import { PageHead, Panel, Pill, stateTone } from "@/components/ui";
import { dangerBtn, ghostBtn, primaryBtn, SuiteDown, SuiteGate, SuiteProjectBar, useSuiteProject } from "@/components/suite/SuiteScreen";
import { prettyName, suiteJson, timeAgo } from "@/lib/suite";

function WorkflowsBody() {
  const project = useSuiteProject();
  const [workflows, setWorkflows] = useState([]);
  const [runs, setRuns] = useState([]);
  const [skills, setSkills] = useState([]);
  const [draft, setDraft] = useState({ name: "", skills: "", environment: "prod" });
  const [selectedRun, setSelectedRun] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    if (!project.projectId) return;
    const [nextWorkflows, nextRuns] = await Promise.all([
      suiteJson(`/api/workflows?project_id=${encodeURIComponent(project.projectId)}`),
      suiteJson(`/api/runs?project_id=${encodeURIComponent(project.projectId)}&limit=12&time_range=all`),
    ]);
    setWorkflows(Array.isArray(nextWorkflows) ? nextWorkflows : []);
    setRuns(Array.isArray(nextRuns) ? nextRuns : []);
  }, [project.projectId]);

  useEffect(() => {
    suiteJson("/api/skills")
      .then((list) => setSkills(Array.isArray(list) ? list : []))
      .catch(() => setSkills([]));
  }, []);

  useEffect(() => {
    if (!project.projectId) return undefined;
    let cancel = false;
    const timer = window.setTimeout(() => {
      load().catch((err) => {
        if (!cancel) setError(err.message);
      });
    }, 0);
    return () => {
      cancel = true;
      window.clearTimeout(timer);
    };
  }, [load, project.projectId]);

  async function runWorkflow(id) {
    setBusy(id);
    setError("");
    try {
      await suiteJson(`/api/workflows/${id}/run`, { method: "POST" });
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function toggleWorkflow(workflow) {
    setError("");
    try {
      await suiteJson(`/api/workflows/${workflow.id}`, { method: "PATCH", body: { enabled: !workflow.enabled } });
      await load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function createWorkflow(event) {
    event.preventDefault();
    if (!project.projectId) return;
    setBusy("create");
    setError("");
    try {
      const names = draft.skills.split(",").map((item) => item.trim()).filter(Boolean);
      await suiteJson(`/api/workflows?project_id=${encodeURIComponent(project.projectId)}`, {
        method: "POST",
        body: { name: draft.name, skills: names, environment: draft.environment, enabled: true },
      });
      setDraft({ name: "", skills: "", environment: "prod" });
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function openRun(id) {
    setError("");
    try {
      setSelectedRun(await suiteJson(`/api/runs/${id}`));
    } catch (err) {
      setError(err.message);
    }
  }

  if (project.down) return <SuiteDown />;

  return (
    <div className="space-y-4">
      <PageHead
        eyebrow="Agentic"
        title="Workflows"
        description="Definitions for this skills project. Run now enqueues a job when Azure or AWS is connected."
        action={
          <SuiteProjectBar loading={project.loading} loadError={project.error}
            projects={project.projects}
            projectId={project.projectId}
            onChange={project.selectProject}
            onCreated={(created) => {
              project.setProjects((current) => [...current, created]);
              project.selectProject(created.id);
            }}
          />
        }
      />
      {error && <p className="text-sm text-danger">{error}</p>}
      <Panel title="New workflow">
        <form className="grid gap-3 md:grid-cols-4" onSubmit={createWorkflow}>
          <input className="h-10 rounded-2xl border border-line px-3 text-sm" placeholder="Name" value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} required />
          <input className="h-10 rounded-2xl border border-line px-3 text-sm md:col-span-2" placeholder="Skills, comma separated" list="suite-skills" value={draft.skills} onChange={(event) => setDraft({ ...draft, skills: event.target.value })} />
          <datalist id="suite-skills">
            {skills.map((item) => (
              <option key={item.name} value={item.name} />
            ))}
          </datalist>
          <select className="h-10 rounded-2xl border border-line bg-white px-3 text-sm" value={draft.environment} onChange={(event) => setDraft({ ...draft, environment: event.target.value })}>
            <option value="dev">dev</option>
            <option value="staging">staging</option>
            <option value="prod">prod</option>
          </select>
          <button type="submit" className={primaryBtn} disabled={busy === "create" || !project.projectId}>
            {busy === "create" ? "Saving…" : "Create"}
          </button>
        </form>
      </Panel>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title={`${workflows.length} workflows`}>
          {workflows.length === 0 && <p className="text-sm text-muted">No workflows yet.</p>}
          <div className="space-y-3">
            {workflows.map((workflow) => (
              <article key={workflow.id} className="rounded-2xl border border-line px-3 py-3">
                <div className="flex items-center justify-between gap-2">
                  <h3 className="text-sm font-semibold">{workflow.name}</h3>
                  <Pill tone={workflow.enabled ? "ok" : "muted"}>{workflow.enabled ? "on" : "off"}</Pill>
                </div>
                <p className="mt-1 text-xs text-muted">
                  {workflow.module_label || "Workflow"} · {workflow.environment} · {workflow.schedule_cron ? `cron ${workflow.schedule_cron}` : "manual"}
                </p>
                <p className="mt-1 text-xs text-muted">
                  Last: {workflow.last_run ? `${workflow.last_run.status} ${timeAgo(workflow.last_run.created_at)}` : "never run"}
                </p>
                <div className="mt-2 flex flex-wrap gap-1">
                  {(workflow.skills || []).slice(0, 6).map((item) => (
                    <Pill key={item} tone="muted">{prettyName(item)}</Pill>
                  ))}
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <button type="button" className={primaryBtn} disabled={busy === workflow.id} onClick={() => void runWorkflow(workflow.id)}>
                    {busy === workflow.id ? "Queuing…" : "Run now"}
                  </button>
                  <button type="button" className={ghostBtn} onClick={() => void toggleWorkflow(workflow)}>
                    {workflow.enabled ? "Disable" : "Enable"}
                  </button>
                </div>
              </article>
            ))}
          </div>
        </Panel>
        <Panel title="Recent runs">
          {runs.length === 0 && <p className="text-sm text-muted">No runs yet.</p>}
          <div className="space-y-2">
            {runs.map((run) => (
              <button key={run.id} type="button" onClick={() => void openRun(run.id)} className="flex w-full items-center justify-between rounded-2xl border border-line px-3 py-2 text-left text-sm hover:bg-canvas">
                <span>
                  <span className="font-semibold">{run.workflow_name || run.id}</span>
                  <span className="block text-xs text-muted">{timeAgo(run.created_at)} · {run.finding_count || 0} findings</span>
                </span>
                <Pill tone={stateTone(run.status)}>{run.status}</Pill>
              </button>
            ))}
          </div>
          {selectedRun && (
            <div className="mt-4 border-t border-line pt-3 text-sm">
              <div className="font-semibold">{selectedRun.workflow_name || selectedRun.id}</div>
              {selectedRun.error && <p className="mt-1 text-danger">{selectedRun.error}</p>}
              <ul className="mt-2 space-y-1">
                {(selectedRun.findings || []).map((finding) => (
                  <li key={finding.id}>{finding.severity}: {finding.title}</li>
                ))}
                {(selectedRun.findings || []).length === 0 && <li className="text-muted">This run has no findings.</li>}
              </ul>
              <button type="button" className={`${dangerBtn} mt-3`} onClick={() => setSelectedRun(null)}>Close</button>
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}

export default function WorkflowsPage() {
  return (
    <SuiteGate>
      <WorkflowsBody />
    </SuiteGate>
  );
}
