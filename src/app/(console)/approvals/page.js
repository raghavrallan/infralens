"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Kpi, PageHead, Panel, Pill } from "@/components/ui";
import { dangerBtn, ghostBtn, primaryBtn, SuiteDown, SuiteGate, SuiteProjectBar, useSuite, useSuiteProject } from "@/components/suite/SuiteScreen";
import { hasMinRole, prettyName, suiteJson, timeUntil } from "@/lib/suite";

function ApprovalsBody() {
  const suite = useSuite();
  const project = useSuiteProject();
  const [approvals, setApprovals] = useState([]);
  const [expanded, setExpanded] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!project.projectId) return undefined;
    let cancel = false;
    const timer = window.setTimeout(() => setLoading(true), 0);
    suiteJson(`/api/approvals?project_id=${encodeURIComponent(project.projectId)}&status=pending&time_range=all`)
      .then((list) => {
        if (!cancel) setApprovals(Array.isArray(list) ? list : []);
      })
      .catch((err) => {
        if (!cancel) setError(err.message);
      })
      .finally(() => {
        if (!cancel) setLoading(false);
      });
    return () => {
      cancel = true;
      window.clearTimeout(timer);
    };
  }, [project.projectId]);

  async function decide(approval, decision) {
    setError("");
    setNotice("");
    try {
      await suiteJson(`/api/approvals/${approval.id}/decide`, { method: "POST", body: { decision } });
      setApprovals((current) => current.filter((item) => item.id !== approval.id));
      setNotice(decision === "approved" ? "Approval recorded. Nothing was executed." : "Rejection recorded.");
    } catch (err) {
      setError(err.message);
    }
  }

  if (project.down) return <SuiteDown />;

  const live = approvals.filter((item) => !item.expired).length;

  return (
    <div className="space-y-4">
      <PageHead
        eyebrow="Agentic"
        title="Approvals"
        description="Pending gates. Approving records the decision. The suite does not execute the change from this inbox."
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
      <Kpi label="Pending" value={live} tone={live ? "warn" : "ok"} hint="Expired rows stay visible until you refresh." />
      {error && <p className="text-sm text-danger">{error}</p>}
      {notice && <p className="text-sm text-ok">{notice}</p>}
      <Panel>
        {loading && <p className="text-sm text-muted">Loading approvals…</p>}
        {!loading && approvals.length === 0 && <p className="text-sm text-muted">No approvals waiting.</p>}
        <div className="space-y-3">
          {approvals.map((approval) => {
            const evidence = approval.evidence || approval.finding?.evidence;
            const allowed = hasMinRole(suite?.user?.role, approval.min_role || "devops_engineer");
            return (
              <article key={approval.id} className="rounded-2xl border border-line px-3 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Pill tone={approval.gate === "block" ? "danger" : "warn"}>{approval.gate_label || approval.gate}</Pill>
                  {approval.finding?.severity && <Pill tone="info">{approval.finding.severity}</Pill>}
                  <span className="text-xs text-muted">{approval.expired ? "expired" : timeUntil(approval.expires_in_seconds)}</span>
                  {approval.break_glass_applied && <Pill tone="warn">break-glass</Pill>}
                </div>
                <h3 className="mt-2 text-sm font-semibold">{approval.finding?.title || "Finding"}</h3>
                <p className="mt-1 text-xs text-muted">
                  {prettyName(approval.finding?.skill)}
                  {approval.min_role_label ? ` · min role ${approval.min_role_label}` : ""}
                </p>
                {expanded === approval.id && (
                  <div className="mt-3 space-y-2 text-sm">
                    {approval.gate_rationale && <p><span className="font-semibold">Rationale. </span>{approval.gate_rationale}</p>}
                    {evidence && <p><span className="font-semibold">Evidence. </span>{evidence}</p>}
                    {approval.rollback && <p><span className="font-semibold">Rollback. </span>{approval.rollback}</p>}
                    {approval.recommended_action && <p><span className="font-semibold">Recommended action. </span>{approval.recommended_action}</p>}
                  </div>
                )}
                <div className="mt-3 flex flex-wrap gap-2">
                  <button type="button" className={ghostBtn} onClick={() => setExpanded((current) => (current === approval.id ? "" : approval.id))}>
                    {expanded === approval.id ? "Hide" : "Details"}
                  </button>
                  <Link href="/chat" className={ghostBtn} onClick={() => window.localStorage.setItem("projectId", project.projectId)}>
                    Chat
                  </Link>
                  <button type="button" className={dangerBtn} onClick={() => void decide(approval, "rejected")}>Reject</button>
                  {allowed ? (
                    <button type="button" className={primaryBtn} onClick={() => void decide(approval, "approved")}>Approve</button>
                  ) : (
                    <span className="text-xs text-muted">Needs {approval.min_role_label || approval.min_role || "devops engineer"} or above</span>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      </Panel>
    </div>
  );
}

export default function ApprovalsPage() {
  return (
    <SuiteGate>
      <ApprovalsBody />
    </SuiteGate>
  );
}
