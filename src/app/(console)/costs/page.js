"use client";

import { BillingBoard } from "@/components/BillingBoard";
import { PageHead } from "@/components/ui";
import { useConsole } from "@/context/ConsoleContext";

export default function CostsPage() {
  const { model, projectId, rangeId } = useConsole();
  if (!model || model.status !== "ready") return null;
  if (!model.canSeeCost) {
    return <PageHead title="Costs" description="Your role does not include billing for this project." />;
  }
  return (
    <div className="space-y-4">
      <PageHead
        eyebrow={model.project.name}
        title="Costs"
        description="Filter the chart the way Cost Analysis does, pick the dates yourself, and download the CSV or an older invoice."
      />
      <BillingBoard
        projectId={projectId}
        rangeId={rangeId}
        saved={{
          currency: model.kpis.currency,
          spend: model.kpis.spend,
          points: model.trend.points,
          services: model.services,
          groups: model.groups,
        }}
      />
    </div>
  );
}
