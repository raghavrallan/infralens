"use client";

import { useEffect, useRef, useState } from "react";
import { DataTable, Panel, Pill } from "@/components/ui";
import { useConsole } from "@/context/ConsoleContext";

async function inspect(body) {
  const response = await fetch("/api/compute/inspect", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.message || "Azure did not return that network.");
  return payload;
}

function forResource(payload, name, group) {
  const subject = payload?.subject;
  if (!subject) return true;
  return String(subject.name || "").toLowerCase() === String(name || "").toLowerCase() && String(subject.group || "") === String(group || "");
}

function noteFor(start, end) {
  if (start === "0.0.0.0" && end === "0.0.0.0") return "Azure services";
  if (start && start === end) return "Single address";
  return "Range";
}

export function NetworkBoard({ serviceId, rows }) {
  const { projectId, rangeId } = useConsole();
  const live = serviceId === "sql" || serviceId === "mysql" || serviceId === "postgresql";
  const choices = rows.filter((row) => (serviceId === "sql" ? row.role === "Server" : true));
  const [selectedId, setSelectedId] = useState(choices[0]?.id || "");
  const [rules, setRules] = useState([]);
  const [subnets, setSubnets] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [savedAt, setSavedAt] = useState(null);
  const ticket = useRef(0);
  const current = choices.find((row) => row.id === selectedId) || choices[0] || null;

  async function load(fresh = false) {
    if (!current) return;
    const mine = ++ticket.current;
    const name = current.name;
    const group = current.group;
    setBusy(true);
    setError("");
    try {
      const payload = await inspect({
        action: "network",
        projectId,
        rangeId,
        serviceId,
        name,
        group,
        fresh,
      });
      if (ticket.current !== mine || !forResource(payload, name, group)) return;
      setRules(payload.rules || []);
      setSubnets(payload.subnets || []);
      setSavedAt(payload.cachedAt || null);
    } catch (err) {
      if (ticket.current === mine) setError(err.message);
    } finally {
      if (ticket.current === mine) setBusy(false);
    }
  }

  useEffect(() => {
    if (!live || !current) return undefined;
    let cancelled = false;
    async function warm() {
      try {
        const payload = await inspect({
          action: "network",
          cacheOnly: true,
          projectId,
          rangeId,
          serviceId,
          name: current.name,
          group: current.group,
        });
        if (cancelled || payload.cacheMiss || !forResource(payload, current.name, current.group)) return;
        setRules(payload.rules || []);
        setSubnets(payload.subnets || []);
        setSavedAt(payload.cachedAt || null);
      } catch {
        // The allow list stays empty until the user asks.
      }
    }
    warm();
    return () => {
      cancelled = true;
    };
  }, [live, current?.id, projectId, rangeId, serviceId]);

  if (!current) return <Panel><p className="py-8 text-center text-sm text-muted">No resources to show a network for.</p></Panel>;

  if (!live) {
    return (
      <Panel title="Networking">
        <DataTable
          rows={choices}
          searchKeys={["name", "public", "network", "host"]}
          columns={[
            { key: "name", label: "Name" },
            { key: "public", label: "Public" },
            { key: "network", label: "Default action", render: (row) => row.network || "—" },
            { key: "addresses", label: "Allowed addresses", render: (row) => row.addresses?.length ? row.addresses.join(", ") : (row.network === "Allow" ? "All networks" : "None listed") },
            { key: "host", label: "Endpoint" },
          ]}
        />
      </Panel>
    );
  }

  return (
    <Panel title="Networking">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <label className="inline-flex items-center gap-1.5 text-xs font-semibold text-muted">
          <span>{serviceId === "sql" ? "Server" : "Server"}</span>
          <select value={current.id} onChange={(event) => { ticket.current += 1; setSelectedId(event.target.value); setRules([]); setSubnets([]); setSavedAt(null); setError(""); setBusy(false); }} className="h-9 rounded-xl border border-line bg-white px-2 text-sm font-medium text-ink outline-none focus:border-brand">
            {choices.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}
          </select>
        </label>
        <button type="button" onClick={() => load(Boolean(savedAt))} disabled={busy} className="h-9 rounded-xl bg-brand px-3 text-sm font-semibold text-white disabled:opacity-50">{busy ? "Reading…" : savedAt ? "Refresh" : "Load allow list"}</button>
        {savedAt && <span className="text-xs text-muted">Kept for an hour</span>}
        <Pill tone={current.public === "Yes" ? "warn" : "ok"}>{current.public === "Yes" ? "Public network on" : "Public network off"}</Pill>
      </div>
      <p className="mb-3 text-sm text-muted">{current.host || "No public endpoint"} · {current.group}</p>
      {error && <p className="mb-3 text-sm text-warn">{error}</p>}
      {current.public === "No" && <p className="mb-3 text-sm text-muted">Public access is off, so clients on the internet are not accepted even if an address is listed.</p>}
      <DataTable
        rows={rules.map((row, index) => ({ ...row, id: `${row.name}-${index}`, note: noteFor(row.start, row.end) }))}
        searchKeys={["name", "start", "end", "note"]}
        columns={[
          { key: "name", label: "Rule" },
          { key: "start", label: "Start IP" },
          { key: "end", label: "End IP" },
          { key: "note", label: "What it allows" },
        ]}
      />
      {subnets.length > 0 && (
        <div className="mt-4">
          <h4 className="mb-2 text-sm font-semibold">Virtual network rules</h4>
          <ul className="space-y-1">
            {subnets.map((name) => <li key={name} className="text-sm">{name}</li>)}
          </ul>
        </div>
      )}
    </Panel>
  );
}
