"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { getStoredUser } from "../lib/auth";

type BgSession = {
  id?: string;
  active?: boolean;
  reason?: string;
  opened_by?: string;
  expires_at?: string | null;
};

type BgStatus = {
  active?: BgSession | null;
  history?: BgSession[];
};

export function BreakGlassPanel({ projectId }: { projectId: string }) {
  const me = getStoredUser();
  const canManage = ["devops_lead", "org_admin", "super_admin"].includes(
    me?.role || "",
  );
  const [status, setStatus] = useState<BgStatus | null>(null);
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!projectId) return;
    try {
      setStatus(
        await api<BgStatus>(
          `/api/break-glass/status?project_id=${encodeURIComponent(projectId)}`,
        ),
      );
    } catch {
      setStatus(null);
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!canManage) return null;

  const active = status?.active && typeof status.active === "object" ? status.active : null;

  const open = async () => {
    setBusy(true);
    setMessage("");
    try {
      await api("/api/break-glass/open", {
        method: "POST",
        body: JSON.stringify({
          project_id: projectId,
          reason: reason || "Emergency gate downgrade",
          ttl_minutes: 60,
        }),
      });
      setReason("");
      setMessage("Break-glass opened (60 minutes).");
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Open failed");
    } finally {
      setBusy(false);
    }
  };

  const expire = async () => {
    setBusy(true);
    try {
      await api(
        `/api/break-glass/expire?project_id=${encodeURIComponent(projectId)}`,
        { method: "POST" },
      );
      setMessage("Break-glass expired.");
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Expire failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card">
      <div className="card-head">
        <h3>Break-glass</h3>
        <span className={`pill ${active ? "warn" : "off"}`}>
          {active ? "active" : "off"}
        </span>
      </div>
      {active ? (
        <>
          <p className="empty-note">
            Opened by {active.opened_by || "—"}. {active.reason || ""}
            {active.expires_at ? ` Expires ${active.expires_at}.` : ""}
          </p>
          <button
            type="button"
            className="tiny-btn danger"
            disabled={busy}
            onClick={() => void expire()}
          >
            Expire now
          </button>
        </>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <label style={{ fontSize: '13px', color: 'var(--muted)' }}>Reason (required for audit)</label>
          <textarea
            placeholder="Enter reason..."
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            style={{ width: '100%', minHeight: '80px', padding: '10px', borderRadius: 'var(--radius)', border: '1px solid var(--border)', background: 'var(--panel)', color: 'var(--text)', fontSize: '14px', fontFamily: 'var(--font-sans)', resize: 'vertical' }}
          />
          <button
            type="button"
            className="modal-btn primary"
            disabled={busy || !reason.trim()}
            onClick={() => void open()}
            style={{ width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', padding: '12px', marginTop: '8px' }}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 10 0v4"></path></svg>
            Open session
          </button>
        </div>
      )}
      {message && <div className="form-msg">{message}</div>}
    </section>
  );
}
