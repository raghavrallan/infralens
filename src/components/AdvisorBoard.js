"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Kpi, PageHead, Panel, Pill } from "@/components/ui";
import { advisorPrompt, guideFor } from "@/lib/advisor-guides";
import { num } from "@/lib/format";
import { suiteJson } from "@/lib/suite";

const LABELS = {
  Cost: "Cost",
  Security: "Security",
  HighAvailability: "High availability",
  Performance: "Performance",
  OperationalExcellence: "Operational excellence",
};

function impactTone(impact) {
  if (impact === "High") return "danger";
  if (impact === "Medium") return "warn";
  return "info";
}

function categoryLabel(category) {
  return LABELS[category] || category || "Advisor";
}

export default function AdvisorBoard({ projectName, rows }) {
  const items = Array.isArray(rows) ? rows : [];
  const categories = [...new Set(items.map((row) => row.category || "Advisor"))];
  const [filter, setFilter] = useState("all");
  const [openId, setOpenId] = useState("");
  const [modelReady, setModelReady] = useState(false);
  const [loadingId, setLoadingId] = useState("");
  const [guides, setGuides] = useState({});
  const asked = useRef(new Set());
  const shown = items.filter((row) => filter === "all" || (row.category || "Advisor") === filter);
  const counts = {
    high: items.filter((row) => row.impact === "High").length,
    medium: items.filter((row) => row.impact === "Medium").length,
    low: items.filter((row) => row.impact && row.impact !== "High" && row.impact !== "Medium").length,
  };

  useEffect(() => {
    let cancel = false;
    suiteJson("/api/health")
      .then((body) => {
        if (!cancel) setModelReady(Boolean(body?.azure_configured));
      })
      .catch(() => {
        if (!cancel) setModelReady(false);
      });
    return () => {
      cancel = true;
    };
  }, []);

  useEffect(() => {
    if (!openId || !modelReady || asked.current.has(openId)) return undefined;
    const row = items.find((item) => item.id === openId);
    if (!row) return undefined;
    let cancel = false;
    setLoadingId(openId);
    suiteJson("/api/advisor/guide", {
      method: "POST",
      body: {
        items: [{
          id: row.id,
          category: row.category,
          impact: row.impact,
          problem: row.problem,
          solution: row.solution,
        }],
      },
    })
      .then((body) => {
        if (cancel) return;
        const next = Array.isArray(body?.guides) ? body.guides[0] : null;
        asked.current.add(openId);
        setGuides((current) => ({
          ...current,
          [row.id]: next?.steps?.length ? { ...guideFor(row), ...next, source: "model" } : guideFor(row),
        }));
      })
      .catch(() => {
        if (cancel) return;
        asked.current.add(openId);
        setGuides((current) => ({ ...current, [row.id]: guideFor(row) }));
      })
      .finally(() => {
        if (!cancel) setLoadingId("");
      });
    return () => {
      cancel = true;
    };
  }, [openId, modelReady, items]);

  function remember(row, guide) {
    window.localStorage.setItem("suitePrompt", advisorPrompt(row, guide, projectName));
  }

  return (
    <div className="space-y-4">
      <PageHead
        eyebrow={projectName}
        title="Advisor"
        description={modelReady
          ? "Azure Advisor recommendations. Open one to ask the configured model for fix steps. Know more continues in chat, and a change waits for your approval."
          : "Azure Advisor recommendations. Fix steps come from the local playbook until an AI model is configured. Know more continues in chat."}
      />
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi label="Recommendations" value={num(items.length)} hint="Saved from the last sync" />
        <Kpi label="High" value={num(counts.high)} hint="Fix these first" tone="danger" />
        <Kpi label="Medium" value={num(counts.medium)} hint="Plan a change window" tone="warn" />
        <Kpi label="Other" value={num(counts.low)} hint="Low impact and unset" tone="info" />
      </div>
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => setFilter("all")} className={`rounded-full px-3 py-1.5 text-xs font-semibold ${filter === "all" ? "bg-ink text-white" : "bg-white text-muted"}`}>
          All
        </button>
        {categories.map((category) => (
          <button key={category} type="button" onClick={() => setFilter(category)} className={`rounded-full px-3 py-1.5 text-xs font-semibold ${filter === category ? "bg-ink text-white" : "bg-white text-muted"}`}>
            {categoryLabel(category)}
          </button>
        ))}
      </div>
      {shown.length === 0 ? (
        <Panel>
          <p className="py-8 text-center text-sm text-muted">No Advisor recommendations are saved for this filter.</p>
        </Panel>
      ) : (
        <div className="space-y-3">
          {shown.map((row) => {
            const open = openId === row.id;
            const guide = guides[row.id]?.source === "pending" ? guideFor(row) : (guides[row.id] || guideFor(row));
            const source = guides[row.id]?.source === "model" ? "Model" : "Playbook";
            return (
              <Panel key={row.id || row.problem}>
                <button type="button" onClick={() => setOpenId(open ? "" : row.id)} className="flex w-full items-start justify-between gap-3 text-left">
                  <span>
                    <span className="block text-sm font-semibold text-ink">{row.problem}</span>
                    <span className="mt-1 block text-xs text-muted">{row.solution || "Azure did not include a longer solution."}</span>
                  </span>
                  <span className="flex shrink-0 items-center gap-2">
                    <Pill tone="muted">{categoryLabel(row.category)}</Pill>
                    <Pill tone={impactTone(row.impact)}>{row.impact || "Unset"}</Pill>
                  </span>
                </button>
                {open && (
                  <div className="mt-4 border-t border-line pt-4">
                    <div className="mb-2 flex items-center gap-2">
                      <span className="text-[11px] font-semibold uppercase tracking-wide text-muted">How to fix</span>
                      <Pill tone={source === "Model" ? "brand" : "muted"}>{loadingId === row.id ? "Asking the model" : source}</Pill>
                    </div>
                    <ol className="list-decimal space-y-1 pl-5 text-sm text-ink">
                      {guide.steps.map((step) => <li key={step}>{step}</li>)}
                    </ol>
                    {!!guide.commands?.length && (
                      <pre className="mt-3 overflow-x-auto rounded-xl bg-canvas p-3 text-xs text-ink">{guide.commands.join("\n")}</pre>
                    )}
                    <p className="mt-2 text-xs text-muted">{guide.caution}</p>
                    <Link href="/chat" onClick={() => remember(row, guide)} className="mt-3 inline-flex rounded-xl bg-brand px-3 py-2 text-sm font-semibold text-white">
                      Know more in chat
                    </Link>
                  </div>
                )}
              </Panel>
            );
          })}
        </div>
      )}
    </div>
  );
}
