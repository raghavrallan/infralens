"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { PageHead, Panel, Pill } from "@/components/ui";
import { fieldClass, SuiteDown, SuiteGate } from "@/components/suite/SuiteScreen";
import { prettyName, suiteJson } from "@/lib/suite";

function WikiList() {
  const [skills, setSkills] = useState([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancel = false;
    suiteJson("/api/skills")
      .then((list) => {
        if (!cancel) setSkills(Array.isArray(list) ? list : []);
      })
      .catch((err) => {
        if (!cancel) setError(err.message);
      })
      .finally(() => {
        if (!cancel) setLoading(false);
      });
    return () => {
      cancel = true;
    };
  }, []);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return [...skills]
      .sort((left, right) => prettyName(left.name).localeCompare(prettyName(right.name)))
      .filter((skill) => {
        if (!needle) return true;
        return [prettyName(skill.name), skill.name, skill.category, skill.description].join(" ").toLowerCase().includes(needle);
      });
  }, [skills, query]);

  if (error?.includes("not running")) return <SuiteDown />;

  return (
    <div className="space-y-4">
      <PageHead eyebrow="Agentic" title="Wiki" description="Skill reference from the catalog. Open an entry for the wiki doc, parameters, and example prompts." />
      <Panel
        title={`${filtered.length} skills`}
        action={<input className={`${fieldClass} mt-0 w-56`} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter skills" aria-label="Filter skills" />}
      >
        {loading && <p className="text-sm text-muted">Loading skills…</p>}
        {error && <p className="text-sm text-danger">{error}</p>}
        {!loading && filtered.length === 0 && <p className="text-sm text-muted">No skills match that filter.</p>}
        <div className="grid gap-3 md:grid-cols-2">
          {filtered.map((skill) => (
            <Link key={skill.name} href={`/wiki/${encodeURIComponent(skill.name)}`} className="rounded-2xl border border-line px-3 py-3 hover:bg-canvas">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold text-ink">{prettyName(skill.name)}</span>
                <Pill tone="muted">{skill.category}</Pill>
                {skill.is_agentic && <Pill tone="brand">Agentic</Pill>}
              </div>
              <p className="mt-2 text-sm text-muted">{skill.description}</p>
            </Link>
          ))}
        </div>
      </Panel>
    </div>
  );
}

export default function WikiPage() {
  return (
    <SuiteGate>
      <WikiList />
    </SuiteGate>
  );
}
