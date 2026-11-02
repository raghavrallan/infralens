"use client";

import { useCallback, useEffect, useState } from "react";
import { PageHead, Panel, Pill } from "@/components/ui";
import { dangerBtn, fieldClass, primaryBtn, SuiteDown, SuiteGate, SuiteProjectBar, useSuite, useSuiteProject } from "@/components/suite/SuiteScreen";
import { hasMinRole, suiteJson } from "@/lib/suite";

function BreakGlassBody() {
  const suite = useSuite();
  const project = useSuiteProject();
  const [status, setStatus] = useState(null);
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const canManage = hasMinRole(suite?.user?.role, "devops_lead");

  const load = useCallback(async () => {
    if (!project.projectId) return;
    setStatus(await suiteJson(`/api/break-glass/status?project_id=${encodeURIComponent(project.projectId)}`));
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

  async function open() {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await suiteJson("/api/break-glass/open", {
        method: "POST",
        body: { project_id: project.projectId, reason, ttl_minutes: 60 },
      });
      setReason("");
      setMessage("Break-glass opened for 60 minutes.");
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function expire() {
    setBusy(true);
    setError("");
    try {
      await suiteJson(`/api/break-glass/expire?project_id=${encodeURIComponent(project.projectId)}`, { method: "POST" });
      setMessage("Break-glass expired.");
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (project.down) return <SuiteDown />;
  const active = status?.active && typeof status.active === "object" ? status.active : null;

  return (
    <div className="space-y-4">
      <PageHead
        eyebrow="Agentic"
        title="Break-glass"
        description="A timed gate downgrade for this skills project. DevOps Lead and above can open or expire it."
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
      {message && <p className="text-sm text-ok">{message}</p>}
      <Panel title="Session" action={<Pill tone={active ? "warn" : "muted"}>{active ? "active" : "off"}</Pill>}>
        {!canManage && <p className="mb-3 text-sm text-muted">Your skills role cannot open break-glass. Status is still shown.</p>}
        {active ? (
          <>
            <p className="text-sm">
              Opened by {active.opened_by || "unknown"}. {active.reason || ""}
              {active.expires_at ? ` Expires ${active.expires_at}.` : ""}
            </p>
            {canManage && (
              <button type="button" className={`${dangerBtn} mt-3`} disabled={busy} onClick={() => void expire()}>
                Expire now
              </button>
            )}
          </>
        ) : (
          <div className="max-w-lg">
            <label className="text-xs font-semibold text-muted">
              Reason
              <textarea className={`${fieldClass} h-24 py-2`} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Why this gate should drop" />
            </label>
            <button type="button" className={`${primaryBtn} mt-3`} disabled={busy || !canManage || !reason.trim() || !project.projectId} onClick={() => void open()}>
              Open session
            </button>
          </div>
        )}
        {(status?.history || []).length > 0 && (
          <ul className="mt-4 space-y-1 text-xs text-muted">
            {status.history.slice(0, 6).map((item) => (
              <li key={item.id || item.expires_at}>{item.reason || "Session"} · {item.opened_by || ""}</li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}

export default function BreakGlassPage() {
  return (
    <SuiteGate>
      <BreakGlassBody />
    </SuiteGate>
  );
}
