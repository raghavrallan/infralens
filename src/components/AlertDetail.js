"use client";

import { Drawer, Pill } from "@/components/ui";
import { conditionText, severityLabel } from "@/lib/alerts";

function toneFor(severity) {
  const value = Number(severity);
  if (value <= 1) return "danger";
  if (value === 2) return "warn";
  return "muted";
}

function Fact({ label, value }) {
  if (!value) return null;
  return (
    <div>
      <dt className="text-[11px] font-semibold uppercase tracking-wide text-muted">{label}</dt>
      <dd className="mt-0.5 break-words text-ink">{value}</dd>
    </div>
  );
}

export function AlertDrawer({ alert, onClose }) {
  const conditions = alert?.conditions || [];
  const scopes = alert?.scopes || [];
  const actions = alert?.actionGroups || [];
  return (
    <Drawer
      open={Boolean(alert)}
      title={alert?.name || ""}
      subtitle={alert ? [alert.group, alert.location].filter(Boolean).join(" · ") : ""}
      onClose={onClose}
    >
      {alert && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <Pill tone={toneFor(alert.severity)}>{severityLabel(alert.severity)}</Pill>
            <Pill tone={alert.state === "Enabled" ? "ok" : "muted"}>{alert.state}</Pill>
            {alert.autoMitigate === "Yes" && <Pill tone="ok">Resolves automatically</Pill>}
            {alert.autoMitigate === "No" && <Pill tone="warn">Stays open</Pill>}
          </div>
          {alert.description && <p className="text-sm leading-6 text-ink">{alert.description}</p>}
          <section>
            <h4 className="text-sm font-semibold">Condition</h4>
            {conditions.length === 0 ? <p className="mt-1 text-sm text-muted">No metric condition is saved on this rule.</p> : (
              <ul className="mt-2 space-y-2">
                {conditions.map((item, index) => (
                  <li key={`${item.metric}-${index}`} className="rounded-xl bg-canvas px-3 py-2 text-sm">
                    <p className="font-medium">{conditionText(item)}</p>
                    {item.namespace && <p className="mt-0.5 text-xs text-muted">{item.namespace}</p>}
                  </li>
                ))}
              </ul>
            )}
          </section>
          <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
            <Fact label="Checked every" value={alert.frequency} />
            <Fact label="Window" value={alert.window} />
            <Fact label="Target type" value={alert.targetType} />
            <Fact label="Target region" value={alert.targetRegion} />
          </dl>
          <section>
            <h4 className="text-sm font-semibold">Scope</h4>
            {scopes.length === 0 ? <p className="mt-1 text-sm text-muted">This rule does not name a resource.</p> : (
              <ul className="mt-2 space-y-2">
                {scopes.slice(0, 8).map((item) => (
                  <li key={`${item.type}-${item.name}`} className="text-sm">
                    <span className="font-medium">{item.name}</span>
                    {item.type && <span className="mt-0.5 block text-xs text-muted">{item.type}</span>}
                  </li>
                ))}
              </ul>
            )}
            {scopes.length > 8 && <p className="mt-2 text-xs text-muted">and {scopes.length - 8} more</p>}
          </section>
          <section>
            <h4 className="text-sm font-semibold">Notify</h4>
            {actions.length === 0 ? <p className="mt-1 text-sm text-muted">No action group is attached.</p> : (
              <ul className="mt-2 space-y-1">
                {actions.map((name) => <li key={name} className="text-sm font-medium">{name}</li>)}
              </ul>
            )}
          </section>
          {alert.id && (
            <a href={`https://portal.azure.com/#resource${alert.id}`} target="_blank" rel="noreferrer" className="inline-block text-sm font-semibold text-brand">
              Open in Azure
            </a>
          )}
        </div>
      )}
    </Drawer>
  );
}
