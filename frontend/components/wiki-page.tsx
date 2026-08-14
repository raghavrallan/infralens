"use client";

/* Static export navigation must be handled by FastAPI's HTML fallback. */
/* eslint-disable @next/next/no-html-link-for-pages */
import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import type { Skill } from "../lib/types";
import { Shell } from "./shell";

type ParamProperty = {
  type?: string;
  description?: string;
  enum?: string[];
};

function prettyName(value: string) {
  return value.split("_").map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(" ");
}

function sortKey(skill: Skill) {
  return prettyName(skill.name);
}

function compareSkills(left: Skill, right: Skill) {
  return sortKey(left).localeCompare(sortKey(right), undefined, { sensitivity: "base" });
}

function markdownToHtml(text: string) {
  const escape = (value: string) => value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
  const inline = (value: string) =>
    escape(value)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em>$1</em>");
  let inCode = false;
  let list: "ul" | "ol" | null = null;
  const output: string[] = [];
  const closeList = () => {
    if (list) {
      output.push(list === "ol" ? "</ol>" : "</ul>");
      list = null;
    }
  };
  for (const line of text.split("\n")) {
    if (line.trim().startsWith("```")) {
      closeList();
      inCode = !inCode;
      output.push(inCode ? "<pre><code>" : "</code></pre>");
      continue;
    }
    if (inCode) {
      output.push(`${escape(line)}\n`);
      continue;
    }
    const escaped = inline(line);
    if (/^##\s+/.test(line)) {
      closeList();
      output.push(`<h2>${escaped.replace(/^##\s+/, "")}</h2>`);
    } else if (/^###\s+/.test(line)) {
      closeList();
      output.push(`<h3>${escaped.replace(/^###\s+/, "")}</h3>`);
    } else if (/^####\s+/.test(line)) {
      closeList();
      output.push(`<h4>${escaped.replace(/^####\s+/, "")}</h4>`);
    } else if (/^---+$/.test(line.trim())) {
      closeList();
      output.push("<hr />");
    } else if (/^\s*-\s+/.test(line)) {
      if (list !== "ul") {
        closeList();
        output.push("<ul>");
        list = "ul";
      }
      output.push(`<li>${escaped.replace(/^\s*-\s+/, "")}</li>`);
    } else if (/^\s*\d+\.\s+/.test(line)) {
      if (list !== "ol") {
        closeList();
        output.push("<ol>");
        list = "ol";
      }
      output.push(`<li>${escaped.replace(/^\s*\d+\.\s+/, "")}</li>`);
    } else if (!line.trim()) {
      closeList();
    } else {
      closeList();
      output.push(`<p>${escaped}</p>`);
    }
  }
  closeList();
  if (inCode) output.push("</code></pre>");
  return output.join("");
}

function parameterRows(skill: Skill) {
  const schema = skill.parameters;
  if (!schema || typeof schema !== "object") return [];
  const properties = (schema.properties || {}) as Record<string, ParamProperty>;
  const required = new Set(Array.isArray(schema.required) ? schema.required.map(String) : []);
  return Object.entries(properties).map(([name, spec]) => ({
    name,
    type: spec.enum?.length ? spec.enum.join(" | ") : spec.type || "string",
    required: required.has(name),
    description: spec.description || "",
  }));
}

type LetterGroup = { letter: string; skills: Skill[] };

function groupByLetter(skills: Skill[]): LetterGroup[] {
  const groups: LetterGroup[] = [];
  for (const skill of skills) {
    const letter = sortKey(skill).charAt(0).toUpperCase() || "#";
    const last = groups[groups.length - 1];
    if (!last || last.letter !== letter) groups.push({ letter, skills: [skill] });
    else last.skills.push(skill);
  }
  return groups;
}

