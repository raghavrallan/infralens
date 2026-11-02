"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { RedisCache } from "@/components/RedisCache";
import { SandboxCalls } from "@/components/SandboxCalls";
import { DataTable, Kpi, PageHead, Panel, Pill } from "@/components/ui";
import { useConsole } from "@/context/ConsoleContext";
import { cash } from "@/lib/format";
import { RANGES } from "@/lib/ranges";

const OPTIONS = [
  ["visit", "Every visit"],
  ["3h", "Every 3 hours"],
  ["12h", "Every 12 hours"],
  ["7d", "Every week"],
];

const TABS = [
  { id: "copies", label: "Saved copies" },
  { id: "services", label: "Services" },
  { id: "tables", label: "Database" },
  { id: "profiles", label: "Profiles" },
  { id: "live", label: "Live logs" },
  { id: "audit", label: "Audit" },
  { id: "redis", label: "Redis" },
];

function size(bytes) {
  const value = Number(bytes) || 0;
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function when(stamp) {
  if (!stamp) return "Not saved";
  return new Date(stamp).toLocaleString();
}

function tableGroup(name) {
  if (String(name).startsWith("estate_")) return "Saved Azure";
  if (["azure_connections", "subscriptions", "project_connections", "project_subscriptions"].includes(name)) return "Azure account";
  if (["users", "org_memberships", "project_memberships", "sessions", "organizations", "projects", "audit_log"].includes(name)) return "People";
  return "Other";
}

function FilterSelect({ label, value, onChange, options }) {
  return (
    <label className="inline-flex items-center gap-1.5 text-xs font-semibold text-muted">
      <span>{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-9 rounded-xl border border-line bg-white px-2 text-sm font-medium text-ink outline-none focus:border-brand"
      >
        {options.map((item) => (
          <option key={item.value} value={item.value}>{item.label}</option>
        ))}
      </select>
    </label>
  );
}

export default function SandboxPage() {
  const { model, projectId, saveSchedule, reloadNow } = useConsole();
  const [report, setReport] = useState(null);
  const [error, setError] = useState("");
  const [cadence, setCadence] = useState(model?.schedule?.cadence || "12h");
  const [saving, setSaving] = useState(false);
  const [tab, setTab] = useState("copies");
  const [cache, setCache] = useState({ bytes: 0, count: 0, entries: [] });
  const ranged = useRef(false);
  const [filters, setFilters] = useState({
    copies: { state: "all", spend: "all" },
    services: { range: model?.range?.id || "all", size: "all" },
    tables: { group: "all", size: "all" },
    profiles: { status: "all", login: "all" },
  });

  useEffect(() => {
    setCadence(model?.schedule?.cadence || report?.cadence || "12h");
  }, [model?.schedule?.cadence, report?.cadence]);

  useEffect(() => {
    const id = model?.range?.id;
    if (!id || ranged.current) return;
    ranged.current = true;
    setFilters((current) => current.services.range === "all" ? { ...current, services: { ...current.services, range: id } } : current);
  }, [model?.range?.id]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const params = new URLSearchParams();
      if (projectId) params.set("projectId", projectId);
      const res = await fetch(`/api/estate/storage?${params}`, { cache: "no-store" });
      const body = await res.json().catch(() => ({}));
      if (cancelled) return;
      if (!res.ok) {
        setError(body.message || "Could not read stored data.");
        return;
      }
      setError("");
      setReport(body);
      const cacheRes = await fetch(`/api/estate/cache?${params}`, { cache: "no-store" });
      const cacheBody = await cacheRes.json().catch(() => ({}));
      if (!cancelled && cacheRes.ok) setCache(cacheBody);
    }
    load();
    const timer = setInterval(load, 5000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [projectId, model?.refreshing, model?.syncedAt]);

  function setFilter(key, value) {
    setFilters((current) => ({ ...current, [tab]: { ...current[tab], [key]: value } }));
  }

  const copies = report?.copies || RANGES.map((range) => ({ id: range.id, label: range.label, saved: false, status: "missing" }));
  const rangeId = model?.range?.id || "mtd";
  const services = report?.services || [];
  const tables = (report?.tables || []).map((item) => ({ ...item, id: item.name, group: tableGroup(item.name), sizeLabel: size(item.bytes) }));
  const profiles = (report?.sandboxes || []).map((item) => ({
    ...item,
    login: item.ready ? "Signed in" : "Waiting",
    seen: when(item.lastLoginAt || item.checkedAt),
  }));

  const view = useMemo(() => {
    if (tab === "copies") {
      const chosen = filters.copies;
      const rows = copies
        .filter((item) => chosen.state === "all" || item.status === chosen.state)
        .filter((item) => chosen.spend === "all" || (chosen.spend === "with" ? item.spend != null : item.spend == null))
        .map((item) => ({ ...item, when: when(item.syncedAt), sizeLabel: size(item.bytes) }));
      const states = [...new Set(copies.map((item) => item.status).filter(Boolean))];
      return {
        rows,
        searchKeys: ["label", "status"],
        placeholder: "Search a date range",
        columns: [
          { key: "label", label: "Range" },
          { key: "status", label: "State", render: (row) => <Pill tone={row.status === "ready" ? "ok" : row.status === "syncing" ? "warn" : "muted"}>{row.status}</Pill> },
          { key: "resources", label: "Resources", align: "right" },
          { key: "subscriptions", label: "Subscriptions", align: "right" },
          { key: "services", label: "Cost services", align: "right" },
          { key: "alerts", label: "Alerts", align: "right" },
          { key: "spend", label: "Spend", align: "right", render: (row) => row.spend == null ? "—" : cash(row.spend, row.currency) },
          { key: "sizeLabel", label: "Stored" },
          { key: "when", label: "Saved at" },
        ],
        toolbar: (
          <span className="inline-flex items-center gap-2">
            <FilterSelect label="State" value={chosen.state} onChange={(value) => setFilter("state", value)} options={[{ value: "all", label: "All states" }, ...states.map((item) => ({ value: item, label: item }))]} />
            <FilterSelect label="Spend" value={chosen.spend} onChange={(value) => setFilter("spend", value)} options={[{ value: "all", label: "Any spend" }, { value: "with", label: "Has spend" }, { value: "without", label: "No spend" }]} />
          </span>
        ),
      };
    }
    if (tab === "services") {
      const chosen = filters.services;
      const rows = services
        .filter((item) => chosen.range === "all" || item.rangeId === chosen.range)
        .filter((item) => chosen.size === "all" || (chosen.size === "large" ? item.count >= 10 : item.count < 10))
        .map((item) => ({
          id: `${item.rangeId}:${item.name}`,
          name: item.name,
          count: item.count,
          range: RANGES.find((range) => range.id === item.rangeId)?.label || item.rangeId,
        }));
      return {
        rows,
        searchKeys: ["name", "range"],
        placeholder: "Search a service",
        columns: [
          { key: "name", label: "Service" },
          { key: "range", label: "Range" },
          { key: "count", label: "Stored resources", align: "right" },
        ],
        toolbar: (
          <span className="inline-flex items-center gap-2">
            <FilterSelect label="Range" value={chosen.range} onChange={(value) => setFilter("range", value)} options={[{ value: "all", label: "All ranges" }, ...RANGES.map((item) => ({ value: item.id, label: item.label }))]} />
            <FilterSelect label="Count" value={chosen.size} onChange={(value) => setFilter("size", value)} options={[{ value: "all", label: "Any count" }, { value: "small", label: "Under 10" }, { value: "large", label: "10 or more" }]} />
          </span>
        ),
      };
    }
    if (tab === "tables") {
      const chosen = filters.tables;
      const rows = tables
        .filter((item) => chosen.group === "all" || item.group === chosen.group)
        .filter((item) => chosen.size === "all" || (chosen.size === "large" ? item.bytes >= 100 * 1024 : item.bytes < 100 * 1024));
      const groups = [...new Set(tables.map((item) => item.group))];
      return {
        rows,
        searchKeys: ["label", "name", "group"],
        placeholder: "Search a table",
        columns: [
          { key: "label", label: "What is stored" },
          { key: "name", label: "Table" },
          { key: "group", label: "Group" },
          { key: "rows", label: "Rows", align: "right" },
          { key: "sizeLabel", label: "Size" },
        ],
        toolbar: (
          <span className="inline-flex items-center gap-2">
            <FilterSelect label="Group" value={chosen.group} onChange={(value) => setFilter("group", value)} options={[{ value: "all", label: "All groups" }, ...groups.map((item) => ({ value: item, label: item }))]} />
            <FilterSelect label="Size" value={chosen.size} onChange={(value) => setFilter("size", value)} options={[{ value: "all", label: "Any size" }, { value: "small", label: "Under 100 KB" }, { value: "large", label: "100 KB or more" }]} />
          </span>
        ),
      };
    }
    const chosen = filters.profiles;
    const rows = profiles
      .filter((item) => chosen.status === "all" || item.status === chosen.status)
      .filter((item) => chosen.login === "all" || (chosen.login === "ready" ? item.ready : !item.ready));
    const statuses = [...new Set(profiles.map((item) => item.status).filter(Boolean))];
    return {
      rows,
      searchKeys: ["name", "status", "login"],
      placeholder: "Search a connection",
      columns: [
        { key: "name", label: "Connection" },
        { key: "status", label: "Status", render: (row) => <Pill tone={row.status === "connected" ? "ok" : "warn"}>{row.status || "pending"}</Pill> },
        { key: "login", label: "CLI profile", render: (row) => <Pill tone={row.ready ? "ok" : "muted"}>{row.login}</Pill> },
        { key: "transport", label: "Reads" },
        { key: "seen", label: "Last login" },
      ],
      toolbar: (
        <span className="inline-flex items-center gap-2">
          <FilterSelect label="Status" value={chosen.status} onChange={(value) => setFilter("status", value)} options={[{ value: "all", label: "All statuses" }, ...statuses.map((item) => ({ value: item, label: item }))]} />
          <FilterSelect label="Profile" value={chosen.login} onChange={(value) => setFilter("login", value)} options={[{ value: "all", label: "Any profile" }, { value: "ready", label: "Signed in" }, { value: "waiting", label: "Waiting" }]} />
        </span>
      ),
    };
  }, [tab, filters, copies, services, tables, profiles]);

  const saved = copies.filter((item) => item.saved).length;
  const current = copies.find((item) => item.id === rangeId);

  return (
    <div className="space-y-4">
      <PageHead
        eyebrow={report?.project?.name || model?.project?.name}
        title="Sandbox"
        description="Azure reads for this project run as az CLI inside the sandbox profile. Live logs and Audit list each command, the Azure route, and the page that called it."
      />
      {error && <p className="text-sm text-danger">{error}</p>}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi label="Saved copies" value={`${saved} of ${copies.length}`} hint={`${size(report?.snapshotBytes || 0)} of Azure data`} />
        <Kpi label="Database" value={size(report?.storedBytes || 0)} hint={`${tables.length} tables`} tone="info" />
        <Kpi label="This range" value={current?.resources || 0} hint={current?.label || "Resources stored"} tone="ok" />
        <Kpi label="Redis cache" value={size(cache.bytes || 0)} hint={`${cache.count || 0} saved endpoints`} />
      </div>
      <Panel>
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <div className="flex flex-wrap items-center gap-1 rounded-2xl bg-canvas p-1">
            {OPTIONS.map(([id, label]) => (
              <button
                key={id}
                type="button"
                onClick={() => setCadence(id)}
                className={`rounded-xl px-3 py-1.5 text-xs font-semibold ${cadence === id ? "bg-white text-ink shadow-sm" : "text-muted"}`}
              >
                {label}
              </button>
            ))}
          </div>
          <button
            type="button"
            disabled={saving}
            className="rounded-xl bg-brand px-3 py-2 text-sm font-semibold text-white disabled:opacity-60"
            onClick={async () => {
              setSaving(true);
              await saveSchedule(cadence);
              setSaving(false);
            }}
          >
            {saving ? "Saving…" : "Save schedule"}
          </button>
          <button type="button" className="rounded-xl border border-line px-3 py-2 text-sm font-semibold" onClick={reloadNow}>
            Reload this range now
          </button>
          <span className="text-xs text-muted">Redis db {report?.redisDb ?? 1} · {report?.queue || "estate"}</span>
        </div>
        <div className="mb-3 inline-flex flex-wrap gap-1 rounded-2xl bg-canvas p-1">
          {TABS.map((item) => {
            const count = item.id === "copies" ? copies.length : item.id === "services" ? services.length : item.id === "tables" ? tables.length : item.id === "profiles" ? profiles.length : item.id === "redis" ? cache.count || 0 : null;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => setTab(item.id)}
                className={`rounded-xl px-3 py-1.5 text-xs font-semibold ${tab === item.id ? "bg-white text-ink shadow-sm" : "text-muted"}`}
              >
                {item.label}
                {count != null && <span className="ml-1.5 tabular-nums text-muted">{count}</span>}
              </button>
            );
          })}
        </div>
        {tab === "live" || tab === "audit" ? (
          <SandboxCalls projectId={projectId} mode={tab} />
        ) : tab === "redis" ? (
          <RedisCache projectId={projectId} report={cache} onChange={setCache} />
        ) : (
          <DataTable
            key={tab}
            rows={view.rows}
            columns={view.columns}
            searchKeys={view.searchKeys}
            placeholder={view.placeholder}
            toolbar={view.toolbar}
          />
        )}
      </Panel>
    </div>
  );
}
