"use client";

import { useState } from "react";
import { DataTable } from "@/components/ui";

function size(bytes) {
  const value = Number(bytes) || 0;
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function when(stamp) {
  if (!stamp) return "—";
  return new Date(stamp).toLocaleString();
}

function expires(ttl) {
  if (ttl == null || ttl < 0) return "Expired";
  if (ttl < 60) return `${ttl} sec`;
  return `${Math.round(ttl / 60)} min`;
}

export function RedisCache({ projectId, report, onChange }) {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function remove(payload) {
    setBusy(payload.all ? "all" : payload.id);
    setError("");
    try {
      const response = await fetch("/api/estate/cache", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ projectId, ...payload }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.message || "Could not delete that cache.");
      onChange(body);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  const entries = report?.entries || [];
  const rows = entries.map((item) => ({
    ...item,
    when: when(item.at),
    expires: expires(item.ttl),
    sizeLabel: size(item.bytes),
  }));

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted">
          {size(report?.bytes || 0)} across {report?.count || 0} saved {report?.count === 1 ? "endpoint" : "endpoints"}. Each read stays for an hour. Deleting one makes the next open ask Azure again.
        </p>
        <button
          type="button"
          disabled={busy === "all" || entries.length === 0}
          onClick={() => remove({ all: true })}
          className="h-9 rounded-xl border border-line px-3 text-sm font-semibold disabled:opacity-50"
        >
          {busy === "all" ? "Deleting…" : "Delete all"}
        </button>
      </div>
      {error && <p className="mb-3 text-sm text-danger">{error}</p>}
      <DataTable
        rows={rows}
        searchKeys={["endpoint", "action", "serviceId"]}
        placeholder="Search an endpoint"
        columns={[
          { key: "action", label: "Read" },
          { key: "endpoint", label: "Endpoint" },
          { key: "when", label: "Saved" },
          { key: "expires", label: "Expires" },
          { key: "sizeLabel", label: "Memory" },
          {
            key: "id",
            label: "",
            render: (row) => (
              <button
                type="button"
                disabled={busy === row.id}
                onClick={() => remove({ id: row.id })}
                className="rounded-lg border border-line px-2 py-1 text-xs font-semibold disabled:opacity-50"
              >
                {busy === row.id ? "Deleting…" : "Delete"}
              </button>
            ),
          },
        ]}
      />
    </div>
  );
}
