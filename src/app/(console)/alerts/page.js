"use client";

import { useState } from "react";
import { AlertDrawer } from "@/components/AlertDetail";
import { DataTable, PageHead, Panel, Pill } from "@/components/ui";
import { useConsole } from "@/context/ConsoleContext";
import { severityLabel } from "@/lib/alerts";

function severityTone(severity) {
  const value = Number(severity);
  if (value <= 1) return "danger";
  if (value === 2) return "warn";
  return "muted";
}

export default function AlertsPage() {
  const { model } = useConsole();
  const [selected, setSelected] = useState(null);
  if (!model || model.status !== "ready") return null;
  return (
    <div className="space-y-4">
      <PageHead eyebrow={model.project.name} title="Alerts" description="Metric alert rules from Azure Monitor. Select a rule to see its condition, scope, and who gets notified." />
      <Panel>
        <DataTable
          rows={model.alerts}
          searchKeys={["name", "state", "group", "signal", "description"]}
          onRow={setSelected}
          columns={[
            { key: "name", label: "Rule" },
            { key: "signal", label: "Condition", render: (row) => <span className="block max-w-xs truncate">{row.signal || "—"}</span> },
            { key: "severity", label: "Severity", render: (row) => <Pill tone={severityTone(row.severity)}>{severityLabel(row.severity)}</Pill> },
            { key: "group", label: "Resource group" },
            { key: "state", label: "State", render: (row) => <Pill tone={row.state === "Enabled" ? "ok" : "muted"}>{row.state}</Pill> },
          ]}
        />
      </Panel>
      <AlertDrawer alert={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
