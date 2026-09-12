import type { Catalog, Project } from "./types";

export const TIME_RANGES = [
  { value: "all", label: "All time" },
  { value: "24h", label: "Last 24 hours" },
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
  { value: "90d", label: "Last 90 days" },
];

export type DashboardSummary = Record<string, unknown>;

export type ArchitectRun = {
  id: string;
  objective?: string;
  tier?: string;
  mode?: string;
  status?: string;
  source?: string;
  updated_at?: string;
  mermaid?: string;
  architecture?: {
    cloud?: string;
    stack?: { frameworks?: string[]; languages?: string[] };
    components?: Array<{ name?: string; service?: string; purpose?: string }>;
    iac_strategy?: string;
    analysis?: { brownfield?: string; security?: string[]; cost?: string[] };
  } | null;
  decisions?: Array<{ id: string; title?: string; gate_decision?: string }>;
};

export type WorkflowDraft = {
  name: string;
  objective: string;
  module: string;
  environment: "dev" | "staging" | "prod";
  schedule_cron: string;
  skills: string[];
};

export function numberValue(value: unknown) {
  return typeof value === "number" ? value : Number(value || 0);
}

export function prettyName(value = "") {
  return value
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export function timeAgo(iso?: string) {
  if (!iso) return "—";
  const seconds = Math.max(
    1,
    Math.round((Date.now() - new Date(iso).getTime()) / 1000),
  );
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export function timeUntil(seconds?: number) {
  if (seconds == null) return "";
  if (seconds <= 0) return "expired";
  const hours = Math.round(seconds / 3600);
  return hours < 1
    ? `${Math.max(1, Math.round(seconds / 60))}m left`
    : `${hours}h left`;
}

export function pickDefaultProjectId(list: Project[], saved: string | null) {
  if (saved && list.some((project) => project.id === saved)) return saved;
  return list.find((project) => project.is_default)?.id || list[0]?.id || null;
}

export function emptyCatalog(): Catalog {
  return { skills: [], modules: [] };
}
