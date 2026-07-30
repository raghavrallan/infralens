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

  const canAdvance = hasMinRole(me?.role, currentItem?.min_role);

  return (
    <section className="card delivery-checklist">
      <div className="card-head">
        <h3>Delivery checklist</h3>
        {!run ? (
          <button type="button" className="tiny-btn solid" disabled={busy} onClick={() => void start()}>
            Start delivery
          </button>
        ) : (
          <span className="pill ok">{run.stage}</span>
        )}
      </div>
      {!run ? (
        <p className="empty-note">Docs → architecture → Terraform PR → gated apply → code PR.</p>
      ) : (
        <>
          <ol className="delivery-steps">
            {run.checklist.map((item) => (
              <li key={item.stage} className={`delivery-step ${item.status}`}>
                <strong>{item.label}</strong>
                <span>
                  {item.status}
                  {item.min_role ? ` · ${item.min_role}+` : ""}
                </span>
              </li>
            ))}
          </ol>
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
          <div className="delivery-next">
            {(run.next_actions || []).map((action) => (
              <div key={action} className="empty-note">
                {action}
              </div>
            ))}
            {run.stage !== "done" && canAdvance && (
              <button
                type="button"
                className="modal-btn primary"
                disabled={busy}
                onClick={() => {
                  const next = nextStage();
                  if (!next) return;
                  if (run.stage === "architecture") {
                    void (async () => {
                      const accepted = await advance(
                        "architecture",
                        "architecture_accepted",
                        true,
                      );
                      if (accepted) await advance(next);
                    })();
                    return;
                  }
                  void advance(next);
                }}
              >
                Advance stage
              </button>
            )}
            {run.stage !== "done" && !canAdvance && (
              <p className="empty-note">
                Needs {currentItem?.min_role || "higher"} role or above to advance.
              </p>
            )}
          </div>
        </>
      )}
      {message && <div className="form-msg">{message}</div>}
    </section>
  );
}
