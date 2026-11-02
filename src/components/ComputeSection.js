"use client";

import { useEffect, useMemo, useState } from "react";
import { MetricsBoard, RevisionsBoard } from "@/components/ComputeBoards";
import { RankBars } from "@/components/Charts";
import { AlertDrawer } from "@/components/AlertDetail";
import { DataTable, Drawer, Kpi, PageHead, Panel, Pill, stateTone } from "@/components/ui";
import { severityLabel } from "@/lib/alerts";
import { useConsole } from "@/context/ConsoleContext";
import { COMPUTE_DEPTH, healthBucket, operationsFor, overviewFacets, resourcesFor, signalValue } from "@/lib/compute";
import { NetworkBoard } from "@/components/DataNetwork";
import { StorageContainers } from "@/components/StorageContainers";
import { DATA_DEPTH, essentialsFor, overviewFacets as dataFacets, resourcesFor as dataResources } from "@/lib/data";
import { NetworkLayout } from "@/components/NetworkLayout";
import { LAYOUT_LABEL, NETWORK_DEPTH, overviewFacets as networkFacets, resourcesFor as networkResources } from "@/lib/network";
import { PlatformCatalog } from "@/components/PlatformCatalog";
import { CATALOG_LABEL, PLATFORM_DEPTH, overviewFacets as platformFacets, resourcesFor as platformResources } from "@/lib/platform";
import { num } from "@/lib/format";
import { serviceById } from "@/lib/services";

const TABS = [
  ["overview", "Overview"],
  ["inventory", "Inventory"],
  ["activity", "Activity log"],
  ["metrics", "Metrics"],
  ["availability", "Availability"],
  ["alerts", "Alerts"],
];

const STATUS_COLOR = {
  healthy: "#0BAA60",
  stopped: "#717171",
  attention: "#D4537E",
  other: "#E2773C",
};

function FilterSelect({ label, value, onChange, options }) {
  return (
    <label className="inline-flex items-center gap-1.5 text-xs font-semibold text-muted">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)} className="h-9 rounded-xl border border-line bg-white px-2 text-sm font-medium text-ink outline-none focus:border-brand">
        {options.map((item) => (
          <option key={item.value} value={item.value}>{item.label}</option>
        ))}
      </select>
    </label>
  );
}

function choices(rows, key, label) {
  const values = [...new Set(rows.map((row) => row[key]).filter(Boolean))].sort((a, b) => String(a).localeCompare(String(b)));
  return [{ value: "all", label }, ...values.map((value) => ({ value, label: value }))];
}

function when(value) {
  const time = Date.parse(value);
  if (!Number.isFinite(time)) return value || "";
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(time));
}

function countBy(rows, key) {
  const map = new Map();
  for (const row of rows) {
    const name = row[key] || "Unknown";
    map.set(name, (map.get(name) || 0) + 1);
  }
  return [...map.entries()]
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value);
}

function Empty({ children }) {
  return <p className="py-8 text-center text-sm text-muted">{children}</p>;
}

