"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";

type HealthBar = { label: string; percent: number; done: number; total: number };
type Blocker = { id: string; level: string; title: string; task_id?: string };
type Rec = {
  id: string;
  title: string;
  reason: string;
  impact: string;
  priority: string;
  related_task_id?: string;
  action?: string;
};
type Check = { name: string; ok: boolean; detail?: string };
type TimelineItem = { stage: string; state: string };

type Health = {
  overall: number;
  bars: Record<string, HealthBar>;
  blockers: Blocker[];
  recommendations: Rec[];
  timeline: TimelineItem[];
  readiness: { ready: boolean; status: string; percent: number; checks: Check[] };
  summary: string;
  next_actions: string[];
  task_counts: { total: number; completed: number; blocked: number };
  artifact_count: number;
  memory_count: number;
  pending_adrs: number;
};

const BAR_ORDER = [
  "architecture",
  "infrastructure",
  "security",
  "testing",
  "delivery",
  "documentation",
  "memory",
];

export function EngineeringCommand({ projectId }: { projectId: string }) {
  const [health, setHealth] = useState<Health | null>(null);
  const [busy, setBusy] = useState<string>("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    if (!projectId) return;
    try {
      setHealth(await api<Health>(`/api/engineering/health?project_id=${encodeURIComponent(projectId)}`));
    } catch {
      setHealth(null);
    }
  }, [projectId]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 15000);
    return () => window.clearInterval(timer);
  }, [load]);

  const accept = async (rec: Rec) => {
    setBusy(rec.id);
    setMessage("");
    try {
      const result = await api<{ action?: string; count?: number }>("/api/engineering/recommendations/accept", {
        method: "POST",
        body: JSON.stringify({
          project_id: projectId,
          title: rec.title,
          reason: rec.reason,
          stage: "infrastructure",
          action: rec.action || "",
        }),
      });
      setMessage(
        result.action === "generate_terraform"
          ? `Generated ${result.count ?? 0} missing artifacts.`
          : "Added to the delivery checklist.",
      );
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not add task");
    } finally {
      setBusy("");
    }
  };

  if (!health) {
    return (
      <section className="card eng-command">
        <h3>Project health</h3>
        <p className="muted">Start a delivery run or Solution Architect session to populate live health.</p>
      </section>
    );
  }

  const bars = BAR_ORDER.map((key) => health.bars[key]).filter(Boolean);

  return (
    <section className="eng-command">
      <div className="eng-hero card">
        <div className="eng-hero-top">
          <div>
            <h3>Project health</h3>
            <p className="muted">{health.summary}</p>
          </div>
          <div className={`eng-score${health.readiness.ready ? " ok" : ""}`}>
            <strong>{health.overall}%</strong>
            <span>{health.readiness.status}</span>
          </div>
        </div>
        <div className="eng-bars">
          {bars.map((bar) => (
            <div className="eng-bar" key={bar.label}>
              <div className="eng-bar-meta">
                <span>{bar.label}</span>
                <span>{bar.percent}%</span>
              </div>
              <div className="eng-bar-track">
                <div className="eng-bar-fill" style={{ width: `${bar.percent}%` }} />
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="eng-split">
        <div className="card">
          <h3>Active blockers</h3>
          {!health.blockers.length ? (
            <p className="empty-note">No blockers.</p>
          ) : (
            <ul className="eng-blockers">
              {health.blockers.map((item) => (
                <li key={item.id} className={`eng-blocker ${item.level}`}>
                  <span className="eng-dot" />
                  <a href="#delivery">{item.title}</a>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="card">
          <h3>AI recommendations</h3>
          {!health.recommendations.length ? (
            <p className="empty-note">No recommendations yet.</p>
          ) : (
            <ul className="eng-recs">
              {health.recommendations.map((rec) => (
                <li key={rec.id}>
                  <strong>{rec.title}</strong>
                  <p>Why? {rec.reason}</p>
                  <p className="muted">Impact: {rec.impact}</p>
                  {rec.action === "add_task" || rec.action === "generate_terraform" ? (
                    <button
                      type="button"
                      className="tiny-btn solid"
                      disabled={busy === rec.id}
                      onClick={() => void accept(rec)}
                    >
                      {rec.action === "generate_terraform" ? "Generate artifacts" : "Add to Delivery Checklist"}
                    </button>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="card">
        <h3>Delivery timeline</h3>
        <ol className="eng-timeline">
          {(health.timeline || []).map((item) => (
            <li key={item.stage} className={item.state}>
              <span className="eng-tl-mark">
                {item.state === "done" ? "✓" : item.state === "current" ? "●" : item.state === "blocked" ? "✕" : "○"}
              </span>
              <span className="eng-tl-label">{item.stage}</span>
              <small>{item.state}</small>
            </li>
          ))}
        </ol>
      </div>

      <div className="eng-split">
        <div className="card">
          <h3>Production readiness</h3>
          <p className="muted">{health.readiness.percent}% of mandatory gates</p>
          <ul className="eng-checks">
            {(health.readiness.checks || []).map((check) => (
              <li key={check.name} className={check.ok ? "ok" : "fail"}>
                {check.ok ? "✓" : "○"} {check.name}
                {check.detail ? <small> — {check.detail}</small> : null}
              </li>
            ))}
          </ul>
        </div>
        <div className="card">
          <h3>Next best actions</h3>
          <ol className="eng-next">
            {(health.next_actions || []).map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ol>
          <p className="muted">
            {health.task_counts.completed}/{health.task_counts.total} tasks · {health.artifact_count} artifacts ·{" "}
            {health.memory_count} memories · {health.pending_adrs} ADRs awaiting a gate
          </p>
        </div>
      </div>
      {message ? <div className="form-msg">{message}</div> : null}
    </section>
  );
}
