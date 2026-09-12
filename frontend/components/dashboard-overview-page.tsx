"use client";

/* eslint-disable @next/next/no-html-link-for-pages */
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import {
  numberValue,
  type DashboardSummary,
} from "../lib/dashboard";
import { DashboardShell, useDashboardContext } from "./dashboard-shell";
import { DeliveryChecklist } from "./delivery-checklist";
import { MemoryStrip } from "./memory-strip";

function OverviewBody() {
  const {
    projectId,
    timeRange,
    azureConfigured,
    setUpdated,
    setLoading,
    refreshKey,
  } = useDashboardContext();
  const [summary, setSummary] = useState<DashboardSummary>({});
  const requestRef = useRef(0);

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
        const nextSummary = await api<DashboardSummary>(
          `/api/dashboard/summary?project_id=${encodeURIComponent(projectId)}&${timeParams}`,
        );
        if (requestId !== requestRef.current) return;
        setSummary(nextSummary);
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

  const runCounts = (summary.runs_by_status || {}) as Record<string, unknown>;
  const severityCounts = (summary.findings_by_severity || {}) as Record<string, unknown>;
  const runTotal = Object.values(runCounts).reduce<number>(
    (total, value) => total + numberValue(value),
    0,
  );
  const openFindings = numberValue(summary.open_findings);
  const pendingApprovals = numberValue(summary.pending_approvals);
  const workflowEnabled = numberValue(summary.workflows_enabled);
  const workflowTotal = numberValue(summary.workflows_total);

  return (
    <>
      {azureConfigured === false ? (
        <p className="form-msg" style={{ marginBottom: 16 }}>
          Platform Azure OpenAI is not configured. Chat, Solution Architect, and
          scheduled workflows will fail until you add the endpoint and API key in{" "}
          <a href="/settings/">Settings</a>.
        </p>
      ) : null}

      <section className="dash-tiles">
        <a className="tile tile-link" href="/dashboard/findings/">
          <div className="tile-top">
            <div className="tile-icon tile-icon-blue">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="11" cy="11" r="8" />
                <line x1="21" y1="21" x2="16.65" y2="16.65" />
              </svg>
            </div>
            <div>
              <div className="tile-label">Open Findings</div>
              <div className="tile-value">{openFindings}</div>
              <div className="tile-sub">Open the findings inbox</div>
            </div>
          </div>
          <div className="tile-breakdown">
            <span className="sev sev-critical">C {numberValue(severityCounts.critical)}</span>
            <span className="sev sev-high">H {numberValue(severityCounts.high)}</span>
            <span className="sev sev-medium">M {numberValue(severityCounts.medium)}</span>
            <span className="sev sev-low">L {numberValue(severityCounts.low)}</span>
          </div>
        </a>

        <a
          className={`tile tile-link${pendingApprovals ? " tile-warn" : ""}`}
          href="/dashboard/approvals/"
        >
          <div className="tile-top">
            <div className="tile-icon tile-icon-orange">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
              </svg>
            </div>
            <div>
              <div className="tile-label">Awaiting Approval</div>
              <div className="tile-value">{pendingApprovals}</div>
              <div className="tile-sub">Review gated findings</div>
            </div>
          </div>
        </a>

        <a className="tile tile-link" href="/dashboard/workflows/">
          <div className="tile-top">
            <div className="tile-icon tile-icon-green">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
              </svg>
            </div>
            <div>
              <div className="tile-label">Workflows</div>
              <div className="tile-value">
                {workflowEnabled}
                <span className="tile-value-denom"> / {workflowTotal}</span>
              </div>
              <div className="tile-sub">Enabled / Total</div>
            </div>
          </div>
        </a>

        <a
          className={`tile tile-link${numberValue(runCounts.failed) ? " tile-warn" : ""}`}
          href="/dashboard/workflows/"
        >
          <div className="tile-top">
            <div className="tile-icon tile-icon-blue">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polygon points="5 3 19 12 5 21 5 3" />
              </svg>
            </div>
            <div>
              <div className="tile-label">Runs</div>
              <div className="tile-value">{runTotal}</div>
              <div className="tile-sub">
                Failed {numberValue(runCounts.failed)} · Succeeded {numberValue(runCounts.succeeded)}
              </div>
            </div>
          </div>
        </a>
      </section>

      <section className="dash-overview-main">
        {projectId ? <Suspense fallback={<div className="empty-note">Loading delivery…</div>}>
          <DeliveryChecklist projectId={projectId} />
        </Suspense> : (
          <div className="empty-note">Select a project to open delivery.</div>
        )}
        {projectId ? <MemoryStrip projectId={projectId} /> : null}
      </section>
    </>
  );
}

export function DashboardOverviewPage() {
  return (
    <DashboardShell title="Overview">
      <OverviewBody />
    </DashboardShell>
  );
}
