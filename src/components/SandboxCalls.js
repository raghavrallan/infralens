"use client";

import { useEffect, useMemo, useState } from "react";
import { DataTable, Pill } from "@/components/ui";

function clock(stamp) {
  if (!stamp) return "—";
  return new Date(stamp).toLocaleString();
}

function duration(ms) {
  const value = Number(ms);
  if (!Number.isFinite(value)) return "—";
  if (value < 1000) return `${value} ms`;
  return `${Math.round(value / 100) / 10} s`;
}

function line(row) {
  const verb = [row.command === "rest" ? "az rest" : `az ${row.command}`, row.method].filter(Boolean).join(" ");
  return `${clock(row.at)}  ${row.status}  ${duration(row.durationMs)}  ${verb}  ${row.route}  ${row.caller}${row.detail ? `  ${row.detail}` : ""}`;
}

export function SandboxCalls({ projectId, mode }) {
  const [calls, setCalls] = useState([]);
  const [error, setError] = useState("");
  const [command, setCommand] = useState("all");
  const [status, setStatus] = useState("all");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const params = new URLSearchParams();
      if (projectId) params.set("projectId", projectId);
      const response = await fetch(`/api/estate/calls?${params}`, { cache: "no-store" });
      const body = await response.json().catch(() => ({}));
      if (cancelled) return;
      if (!response.ok) {
        setError(body.message || "Could not read sandbox calls.");
        return;
      }
      setError("");
      setCalls(body.calls || []);
    }
    load();
    const timer = setInterval(load, mode === "live" ? 2000 : 5000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [projectId, mode]);

  const commands = useMemo(() => [...new Set(calls.map((row) => row.command).filter(Boolean))], [calls]);
  const rows = calls
    .filter((row) => command === "all" || row.command === command)
    .filter((row) => status === "all" || row.status === status)
    .map((row, index) => ({
      ...row,
      id: `${row.at}:${index}:${row.route}`,
      when: clock(row.at),
      took: duration(row.durationMs),
      verb: row.method || "—",
    }));

  if (mode === "live") {
    const newest = [...rows].reverse();
    return (
      <div>
        {error && <p className="mb-3 text-sm text-danger">{error}</p>}
        <p className="mb-3 text-sm text-muted">Each line is one Azure CLI command from this project&apos;s sandbox. The list refreshes every few seconds.</p>
        <div className="max-h-[28rem] overflow-auto rounded-2xl border border-line bg-canvas p-3">
          {newest.length === 0 ? (
            <p className="text-sm text-muted">No CLI calls yet. Open a service and read metrics, containers, or logs.</p>
          ) : (
            <pre className="whitespace-pre-wrap font-mono text-xs leading-6 text-ink">{newest.map((row) => line(row)).join("\n")}</pre>
          )}
        </div>
      </div>
    );
  }

  return (
    <div>
      {error && <p className="mb-3 text-sm text-danger">{error}</p>}
      <DataTable
        rows={rows}
        searchKeys={["route", "caller", "connection", "command", "detail"]}
        placeholder="Search a route or caller"
        toolbar={(
          <span className="inline-flex items-center gap-2">
            <label className="inline-flex items-center gap-1.5 text-xs font-semibold text-muted">
              <span>Command</span>
              <select value={command} onChange={(event) => setCommand(event.target.value)} className="h-9 rounded-xl border border-line bg-white px-2 text-sm font-medium text-ink outline-none focus:border-brand">
                <option value="all">All commands</option>
                {commands.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
            </label>
            <label className="inline-flex items-center gap-1.5 text-xs font-semibold text-muted">
              <span>Result</span>
              <select value={status} onChange={(event) => setStatus(event.target.value)} className="h-9 rounded-xl border border-line bg-white px-2 text-sm font-medium text-ink outline-none focus:border-brand">
                <option value="all">Any result</option>
                <option value="ok">ok</option>
                <option value="fail">fail</option>
              </select>
            </label>
          </span>
        )}
        columns={[
          { key: "when", label: "When" },
          { key: "status", label: "Result", render: (row) => <Pill tone={row.status === "ok" ? "ok" : "danger"}>{row.status}</Pill> },
          { key: "connection", label: "Connection" },
          { key: "command", label: "Command" },
          { key: "verb", label: "Method" },
          { key: "route", label: "Route" },
          { key: "caller", label: "Called from" },
          { key: "took", label: "Duration" },
          { key: "detail", label: "Detail" },
        ]}
      />
    </div>
  );
}
