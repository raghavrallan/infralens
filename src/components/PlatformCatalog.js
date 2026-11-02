"use client";

import { useEffect, useRef, useState } from "react";
import { DataTable, Panel } from "@/components/ui";
import { useConsole } from "@/context/ConsoleContext";
import { CATALOG_LABEL } from "@/lib/platform";

async function inspect(body) {
  const response = await fetch("/api/compute/inspect", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.message || "Azure did not return that catalog.");
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

export function PlatformCatalog({ serviceId, rows }) {
  const { projectId, rangeId } = useConsole();
  const [selectedId, setSelectedId] = useState(rows[0]?.id || "");
  const [detail, setDetail] = useState(null);
  const [savedAt, setSavedAt] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const ticket = useRef(0);
  const current = rows.find((row) => row.id === selectedId) || rows[0] || null;
  const label = CATALOG_LABEL[serviceId] || "Catalog";

  async function load(fresh = false) {
    if (!current) return;
    const mine = ++ticket.current;
    const name = current.name;
    const group = current.group;
    setBusy(true);
    setError("");
    try {
      const payload = await inspect({
        action: "catalog",
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
          action: "catalog",
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
        // The catalog stays empty until the user asks.
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
            <select value={current.id} onChange={(event) => { ticket.current += 1; setSelectedId(event.target.value); setDetail(null); setSavedAt(null); setError(""); setBusy(false); }} className="h-9 max-w-xs rounded-xl border border-line bg-white px-2 text-sm font-medium text-ink outline-none focus:border-brand">
              {rows.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}
            </select>
          </label>
          <button type="button" onClick={() => load(Boolean(savedAt))} disabled={busy} className="h-9 rounded-xl bg-brand px-3 text-sm font-semibold text-white disabled:opacity-50">{busy ? "Reading…" : savedAt ? "Refresh" : `Load ${label.toLowerCase()}`}</button>
          {savedAt && <span className="text-xs text-muted">Kept for an hour</span>}
        </div>
        <p className="text-sm text-muted">{current.location || "No region"} · {current.group}. Names only. Secret and key values stay in Azure.</p>
        {error && <p className="mt-3 text-sm text-warn">{error}</p>}
        {detail && !["keys", "secrets", "certificates", "apis", "queues", "topics", "hubs", "runs", "deployments"].some((key) => detail[key]?.length) && (
          <p className="mt-3 text-sm text-muted">Nothing is listed for this resource.</p>
        )}
      </Panel>
      <Table title="Keys" rows={detail?.keys} columns={[{ key: "name", label: "Key" }, { key: "enabled", label: "Enabled" }, { key: "updated", label: "Updated" }]} />
      <Table title="Secrets" rows={detail?.secrets} columns={[{ key: "name", label: "Secret" }, { key: "enabled", label: "Enabled" }, { key: "updated", label: "Updated" }]} />
      <Table title="Certificates" rows={detail?.certificates} columns={[{ key: "name", label: "Certificate" }, { key: "enabled", label: "Enabled" }, { key: "updated", label: "Updated" }]} />
      <Table title="APIs" rows={detail?.apis} columns={[{ key: "name", label: "API" }, { key: "path", label: "Path" }, { key: "revision", label: "Revision" }]} />
      <Table title="Queues" rows={detail?.queues} columns={[{ key: "name", label: "Queue" }, { key: "status", label: "Status" }, { key: "messages", label: "Messages" }]} />
      <Table title="Topics" rows={detail?.topics} columns={[{ key: "name", label: "Topic" }, { key: "status", label: "Status" }]} />
      <Table title="Event hubs" rows={detail?.hubs} columns={[{ key: "name", label: "Hub" }, { key: "partitions", label: "Partitions" }, { key: "retention", label: "Retention days" }]} />
      <Table title="Runs" rows={detail?.runs} columns={[{ key: "name", label: "Run" }, { key: "status", label: "Status" }, { key: "started", label: "Started" }]} />
      <Table title="Deployments" rows={detail?.deployments} columns={[{ key: "name", label: "Deployment" }, { key: "model", label: "Model" }, { key: "version", label: "Version" }, { key: "capacity", label: "Capacity" }]} />
    </div>
  );
}
