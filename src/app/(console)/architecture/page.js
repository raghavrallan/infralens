"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { PageHead, Panel, Pill } from "@/components/ui";
import { ghostBtn, primaryBtn, SuiteDown, SuiteGate, SuiteProjectBar, useSuiteProject } from "@/components/suite/SuiteScreen";
import { prettyName, suiteJson } from "@/lib/suite";

const STAGES = ["ingest", "architecture", "terraform", "plan", "apply", "code", "done"];

function ArchitectureBody() {
  const project = useSuiteProject();
  const [runs, setRuns] = useState([]);
  const [delivery, setDelivery] = useState(null);
  const [expanded, setExpanded] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!project.projectId) return;
    const [architect, deliveries] = await Promise.all([
      suiteJson(`/api/architecture/runs?project_id=${encodeURIComponent(project.projectId)}&limit=8`),
      suiteJson(`/api/delivery/runs?project_id=${encodeURIComponent(project.projectId)}`),
    ]);
    setRuns(Array.isArray(architect) ? architect : []);
    setDelivery(Array.isArray(deliveries) ? deliveries[0] || null : null);
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

  async function start() {
    setBusy(true);
    setError("");
    try {
      const created = await suiteJson("/api/delivery/runs", { method: "POST", body: { project_id: project.projectId } });
      setDelivery(created);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function generate() {
    if (!delivery?.id) return;
    setBusy(true);
    setError("");
    try {
      setDelivery(await suiteJson(`/api/delivery/runs/${delivery.id}/transition`, { method: "POST", body: { to_stage: "architecture" } }));
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function retry() {
    if (!delivery?.id) return;
    setBusy(true);
    setError("");
    try {
      setDelivery(await suiteJson(`/api/delivery/runs/${delivery.id}/architecture/retry`, { method: "POST" }));
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (project.down) return <SuiteDown />;

  const architectureStatus = String(delivery?.artifacts?.architecture_status || "");
  const proposal = delivery?.artifacts?.architecture_proposal;
  const checklist = delivery?.checklist?.length ? delivery.checklist : STAGES.map((stage) => ({ stage, label: prettyName(stage), status: delivery?.stage === stage ? "current" : "pending" }));

  return (
    <div className="space-y-4">
      <PageHead
        eyebrow="Agentic"
        title="Architecture"
        description="Solution Architect runs, plus the delivery stage that enqueues architecture generation."
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
      <Panel
        title="Delivery architecture"
        action={
          <div className="flex flex-wrap gap-2">
            {!delivery && (
              <button type="button" className={primaryBtn} disabled={busy || !project.projectId} onClick={() => void start()}>
                {busy ? "Starting…" : "Start delivery run"}
              </button>
            )}
            {delivery?.stage === "ingest" && (
              <button type="button" className={primaryBtn} disabled={busy} onClick={() => void generate()}>
                Generate architecture
              </button>
            )}
            {architectureStatus === "failed" && (
              <button type="button" className={ghostBtn} disabled={busy} onClick={() => void retry()}>
                Retry architecture
              </button>
            )}
            <Link href="/chat" className={ghostBtn} onClick={() => window.localStorage.setItem("suiteSkill", "solution_architect")}>
              Open in chat
            </Link>
          </div>
        }
      >
        {!delivery && <p className="text-sm text-muted">No delivery run yet. Start one, then move it to the architecture stage.</p>}
        {delivery && (
          <>
            <p className="text-sm text-muted">
              Stage {prettyName(delivery.stage)} · run {delivery.status}
              {architectureStatus ? ` · architecture ${architectureStatus}` : ""}
            </p>
            {proposal?.summary && <p className="mt-2 text-sm">{proposal.summary}</p>}
            <ol className="mt-3 space-y-1 text-sm">
              {checklist.map((item) => (
                <li key={item.stage} className="flex items-center gap-2">
                  <Pill tone={item.status === "done" ? "ok" : item.status === "current" ? "warn" : "muted"}>{item.status}</Pill>
                  <span>{item.label || prettyName(item.stage)}</span>
                </li>
              ))}
            </ol>
          </>
        )}
      </Panel>
      <Panel title="Solution Architect runs">
        {runs.length === 0 && <p className="text-sm text-muted">No architecture runs yet.</p>}
        <div className="space-y-3">
          {runs.map((item) => {
            const frameworks = item.architecture?.stack?.frameworks || [];
            const components = item.architecture?.components || [];
            return (
              <article key={item.id} className="rounded-2xl border border-line px-3 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Pill tone="info">{item.tier || "tier"} · {item.mode || "mode"}</Pill>
                  <Pill tone={item.status === "ready" ? "ok" : "muted"}>{item.status || "unknown"}</Pill>
                </div>
                <h3 className="mt-2 text-sm font-semibold">{item.objective || "Architecture run"}</h3>
                {item.architecture?.cloud && (
                  <p className="mt-1 text-xs text-muted">
                    {item.architecture.cloud}
                    {frameworks.length ? ` · ${frameworks.join(", ")}` : ""}
                  </p>
                )}
                {expanded === item.id && (
                  <div className="mt-3 space-y-2 text-sm">
                    {item.architecture?.analysis?.brownfield && <p>{item.architecture.analysis.brownfield}</p>}
                    {components.length > 0 && (
                      <ul className="list-disc pl-5">
                        {components.map((component, index) => (
                          <li key={`${component.name || "component"}-${index}`}>
                            {component.name || component.service || "Component"}
                            {component.purpose ? ` — ${component.purpose}` : ""}
                          </li>
                        ))}
                      </ul>
                    )}
                    {(item.decisions || []).map((decision) => (
                      <p key={decision.id}>
                        {decision.title}
                        {decision.gate_decision ? ` · ${decision.gate_decision}` : ""}
                      </p>
                    ))}
                  </div>
                )}
                <button type="button" className={`${ghostBtn} mt-3`} onClick={() => setExpanded((current) => (current === item.id ? "" : item.id))}>
                  {expanded === item.id ? "Hide" : "Summary"}
                </button>
              </article>
            );
          })}
        </div>
      </Panel>
    </div>
  );
}

export default function ArchitecturePage() {
  return (
    <SuiteGate>
      <ArchitectureBody />
    </SuiteGate>
  );
}
