"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { getStoredUser } from "../lib/auth";
import { prettyName, timeUntil } from "../lib/dashboard";
import type { Approval, Finding } from "../lib/types";
import { DashboardShell, useDashboardContext } from "./dashboard-shell";
import { Modal, useToast } from "./modal";

function ApprovalsBody() {
  const {
    projectId,
    timeRange,
    setUpdated,
    setLoading,
    refreshKey,
  } = useDashboardContext();
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [approvalModal, setApprovalModal] = useState<{
    approval: Approval;
    decision: "approved" | "rejected";
  } | null>(null);
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
        const nextApprovals = await api<Approval[]>(
          `/api/approvals?project_id=${encodeURIComponent(projectId)}&status=pending&${timeParams}`,
        );
        if (requestId !== requestRef.current) return;
        setApprovals(nextApprovals);
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

  const pendingLive = approvals.filter((approval) => !approval.expired).length;

  const explain = (finding?: Finding) => {
    if (!finding || !projectId) return;
    window.localStorage.setItem("projectId", projectId);
    window.localStorage.setItem(
      "pendingPrompt",
      `Explain this finding and how to fix it safely.\n\nSkill: ${prettyName(finding.skill)}\nSeverity: ${finding.severity}\nTitle: ${finding.title}\n${finding.evidence ? `Evidence: ${finding.evidence}` : ""}`,
    );
    window.location.href = "/";
  };

  const decideApproval = (
    approval: Approval,
    decision: "approved" | "rejected",
  ) => {
    setApprovalModal({ approval, decision });
  };

  const executeApproval = async () => {
    if (!approvalModal) return;
    const { approval, decision } = approvalModal;
    setApprovalModal(null);
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

  return (
    <>
      <section className="dash-col">
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
                    type="button"
                    className="tiny-btn"
                    onClick={() => explain(approval.finding)}
                  >
                    Chat to resolve
                  </button>
                  <button
                    type="button"
                    className="tiny-btn danger"
                    onClick={() => void decideApproval(approval, "rejected")}
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
                        type="button"
                        className="tiny-btn solid"
                        onClick={() => void decideApproval(approval, "approved")}
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
      </section>

      {approvalModal && (
        <Modal
          title={`${approvalModal.decision === "approved" ? "Approve" : "Reject"} this gated finding?`}
          description={`Are you sure you want to ${approvalModal.decision} this finding?`}
          onClose={() => setApprovalModal(null)}
        >
          <div className="modal-body">
            <div className="modal-actions">
              <button
                type="button"
                className="modal-btn ghost"
                onClick={() => setApprovalModal(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                className={`modal-btn ${approvalModal.decision === "approved" ? "primary" : "danger"}`}
                onClick={() => void executeApproval()}
              >
                {approvalModal.decision === "approved" ? "Approve" : "Reject"}
              </button>
            </div>
          </div>
        </Modal>
      )}
      {Toast}
    </>
  );
}

export function DashboardApprovalsPage() {
  return (
    <DashboardShell title="Approvals">
      <ApprovalsBody />
    </DashboardShell>
  );
}
