"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { DataTable, PageHead, Panel, Pill } from "@/components/ui";
import { SuiteDown, SuiteGate } from "@/components/suite/SuiteScreen";
import { WikiDoc } from "@/components/suite/WikiDoc";
import { prettyName, suiteJson } from "@/lib/suite";

function parameterRows(skill) {
  const schema = skill?.parameters;
  if (!schema || typeof schema !== "object") return [];
  const properties = schema.properties || {};
  const required = new Set(Array.isArray(schema.required) ? schema.required.map(String) : []);
  return Object.entries(properties).map(([name, spec]) => ({
    name,
    type: spec?.enum?.length ? spec.enum.join(" | ") : spec?.type || "string",
    required: required.has(name),
    description: spec?.description || "",
  }));
}

function WikiSkill() {
  const params = useParams();
  const slug = decodeURIComponent(String(params.slug || ""));
  const [skill, setSkill] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!slug) return undefined;
    let cancel = false;
    suiteJson(`/api/skills/${encodeURIComponent(slug)}`)
      .then((body) => {
        if (!cancel) setSkill(body);
      })
      .catch((err) => {
        if (!cancel) setError(err.message);
      });
    return () => {
      cancel = true;
    };
  }, [slug]);

  if (error?.includes("not running")) return <SuiteDown />;

  return (
    <div className="space-y-4">
      <PageHead
        eyebrow="Agentic"
        title={skill ? prettyName(skill.name) : prettyName(slug)}
        description={skill?.description || "Skill wiki"}
        action={
          <Link href="/wiki" className="text-sm font-semibold text-brand">
            All skills
          </Link>
        }
      />
      {error && <p className="text-sm text-danger">{error}</p>}
      {!skill && !error && <p className="text-sm text-muted">Loading skill…</p>}
      {skill && (
        <Panel>
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <Pill tone="muted">{skill.category}</Pill>
            {skill.is_agentic && <Pill tone="brand">Agentic</Pill>}
            {skill.auto_routable === false && <Pill tone="warn">Not auto-routed</Pill>}
            <code className="text-xs text-muted">/{skill.name}</code>
            <Link href="/chat" className="text-sm font-semibold text-brand" onClick={() => window.localStorage.setItem("suiteSkill", skill.name)}>
              Try in chat
            </Link>
          </div>
          <WikiDoc text={skill.wiki || `## ${prettyName(skill.name)}\n\n${skill.description || ""}`} />
          {parameterRows(skill).length > 0 && (
            <div className="mt-4">
              <h2 className="mb-2 text-sm font-semibold">Parameters</h2>
              <DataTable
                rows={parameterRows(skill).map((row) => ({ ...row, id: row.name, requiredLabel: row.required ? "Yes" : "No" }))}
                searchKeys={["name", "type", "description"]}
                columns={[
                  { key: "name", label: "Name" },
                  { key: "type", label: "Type" },
                  { key: "requiredLabel", label: "Required" },
                  { key: "description", label: "Description" },
                ]}
              />
            </div>
          )}
          {(skill.triggers || []).length > 0 && (
            <div className="mt-4">
              <h2 className="mb-2 text-sm font-semibold">Example prompts</h2>
              <ul className="space-y-1 text-sm">
                {skill.triggers.map((trigger) => (
                  <li key={trigger}>
                    <code>{trigger}</code>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Panel>
      )}
    </div>
  );
}

export default function WikiSkillPage() {
  return (
    <SuiteGate>
      <WikiSkill />
    </SuiteGate>
  );
}
