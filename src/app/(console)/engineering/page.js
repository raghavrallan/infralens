"use client";

import { useCallback, useEffect, useState } from "react";
import { Kpi, PageHead, Panel, Pill } from "@/components/ui";
import { fieldClass, ghostBtn, primaryBtn, SuiteDown, SuiteGate, SuiteProjectBar, useSuiteProject } from "@/components/suite/SuiteScreen";
import { prettyName, suiteJson } from "@/lib/suite";

const NEXT_STATUS = {
  not_started: "ready",
  ready: "in_progress",
  in_progress: "validation_required",
  validation_required: "ready_for_review",
  validation_failed: "in_progress",
  blocked: "ready",
  ready_for_review: "approved",
  approved: "completed",
};

const NEXT_STAGE = {
  ingest: "architecture",
  architecture: "terraform",
  terraform: "plan",
  plan: "apply",
  apply: "code",
  code: "done",
};

function EngineeringBody() {
  const project = useSuiteProject();
  const [health, setHealth] = useState(null);
  const [tasks, setTasks] = useState([]);
  const [run, setRun] = useState(null);
  const [docs, setDocs] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    if (!project.projectId) return;
    const [nextHealth, nextTasks, runs] = await Promise.all([
      suiteJson(`/api/engineering/health?project_id=${encodeURIComponent(project.projectId)}`),
      suiteJson(`/api/engineering/tasks?project_id=${encodeURIComponent(project.projectId)}`),
      suiteJson(`/api/delivery/runs?project_id=${encodeURIComponent(project.projectId)}`),
    ]);
    setHealth(nextHealth);
    setTasks(Array.isArray(nextTasks) ? nextTasks : []);
    setRun(Array.isArray(runs) ? runs[0] || null : null);
  }, [project.projectId]);

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

  async function startRun() {
    setBusy("start");
    setError("");
    try {
      setRun(await suiteJson("/api/delivery/runs", { method: "POST", body: { project_id: project.projectId } }));
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function saveDocs() {
    if (!run?.id) return;
    setBusy("docs");
    setError("");
    try {
      setRun(await suiteJson(`/api/delivery/runs/${run.id}/docs`, { method: "POST", body: { docs } }));
      setNotice("Docs saved on the delivery run.");
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function advance() {
    if (!run?.id || !NEXT_STAGE[run.stage]) return;
    setBusy("advance");
    setError("");
    try {
      setRun(await suiteJson(`/api/delivery/runs/${run.id}/transition`, { method: "POST", body: { to_stage: NEXT_STAGE[run.stage] } }));
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function accept(rec) {
    setBusy(rec.id);
    setError("");
    try {
      const result = await suiteJson("/api/engineering/recommendations/accept", {
        method: "POST",
        body: {
          project_id: project.projectId,
          title: rec.title,
          reason: rec.reason,
          stage: "infrastructure",
          action: rec.action || "",
        },
      });
      setNotice(result.action === "generate_terraform" ? `Generated ${result.count ?? 0} artifacts.` : "Added to the delivery checklist.");
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function moveTask(task) {
    const next = NEXT_STATUS[task.status];
    if (!next) return;
    setBusy(task.id);
    setError("");
    try {
      await suiteJson(`/api/engineering/tasks/${task.id}/transition`, { method: "POST", body: { status: next } });
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  if (project.down) return <SuiteDown />;

  const bars = health?.bars ? Object.values(health.bars) : [];

  return (
    <div className="space-y-4">
      <PageHead
        eyebrow="Agentic"
        title="Engineering"
        description="Project health, the delivery checklist, and the next task transition."
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
      {notice && <p className="text-sm text-ok">{notice}</p>}
      <div className="grid gap-3 sm:grid-cols-3">
        <Kpi label="Health" value={health ? `${health.overall}%` : "—"} hint={health?.readiness?.status || "No delivery health yet"} tone={health?.readiness?.ready ? "ok" : "warn"} />
        <Kpi label="Tasks" value={health ? `${health.task_counts?.completed || 0}/${health.task_counts?.total || tasks.length}` : tasks.length} tone="brand" />
        <Kpi label="Stage" value={run ? prettyName(run.stage) : "none"} tone="info" />
      </div>
      <Panel
        title="Delivery checklist"
        action={
          <div className="flex gap-2">
            {!run && (
              <button type="button" className={primaryBtn} disabled={busy === "start" || !project.projectId} onClick={() => void startRun()}>
                {busy === "start" ? "Starting…" : "Start delivery"}
              </button>
            )}
            {run && NEXT_STAGE[run.stage] && (
              <button type="button" className={primaryBtn} disabled={!!busy} onClick={() => void advance()}>
                Move to {prettyName(NEXT_STAGE[run.stage])}
              </button>
            )}
          </div>
        }
      >
        {health?.summary && <p className="mb-3 text-sm text-muted">{health.summary}</p>}
        {run?.stage === "ingest" && (
          <div className="mb-4">
            <label className="text-xs font-semibold text-muted">
              Requirements
              <textarea className={`${fieldClass} h-28 py-2`} value={docs} onChange={(event) => setDocs(event.target.value)} />
            </label>
            <button type="button" className={`${ghostBtn} mt-2`} disabled={busy === "docs" || !docs.trim()} onClick={() => void saveDocs()}>
              Save docs
            </button>
          </div>
        )}
        <ol className="space-y-1 text-sm">
          {(run?.checklist || health?.timeline || []).map((item) => (
            <li key={item.stage} className="flex items-center gap-2">
              <Pill tone={item.status === "done" || item.state === "done" ? "ok" : item.status === "current" || item.state === "current" ? "warn" : item.state === "blocked" ? "danger" : "muted"}>
                {item.status || item.state}
              </Pill>
              <span>{item.label || prettyName(item.stage)}</span>
            </li>
          ))}
          {!run && !health?.timeline?.length && <li className="text-muted">Start a delivery run to build the checklist.</li>}
        </ol>
        {bars.length > 0 && (
          <ul className="mt-4 space-y-2">
            {bars.map((bar) => (
              <li key={bar.label} className="text-sm">
                <div className="flex justify-between text-xs text-muted">
                  <span>{bar.label}</span>
                  <span>{bar.percent}%</span>
                </div>
                <div className="mt-1 h-1.5 rounded-full bg-canvas">
                  <div className="h-1.5 rounded-full bg-brand" style={{ width: `${Math.max(0, Math.min(100, bar.percent || 0))}%` }} />
                </div>
              </li>
            ))}
          </ul>
        )}
      </Panel>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Blockers">
          {(health?.blockers || []).length === 0 && <p className="text-sm text-muted">No blockers.</p>}
          <ul className="space-y-2 text-sm">
            {(health?.blockers || []).map((item) => (
              <li key={item.id}>{item.title}</li>
            ))}
          </ul>
        </Panel>
        <Panel title="Recommendations">
          {(health?.recommendations || []).length === 0 && <p className="text-sm text-muted">No recommendations yet.</p>}
          <ul className="space-y-3 text-sm">
            {(health?.recommendations || []).map((rec) => (
              <li key={rec.id}>
                <div className="font-semibold">{rec.title}</div>
                <p className="text-muted">{rec.reason}</p>
                {(rec.action === "add_task" || rec.action === "open_task" || rec.action === "generate_terraform") && (
                  <button type="button" className={`${primaryBtn} mt-2`} disabled={busy === rec.id} onClick={() => void accept(rec)}>
                    {rec.action === "generate_terraform" ? "Generate artifacts" : "Add to checklist"}
                  </button>
                )}
              </li>
            ))}
          </ul>
        </Panel>
      </div>
      <Panel title="Tasks">
        {tasks.length === 0 && <p className="text-sm text-muted">No delivery tasks yet.</p>}
        <div className="space-y-2">
          {tasks.map((task) => (
            <div key={task.id} className="flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-line px-3 py-2 text-sm">
              <div>
                <div className="font-semibold">{task.title}</div>
                <div className="text-xs text-muted">{task.stage_label || prettyName(task.stage)} · {prettyName(task.status)}</div>
              </div>
              {NEXT_STATUS[task.status] && (
                <button type="button" className={ghostBtn} disabled={busy === task.id} onClick={() => void moveTask(task)}>
                  {prettyName(NEXT_STATUS[task.status])}
                </button>
              )}
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}

export default function EngineeringPage() {
  return (
    <SuiteGate>
      <EngineeringBody />
    </SuiteGate>
  );
}
