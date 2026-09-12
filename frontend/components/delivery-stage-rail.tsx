"use client";

type ChecklistItem = {
  stage: string;
  label: string;
  status: string;
  min_role?: string;
};

export function DeliveryStageRail({
  items,
  currentStage,
}: {
  items: ChecklistItem[];
  currentStage?: string;
}) {
  return (
    <div className="delivery-stage-rail" style={{ display: "flex", alignItems: "flex-start", marginBottom: "36px" }}>
      {items.map((item, i) => {
        const isDone = item.status === "done";
        const isCurrent = item.status === "current" || item.stage === currentStage;
        const color = isDone || isCurrent ? "var(--primary)" : "var(--muted)";
        return (
          <div
            key={item.stage}
            style={{ display: "flex", alignItems: "center", flex: i === items.length - 1 ? "none" : 1 }}
          >
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", position: "relative" }}>
              <div
                style={{
                  width: 32,
                  height: 32,
                  borderRadius: "50%",
                  border: `2px solid ${isDone || isCurrent ? "var(--primary)" : "var(--border)"}`,
                  background: isDone ? "var(--primary)" : "transparent",
                  color: isDone ? "#fff" : color,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 13,
                }}
              >
                {isDone ? "✓" : i + 1}
              </div>
              <span style={{ position: "absolute", top: 40, fontSize: 12, color, whiteSpace: "nowrap" }}>
                {item.label}
              </span>
            </div>
            {i < items.length - 1 && (
              <div style={{ flex: 1, borderTop: "2px dashed var(--border)", margin: "0 10px" }} />
            )}
          </div>
        );
      })}
    </div>
  );
}

export function primaryCtaLabel(stage: string): string {
  switch (stage) {
    case "ingest":
      return "Save docs & continue";
    case "architecture":
      return "Accept architecture";
    case "terraform":
      return "Generate modules & init";
    case "plan":
      return "Run terraform plan";
    case "apply":
      return "Apply (Lead+)";
    case "code":
      return "Scaffold app code";
    default:
      return "Continue";
  }
}
