"use client";

import { useEffect, useRef, useState } from "react";
import { DataTable, Panel } from "@/components/ui";
import { useConsole } from "@/context/ConsoleContext";
import { LAYOUT_LABEL } from "@/lib/network";

async function inspect(body) {
  const response = await fetch("/api/compute/inspect", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.message || "Azure did not return that network detail.");
  return payload;
}

function forResource(payload, name, group) {
  const subject = payload?.subject;
  if (!subject) return true;
  return String(subject.name || "").toLowerCase() === String(name || "").toLowerCase() && String(subject.group || "") === String(group || "");
}

function Table({ title, rows, columns }) {
  if (!rows?.length) return null;
  return (
    <Panel title={title}>
      <DataTable rows={rows.map((row, index) => ({ ...row, id: `${row.name || "row"}-${index}` }))} searchKeys={columns.map((column) => column.key)} columns={columns} />
    </Panel>
  );
}

export function NetworkLayout({ serviceId, rows }) {
  const { projectId, rangeId } = useConsole();
  const [selectedId, setSelectedId] = useState(rows[0]?.id || "");
  const [detail, setDetail] = useState(null);
  const [savedAt, setSavedAt] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const ticket = useRef(0);
  const current = rows.find((row) => row.id === selectedId) || rows[0] || null;
  const label = LAYOUT_LABEL[serviceId] || "Detail";

  async function load(fresh = false) {
    if (!current) return;
    const mine = ++ticket.current;
    const name = current.name;
    const group = current.group;
    setBusy(true);
    setError("");
    try {
      const payload = await inspect({
        action: "layout",
        projectId,
        rangeId,
        serviceId,
        name,
        group,
        fresh,
      });
      if (ticket.current !== mine || !forResource(payload, name, group)) return;
      setDetail(payload);
      setSavedAt(payload.cachedAt || null);
    } catch (err) {
      if (ticket.current === mine) setError(err.message);
    } finally {
      if (ticket.current === mine) setBusy(false);
    }
  }

  useEffect(() => {
    if (!current) return undefined;
    let cancelled = false;
    async function warm() {
      try {
        const payload = await inspect({
          action: "layout",
          cacheOnly: true,
          projectId,
          rangeId,
          serviceId,
          name: current.name,
          group: current.group,
        });
        if (cancelled || payload.cacheMiss || !forResource(payload, current.name, current.group)) return;
        setDetail(payload);
        setSavedAt(payload.cachedAt || null);
      } catch {
        // The detail stays empty until the user asks.
      }
    }
    warm();
    return () => {
      cancelled = true;
    };
  }, [current?.id, projectId, rangeId, serviceId]);

  if (!current) return <Panel><p className="py-8 text-center text-sm text-muted">No resources in this service yet.</p></Panel>;

  return (
    <div className="space-y-4">
      <Panel title={label}>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <label className="inline-flex items-center gap-1.5 text-xs font-semibold text-muted">
            <span>Resource</span>
            <select value={current.id} onChange={(event) => { ticket.current += 1; setSelectedId(event.target.value); setDetail(null); setSavedAt(null); setError(""); setBusy(false); }} className="h-9 rounded-xl border border-line bg-white px-2 text-sm font-medium text-ink outline-none focus:border-brand">
              {rows.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}
            </select>
          </label>
          <button type="button" onClick={() => load(Boolean(savedAt))} disabled={busy} className="h-9 rounded-xl bg-brand px-3 text-sm font-semibold text-white disabled:opacity-50">{busy ? "Reading…" : savedAt ? "Refresh" : `Load ${label.toLowerCase()}`}</button>
          {savedAt && <span className="text-xs text-muted">Kept for an hour</span>}
        </div>
        <p className="text-sm text-muted">{current.location || "No region"} · {current.group}</p>
        {error && <p className="mt-3 text-sm text-warn">{error}</p>}
      </Panel>
      <Table title="Subnets" rows={detail?.subnets} columns={[{ key: "name", label: "Subnet" }, { key: "prefix", label: "Prefix" }, { key: "nsg", label: "NSG" }, { key: "delegation", label: "Delegation" }]} />
      <Table title="Listeners" rows={detail?.listeners} columns={[{ key: "name", label: "Listener" }, { key: "protocol", label: "Protocol" }, { key: "host", label: "Host" }, { key: "port", label: "Port" }]} />
      <Table title="Backend pools" rows={detail?.backends} columns={[{ key: "name", label: "Pool" }, { key: "addresses", label: "Addresses" }]} />
      <Table title="Rules" rows={detail?.rules} columns={[{ key: "name", label: "Rule" }, { key: "protocol", label: "Protocol" }, { key: "frontend", label: "Frontend port" }, { key: "backend", label: "Backend port" }]} />
      <Table title="Probes" rows={detail?.probes} columns={[{ key: "name", label: "Probe" }, { key: "protocol", label: "Protocol" }, { key: "port", label: "Port" }, { key: "path", label: "Path" }]} />
      <Table title="Endpoints" rows={detail?.endpoints} columns={[{ key: "name", label: "Endpoint" }, { key: "host", label: "Host" }, { key: "state", label: "State" }]} />
    </div>
  );
}
