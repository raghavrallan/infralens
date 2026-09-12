"use client";

import { useEffect } from "react";
import { DashboardShell, useDashboardContext } from "./dashboard-shell";
import { EngineeringCommand } from "./engineering-command";

function EngineeringBody() {
  const { projectId, setLoading, setUpdated } = useDashboardContext();

  useEffect(() => {
    setLoading(false);
    if (projectId) setUpdated(new Date());
  }, [projectId, setLoading, setUpdated]);

  if (!projectId) {
    return (
      <div className="empty-note">Select a project to open Engineering Command.</div>
    );
  }

  return (
    <section className="dash-col">
      <EngineeringCommand projectId={projectId} />
    </section>
  );
}

export function DashboardEngineeringPage() {
  return (
    <DashboardShell title="Engineering">
      <EngineeringBody />
    </DashboardShell>
  );
}
