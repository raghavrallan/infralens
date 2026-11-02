"use client";

import { useEffect, useRef, useState } from "react";
import { LineBars, RankBars } from "@/components/Charts";
import { DataTable, Panel, Pill, stateTone } from "@/components/ui";
import { useConsole } from "@/context/ConsoleContext";
import { kqlColumns, kqlExamples, kqlFor, LIVE_METRICS, logKql, METRIC_WINDOWS, signalValue } from "@/lib/compute";
import { kqlColumns as dataKqlColumns, kqlExamples as dataKqlExamples, kqlFor as dataKqlFor, LIVE_METRICS as DATA_METRICS } from "@/lib/data";
import { kqlColumns as networkKqlColumns, kqlExamples as networkKqlExamples, kqlFor as networkKqlFor, LIVE_METRICS as NETWORK_METRICS } from "@/lib/network";
import { kqlColumns as platformKqlColumns, kqlExamples as platformKqlExamples, kqlFor as platformKqlFor, LIVE_METRICS as PLATFORM_METRICS } from "@/lib/platform";
import { serviceById } from "@/lib/services";

function forResource(payload, name, group) {
  const subject = payload?.subject;
  if (!subject) return true;
  return String(subject.name || "").toLowerCase() === String(name || "").toLowerCase() && String(subject.group || "") === String(group || "");
}

function liveMetrics(serviceId) {
  return LIVE_METRICS[serviceId] || DATA_METRICS[serviceId] || NETWORK_METRICS[serviceId] || PLATFORM_METRICS[serviceId] || [];
}

function queryFor(serviceId, clause) {
  return kqlFor(serviceId, clause) || dataKqlFor(serviceId, clause) || networkKqlFor(serviceId, clause) || platformKqlFor(serviceId, clause);
}

function columnsFor(serviceId) {
  return kqlColumns(serviceId).length ? kqlColumns(serviceId) : dataKqlColumns(serviceId).length ? dataKqlColumns(serviceId) : networkKqlColumns(serviceId).length ? networkKqlColumns(serviceId) : platformKqlColumns(serviceId);
}

function examplesFor(serviceId) {
  return kqlExamples(serviceId).length ? kqlExamples(serviceId) : dataKqlExamples(serviceId).length ? dataKqlExamples(serviceId) : networkKqlExamples(serviceId).length ? networkKqlExamples(serviceId) : platformKqlExamples(serviceId);
}

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

async function inspect(body) {
  const response = await fetch("/api/compute/inspect", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.message || "Azure did not return that read.");
  return payload;
}

