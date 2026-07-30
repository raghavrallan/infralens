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
        <div className="users-create">
          <input
            placeholder="Reason (required for audit)"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <button
            type="button"
            className="tiny-btn solid"
            disabled={busy || !reason.trim()}
            onClick={() => void open()}
          >
            Open session
          </button>
        </div>
      )}
      {message && <div className="form-msg">{message}</div>}
    </section>
  );
}
