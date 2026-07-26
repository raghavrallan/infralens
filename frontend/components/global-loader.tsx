"use client";

export function GlobalLoader({ active, label = "Loading InfraLens" }: { active: boolean; label?: string }) {
  if (!active) return null;
  return (
    <div className="global-loader" role="status" aria-live="polite" aria-label={label}>
      <div className="global-loader-panel">
        <span className="global-loader-mark" aria-hidden="true">IL</span>
        <span className="global-loader-copy">{label}</span>
        <span className="global-loader-dots" aria-hidden="true"><i /><i /><i /></span>
      </div>
    </div>
  );
}
