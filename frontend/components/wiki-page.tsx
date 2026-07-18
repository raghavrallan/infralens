"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { Skill } from "../lib/types";
import { Shell } from "./shell";

function prettyName(value: string) { return value.split("_").map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(" "); }
function markdownToHtml(text: string) {
  const escape = (value: string) => value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
  let inCode = false;
  let list = false;
  const output: string[] = [];
  for (const line of text.split("\n")) {
    if (line.trim().startsWith("```")) { if (list) { output.push("</ul>"); list = false; } inCode = !inCode; output.push(inCode ? "<pre><code>" : "</code></pre>"); continue; }
    if (inCode) { output.push(`${escape(line)}\n`); continue; }
    const escaped = escape(line).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>").replace(/\*([^*]+)\*/g, "<em>$1</em>");
    if (/^##\s+/.test(line)) { if (list) { output.push("</ul>"); list = false; } output.push(`<h2>${escaped.replace(/^##\s+/, "")}</h2>`); }
    else if (/^###\s+/.test(line)) { if (list) { output.push("</ul>"); list = false; } output.push(`<h3>${escaped.replace(/^###\s+/, "")}</h3>`); }
    else if (/^\s*-\s+/.test(line)) { if (!list) { output.push("<ul>"); list = true; } output.push(`<li>${escaped.replace(/^\s*-\s+/, "")}</li>`); }
    else if (!line.trim()) { if (list) { output.push("</ul>"); list = false; } }
    else { if (list) { output.push("</ul>"); list = false; } output.push(`<p>${escaped}</p>`); }
  }
  if (list) output.push("</ul>");
  if (inCode) output.push("</code></pre>");
  return output.join("");
}

export function WikiPage() {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [selected, setSelected] = useState<Skill | null>(null);
  const [loading, setLoading] = useState(true);
  const selectSkill = async (name: string | null, push = true) => {
    if (push && name) window.history.pushState({}, "", `/wiki?skill=${encodeURIComponent(name)}`);
    if (!name) { window.history.pushState({}, "", "/wiki"); setSelected(null); return; }
    try { setSelected(await api<Skill>(`/api/skills/${encodeURIComponent(name)}`)); window.scrollTo(0, 0); } catch { setSelected(null); }
  };
  useEffect(() => {
    const onPop = () => void selectSkill(new URLSearchParams(window.location.search).get("skill"), false);
    window.addEventListener("popstate", onPop);
    void api<Skill[]>("/api/skills").then((list) => { setSkills(list); const name = new URLSearchParams(window.location.search).get("skill"); if (name) void selectSkill(name, false); }).finally(() => setLoading(false));
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  return <Shell scroll><main className="wiki-layout"><aside className="wiki-index"><h3>Skills</h3>{skills.map((skill) => <button className={`wiki-index-item${selected?.name === skill.name ? " active" : ""}`} key={skill.name} onClick={() => void selectSkill(skill.name)}><span>{prettyName(skill.name)}</span><small>{skill.category}</small></button>)}</aside><article className="wiki-article">{loading ? <p className="muted">Loading…</p> : selected ? <><div className="wiki-head"><span className="wiki-cat">{selected.category}</span><Link className="wiki-try" href={`/?skill=${encodeURIComponent(selected.name)}`}>Try in chat →</Link></div><div dangerouslySetInnerHTML={{ __html: markdownToHtml(selected.wiki || `## ${prettyName(selected.name)}\n\n${selected.description}`) }} /><h3>Example prompts</h3><ul>{(selected.triggers || []).map((trigger) => <li key={trigger}><code>{trigger}</code></li>)}</ul></> : <><h2>Skill wiki</h2><p className="muted">Reference documentation for every skill in the suite — what each one does, when to use it, what to feed it and what you get back.</p><div className="wiki-grid">{skills.map((skill) => <button className="wiki-card" key={skill.name} onClick={() => void selectSkill(skill.name)}><div className="wiki-card-name">{prettyName(skill.name)}</div><div className="wiki-card-cat">{skill.category}</div><div className="wiki-card-desc">{skill.description}</div></button>)}</div></>}</article></main></Shell>;
}