export function MetricsBoard({ serviceId, rows, region, regions, onRegion }) {
  const { model, projectId, rangeId } = useConsole();
  const choices = liveMetrics(serviceId);
  const [metric, setMetric] = useState(choices[0]?.name || "");
  const [windowId, setWindowId] = useState("1h");
  const [live, setLive] = useState(false);
  const [clause, setClause] = useState("");
  const [reading, setReading] = useState(false);
  const [error, setError] = useState("");
  const [liveRows, setLiveRows] = useState(null);
  const [debug, setDebug] = useState(null);
  const [kqlRows, setKqlRows] = useState(null);
  const [kqlError, setKqlError] = useState("");
  const [kqlBusy, setKqlBusy] = useState(false);
  const choice = choices.find((item) => item.name === metric) || choices[0];
  const saved = !liveRows && choice?.name === choices[0]?.name;
  const shown = (liveRows || (saved ? rows.filter((row) => row.signal && Number.isFinite(Number(row.signal.value))).map((row) => ({
    id: row.id,
    name: row.name,
    value: Number(row.signal.value),
    series: [],
  })) : [])).filter((row) => region === "all" || rows.find((item) => item.id === row.id)?.location === region);

  const metricTicket = useRef(0);
  async function readMetrics(fresh = false) {
    if (!choice) return;
    const mine = ++metricTicket.current;
    const metricName = choice.name;
    const requestedWindow = windowId;
    const requestedIds = rows.filter((row) => region === "all" || row.location === region).map((row) => row.id);
    setReading(true);
    setError("");
    try {
      const payload = await inspect({
        action: "metrics",
        projectId,
        rangeId,
        serviceId,
        metric: metricName,
        window: requestedWindow,
        resourceIds: requestedIds,
        fresh,
      });
      if (metricTicket.current !== mine || (payload.metric && payload.metric !== metricName)) return;
      setLiveRows(payload.rows || []);
      setDebug(payload);
      if (payload.message) setError(payload.message);
    } catch (err) {
      if (metricTicket.current === mine) setError(err.message);
    } finally {
      if (metricTicket.current === mine) setReading(false);
    }
  }

  const metricKey = rows.filter((row) => region === "all" || row.location === region).map((row) => row.id).sort().join(",");
  useEffect(() => {
    if (!choice || !metricKey) return undefined;
    let cancelled = false;
    async function warm() {
      try {
        const payload = await inspect({
          action: "metrics",
          cacheOnly: true,
          projectId,
          rangeId,
          serviceId,
          metric: choice.name,
          window: windowId,
          resourceIds: metricKey.split(","),
        });
        if (cancelled || payload.cacheMiss || (payload.metric && payload.metric !== choice.name)) return;
        setLiveRows(payload.rows || []);
        setDebug(payload);
      } catch {
        // The chart keeps the saved signal until the user asks.
      }
    }
    warm();
    return () => {
      cancelled = true;
    };
  }, [choice, metricKey, projectId, rangeId, serviceId, windowId]);

  const readRef = useRef(readMetrics);
  readRef.current = readMetrics;
  useEffect(() => {
    if (!live) return undefined;
    const timer = setInterval(() => { readRef.current(true); }, 20000);
    return () => clearInterval(timer);
  }, [live]);

  const [kqlSaved, setKqlSaved] = useState(null);
  const kqlTicket = useRef(0);
  async function runKql(fresh = false) {
    const mine = ++kqlTicket.current;
    const requested = clause;
    setKqlBusy(true);
    setKqlError("");
    try {
      const payload = await inspect({ action: "kql", projectId, rangeId, serviceId, clause: requested, fresh });
      if (kqlTicket.current !== mine) return;
      setKqlRows(payload.rows || []);
      setKqlSaved(payload.cachedAt || null);
    } catch (err) {
      if (kqlTicket.current === mine) setKqlError(err.message);
    } finally {
      if (kqlTicket.current === mine) setKqlBusy(false);
    }
  }

  const bars = [...shown].sort((a, b) => b.value - a.value).map((row) => ({ name: row.name, value: row.value, color: "#E2773C" }));
  const focus = shown[0];
  const trend = (focus?.series || []).map((point) => ({
    time: new Date(point.time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    value: point.value,
  }));

  return (
    <div className="space-y-4">
      {choices.length === 0 ? (
        <Panel title="Metrics">
          <p className="text-sm text-muted">Azure does not publish a platform metric on this resource. The query below still reads this service.</p>
        </Panel>
      ) : (
      <Panel title={choice?.label || "Metrics"} action={<span className="text-xs text-muted">{choice?.name}</span>}>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <FilterSelect label="Metric" value={metric} onChange={(value) => { metricTicket.current += 1; setMetric(value); setLiveRows(null); setReading(false); }} options={choices.map((item) => ({ value: item.name, label: item.label }))} />
          <FilterSelect label="Window" value={windowId} onChange={(value) => { metricTicket.current += 1; setWindowId(value); setLiveRows(null); setReading(false); }} options={METRIC_WINDOWS.map(([value, label]) => ({ value, label }))} />
          <FilterSelect label="Region" value={region} onChange={onRegion} options={regions} />
          <button type="button" onClick={() => readMetrics(Boolean(liveRows))} disabled={reading} className="h-9 rounded-xl bg-brand px-3 text-sm font-semibold text-white disabled:opacity-50">
            {reading ? "Reading…" : liveRows ? "Refresh" : "Read live"}
          </button>
          <label className="inline-flex items-center gap-1.5 text-xs font-semibold text-muted">
            <input type="checkbox" checked={live} onChange={(event) => setLive(event.target.checked)} />
            Keep live
          </label>
        </div>
        <p className="mb-3 text-xs text-muted">
          {choice?.aggregation} · {METRIC_WINDOWS.find(([id]) => id === windowId)?.[1]} · {shown.length} samples
          {debug?.missing?.length ? ` · no sample for ${debug.missing.slice(0, 3).join(", ")}` : ""}
          {debug?.cachedAt ? ` · kept for an hour, saved ${new Date(debug.cachedAt).toLocaleTimeString()}` : ""}
          {saved ? " · showing the saved hour until you read live" : ""}
        </p>
        {error && <p className="mb-3 text-sm text-warn">{error}</p>}
        {bars.length === 0 ? <p className="py-8 text-center text-sm text-muted">No samples for this metric yet. Read live to ask Azure.</p> : (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <RankBars data={bars} format={(value) => signalValue(value, choice?.unit) || "0"} />
            <div>
              <p className="mb-2 text-xs font-semibold text-muted">{focus?.name} over this window</p>
              {trend.length > 1 ? <LineBars data={trend} xKey="time" yKey="value" color="#E2773C" /> : <p className="text-sm text-muted">Live points show here after a read. The saved copy only keeps the latest value.</p>}
            </div>
          </div>
        )}
        <ul className="mt-3 space-y-1 border-t border-line pt-3">
          {bars.slice(0, 8).map((row) => (
            <li key={row.name} className="flex justify-between gap-3 text-xs">
              <span className="truncate font-medium">{row.name}</span>
              <span className="tabular-nums text-muted">{signalValue(row.value, choice?.unit)}</span>
            </li>
          ))}
        </ul>
      </Panel>
      )}
      <Panel title="KQL" action={<span className="text-xs text-muted">Resource Graph · {serviceById(serviceId)?.label || "this service"}</span>}>
        <p className="mb-2 text-sm text-muted">This query is built for {serviceById(serviceId)?.label || "this service"}. Pick a filter, or add one | where line.</p>
        <div className="mb-2 flex flex-wrap gap-2">
          {examplesFor(serviceId).map((item) => (
            <button key={item.label} type="button" onClick={() => { kqlTicket.current += 1; setKqlBusy(false); setKqlRows(null); setKqlSaved(null); setClause(clause === item.clause ? "" : item.clause); }} className={`h-8 rounded-full px-3 text-xs font-semibold ${clause === item.clause ? "bg-ink text-white" : "bg-canvas text-ink"}`}>
              {item.label}
            </button>
          ))}
        </div>
        <textarea
          value={clause}
          onChange={(event) => { kqlTicket.current += 1; setClause(event.target.value); }}
          placeholder={examplesFor(serviceId)[0]?.clause || "| where location == 'eastus'"}
          className="h-16 w-full rounded-xl border border-line px-3 py-2 font-mono text-xs outline-none focus:border-brand"
        />
        <pre className="mt-2 overflow-x-auto rounded-xl bg-canvas p-3 text-xs leading-5 text-ink">{queryFor(serviceId, clause)}</pre>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => navigator.clipboard?.writeText(queryFor(serviceId, clause))} className="h-9 rounded-xl border border-line px-3 text-sm font-semibold">Copy</button>
          <button type="button" onClick={() => runKql(Boolean(kqlRows))} disabled={kqlBusy} className="h-9 rounded-xl bg-ink px-3 text-sm font-semibold text-white disabled:opacity-50">{kqlBusy ? "Running…" : kqlRows ? "Refresh query" : "Run query"}</button>
          {kqlSaved && <span className="text-xs text-muted">Kept for an hour</span>}
          {kqlError && <span className="text-xs text-warn">{kqlError}</span>}
        </div>
        {kqlRows && (
          <div className="mt-3">
            <DataTable
              rows={kqlRows.map((row, index) => ({ ...row, id: `${row.name}-${index}` }))}
              searchKeys={columnsFor(serviceId).map((column) => column.key)}
              columns={columnsFor(serviceId)}
            />
          </div>
        )}
      </Panel>
    </div>
  );
}

