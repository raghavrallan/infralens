"use client";

import { primaryCtaLabel } from "./delivery-stage-rail";

type RepairInfo = {
  status?: string;
  attempt?: number;
  max_attempts?: number;
  progress?: string;
  last_error?: string;
};

export function DeliveryStagePanel({
  stage,
  busy,
  canAdvance,
  onPrimary,
  onUpload,
  onImportRepo,
  onMarkExternal,
  onRetryRepair,
  repair,
  hint,
}: {
  stage: string;
  busy: boolean;
  canAdvance: boolean;
  onPrimary: () => void;
  onUpload?: (file: File) => void;
  onImportRepo?: () => void;
  onMarkExternal?: () => void;
  onRetryRepair?: () => void;
  repair?: RepairInfo;
  hint?: string;
}) {
  const showAlt =
    stage === "ingest" ||
    stage === "architecture" ||
    stage === "terraform" ||
    stage === "plan" ||
    stage === "apply";

  return (
    <div className="delivery-stage-panel" style={{ marginBottom: 16 }}>
      {hint ? <p className="muted" style={{ marginTop: 0 }}>{hint}</p> : null}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <button type="button" className="tiny-btn solid" disabled={busy || !canAdvance} onClick={onPrimary}>
          {primaryCtaLabel(stage)}
        </button>
        {showAlt && onUpload ? (
          <label className="tiny-btn" style={{ cursor: "pointer" }}>
            Upload / import file
            <input
              type="file"
              hidden
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) onUpload(file);
                e.target.value = "";
              }}
            />
          </label>
        ) : null}
        {(stage === "terraform" || stage === "plan") && onImportRepo ? (
          <button type="button" className="tiny-btn" disabled={busy} onClick={onImportRepo}>
            Import from mapped repo
          </button>
        ) : null}
        {(stage === "apply" || stage === "plan") && onMarkExternal ? (
          <button type="button" className="tiny-btn" disabled={busy} onClick={onMarkExternal}>
            Mark applied externally
          </button>
        ) : null}
        {onRetryRepair && repair && (repair.status === "failed" || repair.status === "exhausted") ? (
          <button type="button" className="tiny-btn" disabled={busy} onClick={onRetryRepair}>
            Retry repair
          </button>
        ) : null}
      </div>
      {repair && (repair.status || repair.progress) ? (
        <p className="muted" style={{ marginTop: 10 }}>
          Terraform repair: {repair.status || "idle"}
          {repair.attempt ? ` · attempt ${repair.attempt}/${repair.max_attempts || 4}` : ""}
          {repair.progress ? ` · ${repair.progress}` : ""}
          {repair.last_error ? ` · ${repair.last_error.slice(0, 220)}` : ""}
        </p>
      ) : null}
    </div>
  );
}
