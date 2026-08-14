"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { getStoredUser } from "../lib/auth";

type ChecklistItem = {
  stage: string;
  label: string;
  status: string;
  min_role?: string;
};

type DeliveryRun = {
  id: string;
  stage: string;
  status: string;
  checklist: ChecklistItem[];
  next_actions: string[];
  artifacts?: Record<string, unknown>;
};

const ROLE_ORDER = [
  "viewer",
  "developer",
  "devops_engineer",
  "devops_lead",
  "org_admin",
  "super_admin",
];

function hasMinRole(userRole: string | undefined, minimum?: string) {
  if (!minimum) return true;
  return ROLE_ORDER.indexOf(userRole || "viewer") >= ROLE_ORDER.indexOf(minimum);
}

export function DeliveryChecklist({ projectId }: { projectId: string }) {
  const me = getStoredUser();
  const [run, setRun] = useState<DeliveryRun | null>(null);
  const [docs, setDocs] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!projectId) return;
    try {
      const runs = await api<DeliveryRun[]>(
        `/api/delivery/runs?project_id=${encodeURIComponent(projectId)}`,
      );
      setRun(runs[0] || null);
    } catch {
      setRun(null);
    }
  }, [projectId]);

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
      const created = await api<DeliveryRun>("/api/delivery/runs", {
        method: "POST",
        body: JSON.stringify({ project_id: projectId }),
      });
      setRun(created);
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
      const updated = await api<DeliveryRun>(`/api/delivery/runs/${run.id}/docs`, {
        method: "POST",
        body: JSON.stringify({ docs }),
      });
      setRun(updated);
      setMessage("Docs ingested.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Ingest failed");
    } finally {
      setBusy(false);
    }
  };

  const advance = async (toStage: string, artifactKey?: string, artifactValue?: unknown) => {
    if (!run) return;
    setBusy(true);
    setMessage("");
    try {
      const updated = await api<DeliveryRun>(`/api/delivery/runs/${run.id}/transition`, {
        method: "POST",
        body: JSON.stringify({
          to_stage: toStage,
          artifact_key: artifactKey,
          artifact_value: artifactValue,
        }),
      });
      setRun(updated);
      return updated;
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Transition failed");
      return null;
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
    <section className="card delivery-checklist" style={{ padding: '24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '32px' }}>
        <div>
          <h3 style={{ margin: '0 0 4px 0', fontSize: '18px' }}>Delivery checklist</h3>
          <p style={{ margin: 0, color: 'var(--muted)', fontSize: '14px' }}>Track your delivery progress across all stages.</p>
        </div>
        {!run ? (
          <button type="button" className="tiny-btn solid" disabled={busy} onClick={() => void start()}>
            Start delivery
          </button>
        ) : (
          <div style={{ background: 'var(--success-subtle)', padding: '6px 12px', borderRadius: '8px', border: '1px solid var(--success-border, var(--success))', display: 'flex', flexDirection: 'column', alignItems: 'flex-end', minWidth: '100px' }}>
            <span style={{ color: 'var(--success)', fontSize: '11px', fontWeight: '600', marginBottom: '2px' }}>Current stage</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--success)', fontWeight: '600', fontSize: '13px' }}>
              <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: 'var(--success)' }} />
              {run.stage.charAt(0).toUpperCase() + run.stage.slice(1)}
            </div>
          </div>
        )}
      </div>

      {!run ? (
        <p className="empty-note">Docs → architecture → Terraform PR → gated apply → code PR.</p>
      ) : (
        <>
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '48px' }}>
            <div style={{ display: 'flex', alignItems: 'center', flex: 1, paddingRight: '48px', paddingTop: '8px' }}>
              {run.checklist.map((item, i) => {
                const isDone = item.status === "done";
                const isCurrent = item.status === "current";
                const circleColor = isDone ? "var(--primary)" : "transparent";
                const borderColor = isDone || isCurrent ? "var(--primary)" : "var(--border)";
                const textColor = isDone || isCurrent ? "var(--primary)" : "var(--muted)";
                
                return (
                  <div key={item.stage} style={{ display: 'flex', alignItems: 'center', flex: i === run.checklist.length - 1 ? 'none' : 1 }}>
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', position: 'relative' }}>
                      <div style={{ width: '36px', height: '36px', borderRadius: '50%', background: circleColor, border: `2px solid ${borderColor}`, display: 'flex', alignItems: 'center', justifyContent: 'center', color: isDone ? '#fff' : textColor, fontWeight: '600', fontSize: '14px', zIndex: 1 }}>
                        {isDone ? <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3"><polyline points="20 6 9 17 4 12"></polyline></svg> : i + 1}
                      </div>
                      <span style={{ position: 'absolute', top: '44px', fontSize: '13px', fontWeight: '500', color: textColor, whiteSpace: 'nowrap' }}>
                        {item.label}
                      </span>
                    </div>
                    {i < run.checklist.length - 1 && (
                      <div style={{ flex: 1, height: '1px', borderTop: "2px dashed var(--border)", margin: '0 12px' }} />
                    )}
                  </div>
                );
              })}
            </div>
            
            <div style={{ width: '160px', border: '1px solid var(--border)', borderRadius: '8px', padding: '16px', background: 'var(--bg)' }}>
              <div style={{ fontSize: '14px', fontWeight: '600', marginBottom: '12px' }}>
                {Math.round((run.checklist.filter(i => i.status === "done").length / run.checklist.length) * 100)}% complete
              </div>
              <div style={{ height: '6px', background: 'var(--bg-2, var(--border))', borderRadius: '3px', overflow: 'hidden' }}>
                <div style={{ width: `${Math.round((run.checklist.filter(i => i.status === "done").length / run.checklist.length) * 100)}%`, height: '100%', background: 'var(--primary)', borderRadius: '3px' }} />
              </div>
            </div>
          </div>

          {run.stage === "ingest" && (
            <div className="delivery-docs">
              <textarea
                value={docs}
                onChange={(e) => setDocs(e.target.value)}
                placeholder="Paste requirements / architecture notes…"
                rows={4}
              />
              <button type="button" className="tiny-btn" disabled={busy} onClick={() => void saveDocs()}>
                Save docs
              </button>
            </div>
          )}
          {run.stage === "architecture" && (
            <div className="delivery-docs" style={{ marginBottom: "16px" }}>
              {architectureStatus === "generating" && <p className="empty-note">Generating architecture from ingested requirements…</p>}
              {architectureProposal?.summary && architectureStatus !== "generating" && (
                <>
                  <p style={{ fontSize: "13px", margin: "0 0 8px" }}><strong>{architectureProposal.tier || ""} {architectureProposal.mode || ""}</strong> {architectureProposal.summary}</p>
                  {architectureProposal.hld ? <pre style={{ whiteSpace: "pre-wrap", fontSize: "12px", maxHeight: "240px", overflow: "auto" }}>{architectureProposal.hld}</pre> : null}
                </>
              )}
            </div>
          )}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingTop: '16px', borderTop: '1px solid var(--border)' }}>
            <div style={{ fontSize: '13px' }}>
              <strong>Review plan</strong> ActionDiff + rollback
            </div>
            {(run.next_actions || []).map((action) => (
              <div key={action} className="empty-note" style={{ display: 'none' }}>
                {action}
              </div>
            ))}
            {run.stage !== "done" && canAdvance && (
              <button
                type="button"
                className="ghost"
                style={{ color: 'var(--primary)', borderColor: 'var(--primary)', padding: '6px 14px', borderRadius: 'var(--radius)', fontSize: '13px', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '4px' }}
                disabled={busy}
                onClick={() => {
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
                }}
              >
                Advance stage
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="9 18 15 12 9 6"></polyline></svg>
              </button>
            )}
            {run.stage !== "done" && !canAdvance && (
              <p style={{ fontSize: '13px', color: 'var(--muted)', margin: 0 }}>
                Needs {currentItem?.min_role || "higher"}+ role.
              </p>
            )}
          </div>
        </>
      )}
      {message && <div className="form-msg">{message}</div>}
    </section>
  );
}
