"use client";

export type ArchitectureNode = {
  name?: string;
  service?: string;
  purpose?: string;
  provider?: string;
};

const LANE_ORDER = [
  "repository",
  "compute",
  "networking",
  "database",
  "cache",
  "secrets",
  "iam",
  "monitoring",
  "cicd",
];

function lane(name: string): string {
  const lowered = name.toLowerCase();
  if (lowered.includes("repo") || lowered.includes("document")) return "repository";
  if (lowered.includes("compute") || lowered.includes("container") || lowered.includes("frontend")) return "compute";
  if (lowered.includes("network") || lowered.includes("vnet") || lowered.includes("vpc")) return "networking";
  if (lowered.includes("database") || lowered.includes("postgres")) return "database";
  if (lowered.includes("cache") || lowered.includes("redis")) return "cache";
  if (lowered.includes("secret") || lowered.includes("vault")) return "secrets";
  if (lowered.includes("iam") || lowered.includes("identity")) return "iam";
  if (lowered.includes("monitor") || lowered.includes("log")) return "monitoring";
  if (lowered.includes("ci") || lowered.includes("github")) return "cicd";
  return "compute";
}

export function ArchitectureDiagram({
  components,
}: {
  components?: ArchitectureNode[] | null;
}) {
  const items = (components || []).filter((item) => item.name);
  if (!items.length) return null;
  const sorted = [...items].sort(
    (a, b) => LANE_ORDER.indexOf(lane(a.name || "")) - LANE_ORDER.indexOf(lane(b.name || "")),
  );
  return (
    <div className="arch-diagram" role="img" aria-label="Architecture components">
      {sorted.map((item, index) => (
        <div key={item.name} className="arch-diagram-item">
          <article className="arch-node">
            <strong>{item.name}</strong>
            <span>{item.service || item.provider || "component"}</span>
            {item.purpose ? <small>{item.purpose}</small> : null}
          </article>
          {index < sorted.length - 1 ? <span className="arch-arrow" aria-hidden="true">→</span> : null}
        </div>
      ))}
    </div>
  );
}