function Breakdown({ title, hint, data, rows, detail }) {
  return (
    <Panel title={title} className="flex h-full flex-col">
      <p className="mb-3 text-xs text-muted">{hint || "Nothing to split yet."}</p>
      {data.length ? <RankBars data={data} /> : <Empty>No resources in this service yet.</Empty>}
      {rows.length > 0 && (
        <ul className="mt-3 space-y-1 border-t border-line pt-3">
          {rows.slice(0, 6).map((row) => (
            <li key={row.id || row.name} className="flex items-center justify-between gap-3 text-xs">
              <span className="truncate font-medium text-ink">{row.name}</span>
              <span className="shrink-0 text-muted">{detail(row)}</span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

export default function ComputeSection({ serviceId }) {
  const spec = COMPUTE_DEPTH[serviceId] || DATA_DEPTH[serviceId] || NETWORK_DEPTH[serviceId] || PLATFORM_DEPTH[serviceId];
  const dataService = Boolean(DATA_DEPTH[serviceId]);
  const networkService = Boolean(NETWORK_DEPTH[serviceId]);
  const platformService = Boolean(PLATFORM_DEPTH[serviceId]);
  const { model } = useConsole();
  const [mounted, setMounted] = useState(false);
  const [tab, setTab] = useState("overview");
  const [selected, setSelected] = useState(null);
  const [alert, setAlert] = useState(null);
  const [filters, setFilters] = useState({
    inventoryStatus: "all",
    activityStatus: "all",
    region: "all",
    group: "all",
    zone: "all",
    https: "all",
    ingress: "all",
    public: "all",
    severity: "all",
  });
  const rows = useMemo(() => {
    if (!model) return [];
    if (dataService) return dataResources(model, serviceId);
    if (networkService) return networkResources(model, serviceId);
    if (platformService) return platformResources(model, serviceId);
    return resourcesFor(model, serviceId);
  }, [model, serviceId, dataService, networkService, platformService]);
  const operations = useMemo(() => (model ? operationsFor(model, serviceId, rows) : []), [model, serviceId, rows]);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted || !spec || !model || model.status !== "ready") return null;

  const groups = new Set(rows.map((row) => row.group));
  const alerts = (model.alerts || []).filter((item) => groups.has(item.group));
  const healthy = rows.filter((row) => healthBucket(row.status) === "healthy").length;
  const stopped = rows.filter((row) => healthBucket(row.status) === "stopped").length;
  const attention = rows.filter((row) => healthBucket(row.status) === "attention").length;
  const regions = new Set(rows.map((row) => row.location).filter(Boolean)).size;

  function setFilter(key, value) {
    setFilters((current) => ({ ...current, [key]: value }));
  }

  const inventory = rows.filter((row) => {
    if (filters.inventoryStatus !== "all" && row.status !== filters.inventoryStatus) return false;
    if (filters.region !== "all" && row.location !== filters.region) return false;
    if (filters.group !== "all" && row.group !== filters.group) return false;
    return true;
  });
  const activity = operations.filter((row) => filters.activityStatus === "all" || row.status === filters.activityStatus);
  const availability = rows.filter((row) => {
    if (filters.zone === "zonal" && row.zone === "None") return false;
    if (filters.zone === "none" && row.zone !== "None") return false;
    if (filters.https !== "all" && row.https !== filters.https) return false;
    if (filters.ingress !== "all" && row.ingress !== filters.ingress) return false;
    if (filters.public !== "all" && row.public !== filters.public) return false;
    return true;
  });
  const alertRows = alerts.filter((row) => filters.severity === "all" || String(row.severity) === filters.severity);
  const selectedOps = selected ? operations.filter((item) => String(item.resource || "").toLowerCase() === String(selected.name || "").toLowerCase()) : [];

  const statusBars = ["healthy", "stopped", "attention", "other"].map((bucket) => ({
    name: bucket === "healthy" ? "Healthy" : bucket === "stopped" ? "Stopped" : bucket === "attention" ? "Attention" : "Other",
    value: rows.filter((row) => healthBucket(row.status) === bucket).length,
    color: STATUS_COLOR[bucket],
  })).filter((item) => item.value);
  const regionBars = countBy(rows, "location").slice(0, 8).map((item) => ({ ...item, color: "#0084FF" }));
  const facet = dataService ? dataFacets(serviceId) : networkService ? networkFacets(serviceId) : platformService ? platformFacets(serviceId) : overviewFacets(serviceId);

  const columns = spec.columns.map(([key, label]) => ({
    key,
    label,
    render: key === "status" ? (row) => <Pill tone={stateTone(row.status)}>{row.status}</Pill> : undefined,
  }));

  return (
    <div className="space-y-4">
      <PageHead eyebrow={model.project.name} title={serviceById(serviceId)?.label || serviceTitle(serviceId)} description={spec.summary} />
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <Kpi label="Resources" value={num(rows.length)} hint={`${num(regions)} regions`} />
        <Kpi label="Healthy" value={num(healthy)} hint="Running or succeeded" tone="ok" />
        <Kpi label="Stopped" value={num(stopped)} hint={`${num(attention)} need attention`} tone={attention ? "danger" : "warn"} />
        <Kpi label="Activity" value={num(operations.length)} hint="Operations in the saved log" tone="info" />
      </div>
      <div className="inline-flex w-fit flex-wrap gap-1 rounded-xl bg-white p-1">
        {tabsFor(serviceId, rows).map(([id, label]) => (
          <button key={id} type="button" onClick={() => setTab(id)} className={`rounded-lg px-3 py-1.5 text-sm font-semibold ${tab === id ? "bg-orange-50 text-ink" : "text-muted"}`}>
            {label}
          </button>
        ))}
      </div>
      {tab === "overview" && (
        <div className="grid grid-cols-1 items-stretch gap-4 md:grid-cols-2">
          <Breakdown title="Status" hint={`${healthy} healthy · ${stopped} stopped · ${attention} need attention`} data={statusBars} rows={rows} detail={(row) => `${row.status} · ${row.location || "no region"}`} />
          <Breakdown title="Regions" hint={regionBars.map((item) => `${item.name} ${item.value}`).join(" · ") || "No regions yet"} data={regionBars} rows={rows} detail={(row) => row.location || "No region"} />
          <Breakdown title={facet[1]} hint="How this service is split, with the resources in each bar" data={countBy(rows, facet[0]).slice(0, 8).map((item) => ({ ...item, color: "#0BAA60" }))} rows={rows} detail={(row) => row[facet[0]] || "Not set"} />
          <Breakdown title="Resource groups" hint={countBy(rows, "group").slice(0, 4).map((item) => `${item.name} ${item.value}`).join(" · ") || "No groups yet"} data={countBy(rows, "group").slice(0, 8).map((item) => ({ ...item, color: "#7C6AE8" }))} rows={rows} detail={(row) => row.group || "No group"} />
          <Panel title="Recent activity" className="md:col-span-2">
            {operations.length === 0 ? <Empty>No operations for these resources are in the saved activity log.</Empty> : (
              <ul className="divide-y divide-line">
                {operations.slice(0, 6).map((item) => (
                  <li key={item.id} className="flex flex-wrap items-center gap-3 py-2.5 text-sm">
                    <Pill tone={stateTone(item.status)}>{item.status || "Logged"}</Pill>
                    <span className="min-w-0 flex-1 truncate font-medium">{item.text}</span>
                    <span className="truncate text-muted">{item.resource}</span>
                    <span className="text-xs text-muted">{when(item.time)}</span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
      )}
      {tab === "servers" && (
        <ResourceTable rows={rows.filter((row) => row.role === "Server")} filters={filters} setFilter={setFilter} empty="This project has no SQL servers." columns={[
          ["name", "Server"], ["status", "Status"], ["public", "Public"], ["host", "Endpoint"], ["location", "Region"], ["group", "Resource group"],
        ]} onRow={setSelected} />
      )}
      {tab === "databases" && (
        <ResourceTable rows={rows.filter((row) => row.role === "Database")} filters={filters} setFilter={setFilter} empty="This project has no SQL databases." columns={[
          ["name", "Database"], ["status", "Status"], ["server", "Server"], ["compute", "Compute"], ["vCores", "vCores"], ["memory", "Memory"], ["storage", "Max storage"], ["location", "Region"],
        ]} onRow={setSelected} />
      )}
      {tab === "pools" && (
        <ResourceTable rows={rows.filter((row) => row.role === "Pool")} filters={filters} setFilter={setFilter} empty="This project has no elastic pools." columns={[
          ["name", "Pool"], ["status", "Status"], ["server", "Server"], ["vCores", "vCores"], ["memory", "Memory"], ["storage", "Max storage"], ["location", "Region"],
        ]} onRow={setSelected} />
      )}
      {tab === "containers" && <StorageContainers />}
      {tab === "layout" && <NetworkLayout serviceId={serviceId} rows={rows} />}
      {tab === "catalog" && <PlatformCatalog serviceId={serviceId} rows={rows} />}
      {tab === "networking" && <NetworkBoard serviceId={serviceId} rows={rows} />}
      {tab === "inventory" && (
        <Panel>
          {rows.length === 0 ? <Empty>This project has no resources for this service.</Empty> : (
            <DataTable
              rows={inventory}
              searchKeys={["name", "status", "group", "location", "size", "os", "host", "plan", "runtime", "sku", "role", "version", "kind", "public", "api", "address", "subnets", "ddos", "waf", "threat", "soft", "purge", "rbac", "vnet", "local", "domain", "kafka", "inflate", "tier", "capacity"]}
              toolbar={(
                <span className="inline-flex flex-wrap gap-2">
                  <FilterSelect label="Status" value={filters.inventoryStatus} onChange={(value) => setFilter("inventoryStatus", value)} options={choices(rows, "status", "Any status")} />
                  <FilterSelect label="Region" value={filters.region} onChange={(value) => setFilter("region", value)} options={choices(rows, "location", "Any region")} />
                  <FilterSelect label="Group" value={filters.group} onChange={(value) => setFilter("group", value)} options={choices(rows, "group", "Any group")} />
                </span>
              )}
              columns={columns}
              onRow={setSelected}
            />
          )}
        </Panel>
      )}
      {tab === "activity" && (
        <Panel>
          {operations.length === 0 ? <Empty>No operations for these resources are in the saved activity log.</Empty> : (
            <DataTable
              rows={activity}
              searchKeys={["text", "resource", "caller", "status"]}
              toolbar={<FilterSelect label="Status" value={filters.activityStatus} onChange={(value) => setFilter("activityStatus", value)} options={choices(operations, "status", "Any status")} />}
              columns={[
                { key: "time", label: "Time", render: (row) => when(row.time) },
                { key: "status", label: "Status", render: (row) => <Pill tone={stateTone(row.status)}>{row.status || "Logged"}</Pill> },
                { key: "text", label: "Operation" },
                { key: "resource", label: "Resource" },
                { key: "caller", label: "Caller" },
              ]}
            />
          )}
        </Panel>
      )}
      {tab === "metrics" && (
        <MetricsBoard serviceId={serviceId} rows={serviceId === "sql" ? rows.filter((row) => row.role === "Database" && row.name.toLowerCase() !== "master") : rows} region={filters.region} regions={choices(rows, "location", "Any region")} onRegion={(value) => setFilter("region", value)} />
      )}
      {tab === "revisions" && serviceId === "container-apps" && <RevisionsBoard rows={rows} />}
      {tab === "availability" && (
        <Panel>
          {rows.length === 0 ? <Empty>Nothing to judge availability against.</Empty> : (
            <DataTable
              rows={availability}
              searchKeys={["name", "status", "zone", "https", "ingress", "provisioning"]}
              toolbar={availabilityFilters(serviceId, filters, setFilter, rows)}
              columns={[
                { key: "name", label: "Name" },
                ...spec.availability.map(([key, label]) => ({
                  key,
                  label,
                  render: key === "status" ? (row) => <Pill tone={stateTone(row.status)}>{row.status}</Pill> : undefined,
                })),
              ]}
              onRow={setSelected}
            />
          )}
        </Panel>
      )}
      {tab === "alerts" && (
        <Panel>
          {alerts.length === 0 ? <Empty>No metric alert rules are saved for the resource groups that hold this service.</Empty> : (
            <DataTable
              rows={alertRows}
              searchKeys={["name", "group", "state", "severity", "signal", "description"]}
              toolbar={<FilterSelect label="Severity" value={filters.severity} onChange={(value) => setFilter("severity", value)} options={choices(alerts, "severity", "Any severity")} />}
              onRow={setAlert}
              columns={[
                { key: "name", label: "Alert" },
                { key: "signal", label: "Condition", render: (row) => <span className="block max-w-xs truncate">{row.signal || "—"}</span> },
                { key: "severity", label: "Severity", render: (row) => <Pill tone={Number(row.severity) <= 1 ? "danger" : Number(row.severity) === 2 ? "warn" : "muted"}>{severityLabel(row.severity)}</Pill> },
                { key: "state", label: "State", render: (row) => <Pill tone={stateTone(row.state)}>{row.state}</Pill> },
                { key: "group", label: "Resource group" },
              ]}
            />
          )}
        </Panel>
      )}
      <Drawer open={Boolean(selected)} title={selected?.name || ""} subtitle={selected ? `${selected.group} · ${selected.location}` : ""} onClose={() => setSelected(null)}>
        {selected && (
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <Pill tone={stateTone(selected.status)}>{selected.status}</Pill>
              {selected.signal && spec.metric && <span className="text-sm text-muted">{spec.metric.label} {signalValue(selected.signal.value, selected.signal.unit)}</span>}
            </div>
            <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
              {(dataService ? essentialsFor(serviceId, selected) : spec.essentials).map(([key, label]) => (
                <div key={key}>
                  <dt className="text-[11px] font-semibold uppercase tracking-wide text-muted">{label}</dt>
                  <dd className="mt-0.5 break-words text-ink">{selected[key] || "—"}</dd>
                </div>
              ))}
            </dl>
            <div>
              <h4 className="text-sm font-semibold">Activity</h4>
              {selectedOps.length === 0 ? <p className="mt-1 text-sm text-muted">No saved operations name this resource.</p> : (
                <ul className="mt-2 space-y-2">
                  {selectedOps.slice(0, 6).map((item) => (
                    <li key={item.id} className="text-sm">
                      <span className="font-medium">{item.text}</span>
                      <span className="mt-0.5 block text-xs text-muted">{item.status} · {when(item.time)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}
      </Drawer>
      <AlertDrawer alert={alert} onClose={() => setAlert(null)} />
    </div>
  );
}

function tabsFor(serviceId, rows) {
  if (serviceId === "container-apps") {
    return [["overview", "Overview"], ["inventory", "Inventory"], ["activity", "Activity log"], ["metrics", "Metrics"], ["revisions", "Revisions"], ["availability", "Availability"], ["alerts", "Alerts"]];
  }
  if (serviceId === "sql") {
    const tabs = [["overview", "Overview"], ["servers", "Servers"], ["databases", "Databases"]];
    if (rows.some((row) => row.role === "Pool")) tabs.push(["pools", "Pools"]);
    tabs.push(["networking", "Networking"], ["activity", "Activity log"], ["metrics", "Metrics"], ["availability", "Availability"], ["alerts", "Alerts"]);
    return tabs;
  }
  if (serviceId === "storage") {
    return [["overview", "Overview"], ["inventory", "Inventory"], ["containers", "Containers"], ["networking", "Networking"], ["activity", "Activity log"], ["metrics", "Metrics"], ["availability", "Availability"], ["alerts", "Alerts"]];
  }
  if (DATA_DEPTH[serviceId]) {
    return [["overview", "Overview"], ["inventory", "Inventory"], ["networking", "Networking"], ["activity", "Activity log"], ["metrics", "Metrics"], ["availability", "Availability"], ["alerts", "Alerts"]];
  }
  if (NETWORK_DEPTH[serviceId]) {
    return [["overview", "Overview"], ["inventory", "Inventory"], ["layout", LAYOUT_LABEL[serviceId] || "Detail"], ["activity", "Activity log"], ["metrics", "Metrics"], ["availability", "Availability"], ["alerts", "Alerts"]];
  }
  if (PLATFORM_DEPTH[serviceId]) {
    return [["overview", "Overview"], ["inventory", "Inventory"], ["catalog", CATALOG_LABEL[serviceId] || "Catalog"], ["activity", "Activity log"], ["metrics", "Metrics"], ["availability", "Availability"], ["alerts", "Alerts"]];
  }
  return TABS;
}

function ResourceTable({ rows, filters, setFilter, empty, columns, onRow }) {
  const shown = rows.filter((row) => {
    if (filters.inventoryStatus !== "all" && row.status !== filters.inventoryStatus) return false;
    if (filters.region !== "all" && row.location !== filters.region) return false;
    if (filters.group !== "all" && row.group !== filters.group) return false;
    return true;
  });
  return (
    <Panel>
      {rows.length === 0 ? <Empty>{empty}</Empty> : (
        <DataTable
          rows={shown}
          searchKeys={["name", "status", "server", "group", "location", "sku", "vCores", "memory", "storage", "host", "public", "compute"]}
          toolbar={(
            <span className="inline-flex flex-wrap gap-2">
              <FilterSelect label="Status" value={filters.inventoryStatus} onChange={(value) => setFilter("inventoryStatus", value)} options={choices(rows, "status", "Any status")} />
              <FilterSelect label="Region" value={filters.region} onChange={(value) => setFilter("region", value)} options={choices(rows, "location", "Any region")} />
              <FilterSelect label="Group" value={filters.group} onChange={(value) => setFilter("group", value)} options={choices(rows, "group", "Any group")} />
            </span>
          )}
          columns={columns.map(([key, label]) => ({
            key,
            label,
            render: key === "status" ? (row) => <Pill tone={stateTone(row.status)}>{row.status}</Pill> : undefined,
          }))}
          onRow={onRow}
        />
      )}
    </Panel>
  );
}

function serviceTitle(serviceId) {
  const titles = {
    "virtual-machines": "Virtual machines",
    "vm-scale-sets": "VM scale sets",
    "app-service": "App Service",
    functions: "Functions",
    "container-apps": "Container Apps",
    kubernetes: "Kubernetes",
  };
  return titles[serviceId] || "Compute";
}

function availabilityFilters(serviceId, filters, setFilter, rows) {
  if (serviceId === "app-service" || serviceId === "functions") {
    return <FilterSelect label="HTTPS" value={filters.https} onChange={(value) => setFilter("https", value)} options={choices(rows, "https", "Any HTTPS")} />;
  }
  if (serviceId === "container-apps") {
    return <FilterSelect label="Ingress" value={filters.ingress} onChange={(value) => setFilter("ingress", value)} options={choices(rows, "ingress", "Any ingress")} />;
  }
  if (serviceId === "storage") {
    return (
      <span className="inline-flex flex-wrap gap-2">
        <FilterSelect label="HTTPS" value={filters.https} onChange={(value) => setFilter("https", value)} options={choices(rows, "https", "Any HTTPS")} />
        <FilterSelect label="Public blob" value={filters.public} onChange={(value) => setFilter("public", value)} options={choices(rows, "public", "Any public access")} />
      </span>
    );
  }
  if (DATA_DEPTH[serviceId]) {
    return <FilterSelect label="Public" value={filters.public} onChange={(value) => setFilter("public", value)} options={choices(rows, "public", "Any public access")} />;
  }
  return (
    <FilterSelect
      label="Zone"
      value={filters.zone}
      onChange={(value) => setFilter("zone", value)}
      options={[{ value: "all", label: "Any zone" }, { value: "zonal", label: "Zonal" }, { value: "none", label: "No zone" }]}
    />
  );
}