export function WikiPage() {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [selected, setSelected] = useState<Skill | null>(null);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");

  const selectSkill = async (name: string | null, push = true) => {
    if (push && name) window.history.pushState({}, "", `/wiki?skill=${encodeURIComponent(name)}`);
    if (!name) {
      if (push) window.history.pushState({}, "", "/wiki");
      setSelected(null);
      return;
    }
    try {
      setSelected(await api<Skill>(`/api/skills/${encodeURIComponent(name)}`));
      window.scrollTo(0, 0);
    } catch {
      setSelected(null);
    }
  };

  useEffect(() => {
    const onPop = () => void selectSkill(new URLSearchParams(window.location.search).get("skill"), false);
    window.addEventListener("popstate", onPop);
    void api<Skill[]>("/api/skills")
      .then((list) => {
        setSkills([...list].sort(compareSkills));
        const name = new URLSearchParams(window.location.search).get("skill");
        if (name) void selectSkill(name, false);
      })
      .finally(() => setLoading(false));
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const sorted = [...skills].sort(compareSkills);
    if (!needle) return sorted;
    return sorted.filter((skill) => {
      const haystack = [prettyName(skill.name), skill.name, skill.category, skill.description].join(" ").toLowerCase();
      return haystack.includes(needle);
    });
  }, [skills, query]);

  const groups = useMemo(() => groupByLetter(filtered), [filtered]);
  const letters = useMemo(() => groups.map((group) => group.letter), [groups]);
  const params = selected ? parameterRows(selected) : [];

  const scrollToLetter = (letter: string) => {
    document.getElementById(`wiki-letter-${letter}`)?.scrollIntoView({ block: "start" });
  };

  return (
    <Shell>
      <main className="wiki-layout">
        <aside className="wiki-index">
          <h3>Skills A–Z</h3>
          <p className="wiki-index-meta">{filtered.length} of {skills.length}</p>
          <input
            className="wiki-search"
            type="search"
            placeholder="Filter A–Z…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label="Filter skills A to Z"
          />
          {letters.length > 0 && (
            <div className="wiki-az" aria-label="Jump to letter">
              {letters.map((letter) => (
                <button key={letter} type="button" onClick={() => scrollToLetter(letter)}>{letter}</button>
              ))}
            </div>
          )}
          {groups.map((group) => (
            <div key={group.letter} id={`wiki-letter-${group.letter}`}>
              <div className="wiki-letter">{group.letter}</div>
              {group.skills.map((skill) => (
                <button
                  className={`wiki-index-item${selected?.name === skill.name ? " active" : ""}`}
                  key={skill.name}
                  type="button"
                  onClick={() => void selectSkill(skill.name)}
                >
                  <span>{prettyName(skill.name)}</span>
                  <small>{skill.category}</small>
                </button>
              ))}
            </div>
          ))}
          {!loading && filtered.length === 0 && <p className="muted">No skills match that filter.</p>}
        </aside>
        <article className="wiki-article">
          {loading ? (
            <p className="muted">Loading…</p>
          ) : selected ? (
            <>
              <div className="wiki-head">
                <div className="wiki-head-tags">
                  <span className="wiki-cat">{selected.category}</span>
                  {selected.is_agentic && <span className="wiki-badge">Agentic</span>}
                  {selected.auto_routable === false && <span className="wiki-badge wiki-badge-muted">Not auto-routed</span>}
                  <code className="wiki-slug">/{selected.name}</code>
                </div>
                <div className="wiki-head-actions">
                  <button className="wiki-back" type="button" onClick={() => void selectSkill(null)}>All skills</button>
                  <a className="wiki-try" href="/">Try in chat →</a>
                </div>
              </div>
              <div dangerouslySetInnerHTML={{ __html: markdownToHtml(selected.wiki || `## ${prettyName(selected.name)}\n\n${selected.description}`) }} />
              {params.length > 0 && (
                <>
                  <h3>Parameters</h3>
                  <div className="wiki-table-wrap">
                    <table className="wiki-table">
                      <thead>
                        <tr>
                          <th>Name</th>
                          <th>Type</th>
                          <th>Required</th>
                          <th>Description</th>
                        </tr>
                      </thead>
                      <tbody>
                        {params.map((param) => (
                          <tr key={param.name}>
                            <td><code>{param.name}</code></td>
                            <td>{param.type}</td>
                            <td>{param.required ? "Yes" : "No"}</td>
                            <td>{param.description}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
              <h3>Example prompts</h3>
              <ul>
                {(selected.triggers || []).map((trigger) => (
                  <li key={trigger}><code>{trigger}</code></li>
                ))}
              </ul>
            </>
          ) : (
            <>
              <h2>Skill wiki</h2>
              <p className="muted">
                Reference documentation for every agent and skill — sorted A–Z. Open an entry for what it does,
                when to use it, how to run it, inputs, output, and safety limits.
              </p>
              {groups.map((group) => (
                <section key={group.letter} className="wiki-letter-section">
                  <h3 className="wiki-letter-heading">{group.letter}</h3>
                  <div className="wiki-grid">
                    {group.skills.map((skill) => (
                      <button className="wiki-card" key={skill.name} type="button" onClick={() => void selectSkill(skill.name)}>
                        <div className="wiki-card-name">{prettyName(skill.name)}</div>
                        <div className="wiki-card-cat">{skill.category}</div>
                        <div className="wiki-card-desc">{skill.description}</div>
                      </button>
                    ))}
                  </div>
                </section>
              ))}
            </>
          )}
        </article>
      </main>
    </Shell>
  );
}
