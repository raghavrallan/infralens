"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { getStoredUser } from "../lib/auth";
import { prettyName, timeUntil } from "../lib/dashboard";
import type { Approval, Finding } from "../lib/types";
import { DashboardShell, useDashboardContext } from "./dashboard-shell";
import { Modal, useToast } from "./modal";

const PAGE_SIZE = 25;

function canApprove(minRole?: string) {
  const order = [
    "viewer",
    "developer",
    "devops_engineer",
    "devops_lead",
    "org_admin",
    "super_admin",
  ];
  const me = getStoredUser();
  const min = minRole || "devops_engineer";
  return order.indexOf(me?.role || "viewer") >= order.indexOf(min);
}

function ApprovalsBody() {
  const {
    projectId,
    timeRange,
    setUpdated,
    setLoading,
    refreshKey,
  } = useDashboardContext();
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [expandedId, setExpandedId] = useState<string | null>(null);
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
        setVisibleCount(PAGE_SIZE);
        setUpdated(new Date());
      } finally {
        if (requestId === requestRef.current) setLoading(false);
      }
    },
    [projectId, setLoading, setUpdated, timeRange],
  );

  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [projectId, timeRange]);

  useEffect(() => {
    void loadData(true);
    const timer = window.setInterval(() => {
      if (!document.hidden) void loadData(false);
    }, 15000);
    return () => window.clearInterval(timer);
  }, [loadData, refreshKey]);

  const pendingLive = approvals.filter((approval) => !approval.expired).length;
  const visibleApprovals = approvals.slice(0, visibleCount);

  const explain = (finding?: Finding) => {
    if (!finding || !projectId) return;
    window.localStorage.setItem("projectId", projectId);
    window.localStorage.setItem(
      "pendingPrompt",
      `Explain this finding and how to fix it safely.\n\nSkill: ${prettyName(finding.skill)}\nSeverity: ${finding.severity}\nTitle: ${finding.title}\n${finding.evidence ? `Evidence: ${finding.evidence}` : ""}`,
    );
    window.location.href = "/";
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
    <section className="dash-page">
      <div className="dash-page-toolbar">
        <span className={`pill ${pendingLive ? "warn" : "off"}`}>
          {pendingLive} pending
        </span>
        <span className="hint small">
          Approving records intent only — nothing is executed automatically.
        </span>
        {approvals.length ? (
          <span className="hint small">
            Showing {Math.min(visibleCount, approvals.length)} of{" "}
            {approvals.length}
          </span>
        ) : null}
      </div>

      <div className="dash-feed">
        {!approvals.length ? (
          <div className="dash-empty">
            <h3>No approvals waiting</h3>
            <p>Change-producing findings land here, time-boxed for review.</p>
          </div>
        ) : (
          visibleApprovals.map((approval) => {
            const expanded = expandedId === approval.id;
            const evidence = approval.evidence || approval.finding?.evidence;
            const hasDetails = Boolean(
              approval.gate_rationale ||
                evidence ||
                approval.rollback ||
                approval.preflight?.summary ||
                approval.precedent?.length,
            );
            return (
              <article
                className={`dash-item approval-card${approval.expired ? " expired" : ""}`}
                key={approval.id}
              >
                <div className="finding-top">
                  <span className={`gate-badge gate-${approval.gate}`}>
                    {approval.gate_label}
                  </span>
                  {approval.finding?.severity ? (
                    <span className={`sev sev-${approval.finding.severity}`}>
                      {approval.finding.severity}
                    </span>
                  ) : null}
                  <span className="approval-expiry">
                    {approval.expired
                      ? "expired"
                      : timeUntil(approval.expires_in_seconds)}
                  </span>
                </div>
                <h3 className="finding-title">
                  {approval.finding?.title || "Finding"}
                </h3>
                <div className="finding-meta">
                  <span>{prettyName(approval.finding?.skill)}</span>
                  <span>
                    blast:{" "}
                    {approval.blast_radius ||
                      approval.finding?.blast_radius ||
                      "—"}
                  </span>
                  {approval.min_role_label ? (
                    <span>min role: {approval.min_role_label}</span>
                  ) : null}
                  {approval.break_glass_applied ? (
                    <span>break-glass active</span>
                  ) : null}
                </div>
                {expanded && hasDetails ? (
                  <div className="finding-body">
                    {approval.gate_rationale ? (
                      <>
                        <span className="label">Rationale</span>
                        {approval.gate_rationale}
                      </>
                    ) : null}
                    {evidence ? (
                      <>
                        <span className="label">Evidence</span>
                        {evidence}
                      </>
                    ) : null}
                    {approval.rollback ? (
                      <>
                        <span className="label">Rollback</span>
                        {approval.rollback}
                      </>
                    ) : null}
                    {approval.preflight?.summary ? (
                      <>
                        <span className="label">Preflight</span>
                        {approval.preflight.summary}
                      </>
                    ) : null}
                    {!!approval.precedent?.length ? (
                      <>
                        <span className="label">Precedent</span>
                        {approval.precedent
                          .slice(0, 2)
                          .map((item) => `${item.outcome}: ${item.summary}`)
                          .join(" · ")}
                      </>
                    ) : null}
                  </div>
                ) : null}
                <div className="finding-actions">
                  {hasDetails ? (
                    <button
                      type="button"
                      className="tiny-btn"
                      onClick={() =>
                        setExpandedId((current) =>
                          current === approval.id ? null : approval.id,
                        )
                      }
                    >
                      {expanded ? "Hide details" : "Show details"}
                    </button>
                  ) : null}
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
                    onClick={() =>
                      setApprovalModal({ approval, decision: "rejected" })
                    }
                  >
                    Reject
                  </button>
                  {canApprove(approval.min_role) ? (
                    <button
                      type="button"
                      className="tiny-btn solid"
                      onClick={() =>
                        setApprovalModal({ approval, decision: "approved" })
                      }
                      title={
                        approval.min_role_label
                          ? `Requires ${approval.min_role_label}+`
                          : undefined
                      }
                    >
                      Approve
                    </button>
                  ) : (
                    <span className="empty-note">
                      Needs {approval.min_role_label || approval.min_role}+
                    </span>
                  )}
                </div>
              </article>
            );
          })
        )}
        {approvals.length > visibleCount ? (
          <div className="dash-feed-more">
            <button
              type="button"
              className="tiny-btn"
              onClick={() => setVisibleCount((count) => count + PAGE_SIZE)}
            >
              Load {Math.min(PAGE_SIZE, approvals.length - visibleCount)} more
            </button>
          </div>
        ) : null}
      </div>

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
    </section>
  );
}

export function DashboardApprovalsPage() {
  return (
    <DashboardShell title="Approvals">
      <ApprovalsBody />
    </DashboardShell>
  );
}