export function RevisionsBoard({ rows }) {
  const { projectId, rangeId } = useConsole();
  const [selected, setSelected] = useState(rows[0] || null);
  const [revisions, setRevisions] = useState([]);
  const [lines, setLines] = useState([]);
  const [kind, setKind] = useState("console");
  const [live, setLive] = useState(false);
  const [revisionBusy, setRevisionBusy] = useState(false);
  const [logBusy, setLogBusy] = useState(false);
  const [revisionError, setRevisionError] = useState("");
  const [logError, setLogError] = useState("");
  const current = rows.find((row) => row.id === selected?.id) || rows[0] || null;

  const [revisionSaved, setRevisionSaved] = useState(null);
  const revisionTicket = useRef(0);
  async function loadRevisions(fresh = false) {
    if (!current) return;
    const mine = ++revisionTicket.current;
    const name = current.name;
    const group = current.group;
    setRevisionBusy(true);
    setRevisionError("");
    try {
      const payload = await inspect({
        action: "revisions",
        projectId,
        rangeId,
        serviceId: "container-apps",
        name,
        group,
        fresh,
      });
      if (revisionTicket.current !== mine || !forResource(payload, name, group)) return;
      setRevisions(payload.rows || []);
      setRevisionSaved(payload.cachedAt || null);
    } catch (err) {
      if (revisionTicket.current === mine) setRevisionError(err.message);
    } finally {
      if (revisionTicket.current === mine) setRevisionBusy(false);
    }
  }

  useEffect(() => {
    if (!current) return undefined;
    let cancelled = false;
    async function warm() {
      try {
        const payload = await inspect({
          action: "revisions",
          cacheOnly: true,
          projectId,
          rangeId,
          serviceId: "container-apps",
          name: current.name,
          group: current.group,
        });
        if (cancelled || payload.cacheMiss || !forResource(payload, current.name, current.group)) return;
        setRevisions(payload.rows || []);
        setRevisionSaved(payload.cachedAt || null);
      } catch {
        // Revisions stay blank until the user asks.
      }
    }
    warm();
    return () => {
      cancelled = true;
    };
  }, [current?.id, projectId, rangeId]);

  async function loadLogs(quiet) {
    if (!current) return;
    const mine = revisionTicket.current;
    const name = current.name;
    const group = current.group;
    const requestedKind = kind;
    if (!quiet) setLogBusy(true);
    setLogError("");
    try {
      const payload = await inspect({
        action: "logs",
        projectId,
        rangeId,
        serviceId: "container-apps",
        name,
        group,
        kind: requestedKind,
      });
      if (revisionTicket.current !== mine) return;
      setLines(payload.lines || []);
    } catch (err) {
      if (revisionTicket.current !== mine) return;
      setLogError(err.message);
      setLive(false);
    } finally {
      if (!quiet && revisionTicket.current === mine) setLogBusy(false);
    }
  }

  const logsRef = useRef(loadLogs);
  logsRef.current = loadLogs;
  useEffect(() => {
    if (!live || !current) return undefined;
    const timer = setInterval(() => { logsRef.current(true); }, 10000);
    return () => clearInterval(timer);
  }, [live, current]);

  if (!current) return <Panel><p className="py-8 text-center text-sm text-muted">No container apps in this project.</p></Panel>;

  return (
    <div className="space-y-4">
      <Panel title="Revisions and artifacts">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <FilterSelect label="App" value={current.id} onChange={(value) => { revisionTicket.current += 1; setSelected(rows.find((row) => row.id === value) || null); setRevisions([]); setLines([]); setRevisionSaved(null); setRevisionError(""); setRevisionBusy(false); }} options={rows.map((row) => ({ value: row.id, label: row.name }))} />
          <button type="button" onClick={() => loadRevisions(Boolean(revisionSaved))} disabled={revisionBusy} className="h-9 rounded-xl bg-brand px-3 text-sm font-semibold text-white disabled:opacity-50">{revisionBusy ? "Reading…" : revisionSaved ? "Refresh" : "Load revisions"}</button>
          {revisionSaved && <span className="text-xs text-muted">Kept for an hour</span>}
        </div>
        <dl className="mb-3 grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
          <div><dt className="text-[11px] font-semibold uppercase tracking-wide text-muted">Latest revision</dt><dd className="mt-0.5 break-all">{current.revision || "—"}</dd></div>
          <div><dt className="text-[11px] font-semibold uppercase tracking-wide text-muted">Mode</dt><dd className="mt-0.5">{current.revisionMode || "—"}</dd></div>
          <div><dt className="text-[11px] font-semibold uppercase tracking-wide text-muted">Artifact</dt><dd className="mt-0.5 break-all">{current.image || "Load revisions to see the image"}</dd></div>
          <div><dt className="text-[11px] font-semibold uppercase tracking-wide text-muted">Replicas</dt><dd className="mt-0.5">{current.replicas || "—"} · {current.ingress || "ingress off"}</dd></div>
        </dl>
        {revisionError && <p className="mb-3 text-sm text-warn">{revisionError}</p>}
        {revisions.length > 0 && (
          <DataTable
            rows={revisions.map((row, index) => ({ ...row, id: `${row.name}-${index}`, activeLabel: row.active ? "Active" : "Inactive" }))}
            searchKeys={["name", "image", "running", "health"]}
            columns={[
              { key: "name", label: "Revision" },
              { key: "activeLabel", label: "Active", render: (row) => <Pill tone={row.active ? "ok" : "muted"}>{row.activeLabel}</Pill> },
              { key: "running", label: "Running" },
              { key: "health", label: "Health" },
              { key: "replicas", label: "Replicas" },
              { key: "traffic", label: "Traffic %" },
              { key: "image", label: "Artifact" },
            ]}
          />
        )}
      </Panel>
      <Panel title="Logs">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <FilterSelect label="Stream" value={kind} onChange={setKind} options={[{ value: "console", label: "Console" }, { value: "system", label: "System" }]} />
          <button type="button" onClick={() => loadLogs(false)} disabled={logBusy} className="h-9 rounded-xl bg-brand px-3 text-sm font-semibold text-white disabled:opacity-50">{logBusy ? "Reading…" : "Tail logs"}</button>
          <label className="inline-flex items-center gap-1.5 text-xs font-semibold text-muted">
            <input type="checkbox" checked={live} onChange={(event) => setLive(event.target.checked)} />
            Live tail
          </label>
        </div>
        <pre className="mb-3 overflow-x-auto rounded-xl bg-canvas p-3 text-xs leading-5">{logKql(current.name, kind)}</pre>
        {logError && <p className="mb-3 text-sm text-warn">{logError}</p>}
        {lines.length === 0 ? <p className="text-sm text-muted">Tail reads the last two days from this environment&apos;s Log Analytics workspace. Direct log streaming is not used.</p> : (
          <pre className="max-h-80 overflow-auto rounded-xl bg-ink p-3 text-xs leading-5 text-white">{lines.join("\n")}</pre>
        )}
      </Panel>
    </div>
  );
}
