"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Kpi, PageHead, Panel, Pill } from "@/components/ui";
import { ghostBtn, primaryBtn, SuiteDown, SuiteGate, SuiteProjectBar, useSuiteProject } from "@/components/suite/SuiteScreen";
import { prettyName, suiteJson } from "@/lib/suite";

function sevTone(severity) {
  const value = String(severity || "").toLowerCase();
  if (value === "critical" || value === "high") return "danger";
  if (value === "medium") return "warn";
  if (value === "low") return "info";
  return "muted";
}

function FindingsBody() {
  const project = useSuiteProject();
  const [findings, setFindings] = useState([]);
  const [modules, setModules] = useState([]);
  const [severity, setSeverity] = useState("");
  const [status, setStatus] = useState("open");
  const [module, setModule] = useState("");
  const [expanded, setExpanded] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    suiteJson("/api/intelligence/catalog")
      .then((catalog) => setModules(catalog?.modules || []))
      .catch(() => setModules([]));
  }, []);

  useEffect(() => {
    if (!project.projectId) return undefined;
    let cancel = false;
    const timer = window.setTimeout(() => setLoading(true), 0);
    const query = new URLSearchParams({ project_id: project.projectId, time_range: "all" });
    if (severity) query.set("severity", severity);
    if (status) query.set("status", status);
    if (module) query.set("module", module);
    suiteJson(`/api/findings?${query}`)
      .then((list) => {
        if (!cancel) setFindings(Array.isArray(list) ? list : []);
      })
      .catch((err) => {
        if (!cancel) setError(err.message);
      })
      .finally(() => {
        if (!cancel) setLoading(false);
      });
    return () => {
      cancel = true;
      window.clearTimeout(timer);
    };
  }, [project.projectId, severity, status, module]);

  async function updateFinding(id, nextStatus) {
    setError("");
    try {
      await suiteJson(`/api/findings/${id}`, { method: "PATCH", body: { status: nextStatus } });
      setFindings((current) => current.map((item) => (item.id === id ? { ...item, status: nextStatus } : item)));
    } catch (err) {
      setError(err.message);
    }
  }

  if (project.down) return <SuiteDown />;

  const critical = findings.filter((item) => item.severity === "critical" || item.severity === "high").length;

  return (
    <div className="space-y-4">
      <PageHead
        eyebrow="Agentic"
        title="Findings"
        description="Open findings from workflow runs, with the gate and the recommended action."
        action={
          <SuiteProjectBar loading={project.loading} loadError={project.error}
            projects={project.projects}
            projectId={project.projectId}
            onChange={project.selectProject}
            onCreated={(created) => {
              project.setProjects((current) => [...current, created]);
              project.selectProject(created.id);
            }}
          />
        }
      />
      <div className="grid gap-3 sm:grid-cols-3">
        <Kpi label="In this filter" value={findings.length} tone="brand" />
        <Kpi label="High or critical" value={critical} tone={critical ? "danger" : "ok"} />
        <Kpi label="Status" value={status || "all"} tone="info" />
      </div>
      <Panel>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          {["", "critical", "high", "medium", "low"].map((value) => (
            <button key={value || "all"} type="button" onClick={() => setSeverity(value)} className={`rounded-full px-3 py-1 text-xs font-semibold ${severity === value ? "bg-ink text-white" : "bg-canvas text-muted"}`}>
              {value ? prettyName(value) : "All"}
            </button>
          ))}
          <select className="h-10 rounded-2xl border border-line bg-white px-3 text-sm" value={status} onChange={(event) => setStatus(event.target.value)} aria-label="Status">
            <option value="open">Open</option>
            <option value="acknowledged">Acknowledged</option>
            <option value="resolved">Resolved</option>
            <option value="">All statuses</option>
          </select>
          <select className="h-10 rounded-2xl border border-line bg-white px-3 text-sm" value={module} onChange={(event) => setModule(event.target.value)} aria-label="Module">
            <option value="">All modules</option>
            {modules.map((item) => (
              <option key={item.key} value={item.key}>
                {item.label}
              </option>
            ))}
          </select>
        </div>
        {error && <p className="mb-3 text-sm text-danger">{error}</p>}
        {loading && <p className="text-sm text-muted">Loading findings…</p>}
        {!loading && findings.length === 0 && <p className="text-sm text-muted">No findings match this filter.</p>}
        <div className="space-y-3">
          {findings.map((finding) => (
            <article key={finding.id} className="rounded-2xl border border-line px-3 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <Pill tone={sevTone(finding.severity)}>{finding.severity}</Pill>
                {finding.gate_label && <Pill tone={finding.gate_decision === "block" ? "danger" : "warn"}>{finding.gate_label}</Pill>}
                {finding.module_label && <Pill tone="muted">{finding.module_label}</Pill>}
                {finding.status !== "open" && <Pill tone="info">{finding.status}</Pill>}
              </div>
              <h3 className="mt-2 text-sm font-semibold">{finding.title}</h3>
              <p className="mt-1 text-xs text-muted">
                {prettyName(finding.skill)}
                {finding.resource ? ` · ${finding.resource}` : ""}
                {finding.blast_radius ? ` · blast ${finding.blast_radius}` : ""}
              </p>
              {expanded === finding.id && (
                <div className="mt-3 space-y-2 text-sm">
                  {finding.evidence && (
                    <p>
                      <span className="font-semibold">Evidence. </span>
                      {finding.evidence}
                    </p>
                  )}
                  {finding.recommended_action && (
                    <p>
                      <span className="font-semibold">Recommended action. </span>
                      {finding.recommended_action}
                    </p>
                  )}
                </div>
              )}
              <div className="mt-3 flex flex-wrap gap-2">
                <button type="button" className={ghostBtn} onClick={() => setExpanded((current) => (current === finding.id ? "" : finding.id))}>
                  {expanded === finding.id ? "Hide" : "Gate and action"}
                </button>
                <Link
                  href="/chat"
                  className={ghostBtn}
                  onClick={() => {
                    window.localStorage.setItem("projectId", project.projectId);
                    window.localStorage.setItem(
                      "suitePrompt",
                      `Explain this finding and how to fix it safely.\n\nSkill: ${prettyName(finding.skill)}\nSeverity: ${finding.severity}\nTitle: ${finding.title}\n${finding.evidence ? `Evidence: ${finding.evidence}` : ""}`,
                    );
                  }}
                >
                  Chat to resolve
                </Link>
                {finding.status === "open" && (
                  <button type="button" className={ghostBtn} onClick={() => void updateFinding(finding.id, "acknowledged")}>
                    Acknowledge
                  </button>
                )}
                {finding.status !== "resolved" ? (
                  <button type="button" className={primaryBtn} onClick={() => void updateFinding(finding.id, "resolved")}>
                    Resolve
                  </button>
                ) : (
                  <button type="button" className={ghostBtn} onClick={() => void updateFinding(finding.id, "open")}>
                    Reopen
                  </button>
                )}
              </div>
            </article>
          ))}
        </div>
      </Panel>
    </div>
  );
}

export default function FindingsPage() {
  return (
    <SuiteGate>
      <FindingsBody />
    </SuiteGate>
  );
}
