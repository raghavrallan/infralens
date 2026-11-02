"use client";

import AdvisorBoard from "@/components/AdvisorBoard";
import { useConsole } from "@/context/ConsoleContext";

export default function InsightsPage() {
  const { model } = useConsole();
  if (!model || model.status !== "ready") return null;
  return <AdvisorBoard projectName={model.project?.name} rows={model.advisor} />;
}
