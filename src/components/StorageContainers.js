"use client";

import { useEffect, useState } from "react";
import { DataTable, Panel } from "@/components/ui";
import { useConsole } from "@/context/ConsoleContext";

async function inspect(body) {
  const response = await fetch("/api/compute/inspect", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.message || "Azure did not return those containers.");
  return payload;
}

function bytes(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  const units = [
    [1024 ** 4, "TB"],
    [1024 ** 3, "GB"],
    [1024 ** 2, "MB"],
    [1024, "KB"],
  ];
  for (const [size, label] of units) {
    if (number >= size) return `${Math.round((number / size) * 10) / 10} ${label}`;
  }
  return `${Math.round(number)} B`;
}

function when(value) {
  const time = Date.parse(value);
  if (!Number.isFinite(time)) return "—";
  return new Date(time).toLocaleString();
}

function accessLabel(value) {
  if (!value || value === "None") return "Private";
  return value;
}

function savedLabel(stamp) {
  const time = Number(stamp);
  if (!Number.isFinite(time) || time <= 0) return "";
  const minutes = Math.max(0, Math.round((Date.now() - time) / 60000));
  if (minutes < 1) return "Saved just now";
  if (minutes < 60) return `Saved ${minutes} min ago`;
  return "Saved over an hour ago";
}

export function StorageContainers() {
  const { projectId, rangeId } = useConsole();
  const [accounts, setAccounts] = useState(null);
  const [savedAt, setSavedAt] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function load(fresh) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const payload = await inspect({ action: "containers", projectId, rangeId, serviceId: "storage", fresh });
      setAccounts(payload.accounts || []);
      setSavedAt(payload.cachedAt || null);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    async function warm() {
      try {
        const payload = await inspect({ action: "containers", projectId, rangeId, serviceId: "storage", cacheOnly: true });
        if (cancelled || payload.cacheMiss) return;
        setAccounts(payload.accounts || []);
        setSavedAt(payload.cachedAt || null);
      } catch {
        // The tab stays empty until the user asks.
      }
    }
    warm();
    return () => {
      cancelled = true;
    };
  }, [projectId, rangeId]);

  const containers = (accounts || []).flatMap((account) => (account.containers || []).map((item) => ({
    ...item,
    id: `${account.name}/${item.name}`,
    account: account.name,
    updatedLabel: when(item.updated),
    accessLabel: accessLabel(item.access),
  })));
  const accountRows = (accounts || []).map((account) => {
    const times = (account.containers || []).map((item) => Date.parse(item.updated)).filter(Number.isFinite);
    return {
      id: account.name,
      name: account.name,
      count: account.containers?.length || 0,
      used: bytes(account.used),
      blobs: account.blobs == null ? "—" : String(Math.round(account.blobs)),
      updated: times.length ? new Date(Math.max(...times)).toLocaleString() : "—",
      error: account.error || "",
    };
  });

  return (
    <div className="space-y-4">
      <Panel title="Containers" action={<button type="button" onClick={() => load(Boolean(accounts))} disabled={busy} className="h-9 rounded-xl bg-brand px-3 text-sm font-semibold text-white disabled:opacity-50">{busy ? "Reading…" : accounts ? "Refresh" : "Read containers"}</button>}>
        <p className="mb-3 text-sm text-muted">Each account shows how many blob containers it has, the account&apos;s used size, and when a container was last updated. Azure reports that size for the whole account, not as a separate total inside each container. This copy stays in Redis for an hour. Refresh, or the next schedule, asks Azure again.{savedAt ? ` ${savedLabel(savedAt)}.` : ""}</p>
        {error && <p className="mb-3 text-sm text-warn">{error}</p>}
        {!accounts && <p className="text-sm text-muted">Read containers to load the current list from Azure.</p>}
        {accounts && (
          <DataTable
            rows={accountRows}
            searchKeys={["name", "used", "updated"]}
            columns={[
              { key: "name", label: "Account" },
              { key: "count", label: "Containers" },
              { key: "used", label: "Used size" },
              { key: "blobs", label: "Blobs" },
              { key: "updated", label: "Latest update" },
            ]}
          />
        )}
      </Panel>
      {containers.length > 0 && (
        <Panel title="Container detail">
          <DataTable
            rows={containers}
            searchKeys={["account", "name", "updatedLabel", "accessLabel"]}
            columns={[
              { key: "account", label: "Account" },
              { key: "name", label: "Container" },
              { key: "accessLabel", label: "Access" },
              { key: "updatedLabel", label: "Updated" },
            ]}
          />
        </Panel>
      )}
    </div>
  );
}
