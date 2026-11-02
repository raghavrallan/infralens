"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { CostBars, SpendArea, SpendColumns } from "@/components/Charts";
import { DataTable, Panel } from "@/components/ui";
import { BILLING_PRESETS, billingChoices, billingCsv, billingWindow, buildChart, inclusiveEnd, prettyDay } from "@/lib/billing";
import { cash } from "@/lib/format";

const GROUPS = [
  ["total", "Total"],
  ["ServiceName", "Service"],
  ["ResourceGroupName", "Resource group"],
  ["subscription", "Subscription"],
];

function toggle(list, value) {
  return list.includes(value) ? list.filter((item) => item !== value) : [...list, value];
}

function FilterMenu({ label, options, selected, onToggle, onClear }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button type="button" className="rounded-md border border-line bg-white px-3 py-1.5 text-xs font-semibold text-ink" onClick={() => setOpen((value) => !value)}>
        {label}{selected.length ? ` · ${selected.length}` : ""}
      </button>
      {open ? (
        <div className="absolute z-20 mt-1 max-h-64 w-64 overflow-auto rounded-md border border-line bg-white p-2 shadow-lg">
          <button type="button" className="mb-1 text-xs font-semibold text-brand" onClick={onClear}>Clear</button>
          {options.map((option) => (
            <label key={option} className="flex cursor-pointer items-center gap-2 py-1 text-xs text-ink">
              <input type="checkbox" checked={selected.includes(option)} onChange={() => onToggle(option)} />
              <span className="truncate">{option}</span>
            </label>
          ))}
          {!options.length ? <p className="text-xs text-muted">No values in this range.</p> : null}
        </div>
      ) : null}
    </div>
  );
}

export function BillingBoard({ projectId, rangeId, saved }) {
  const start = BILLING_PRESETS.some((item) => item.id === rangeId) ? rangeId : "qtr";
  const opening = billingWindow(start) || billingWindow("qtr");
  const [preset, setPreset] = useState(start);
  const [from, setFrom] = useState(opening.from);
  const [to, setTo] = useState(opening.to);
  const [applied, setApplied] = useState(opening);
  const [groupBy, setGroupBy] = useState("ServiceName");
  const [grain, setGrain] = useState("day");
  const [chart, setChart] = useState("columns");
  const [services, setServices] = useState([]);
  const [groups, setGroups] = useState([]);
  const [subscriptions, setSubscriptions] = useState([]);
  const [rows, setRows] = useState(null);
  const [currency, setCurrency] = useState(saved?.currency || "USD");
  const [warnings, setWarnings] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [invoices, setInvoices] = useState([]);
  const [invoiceNote, setInvoiceNote] = useState("");
  const [invoiceBusy, setInvoiceBusy] = useState(false);
  const [downloading, setDownloading] = useState("");

  const headerRange = useRef(rangeId);
  useEffect(() => {
    if (headerRange.current === rangeId) return;
    headerRange.current = rangeId;
    const next = billingWindow(rangeId);
    if (!next) return;
    setPreset(rangeId);
    setFrom(next.from);
    setTo(next.to);
    setApplied(next);
    setServices([]);
    setGroups([]);
    setSubscriptions([]);
  }, [rangeId]);

  useEffect(() => {
    let live = true;
    setBusy(true);
    setError("");
    setRows(null);
    fetch("/api/costs/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ projectId, preset, from: applied.from, to: applied.to }),
    })
      .then(async (response) => {
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(body.message || "Azure did not return this cost range.");
        return body;
      })
      .then((body) => {
        if (!live) return;
        const limit = (preset === "custom" ? applied.to : inclusiveEnd(applied.to)).replaceAll("-", "");
        setRows((body.rows || []).filter((row) => !limit || row.date <= limit));
        setCurrency(body.currency || "USD");
        setWarnings(body.warnings || []);
      })
      .catch((err) => {
        if (live) setError(err.message);
      })
      .finally(() => {
        if (live) setBusy(false);
      });
    return () => {
      live = false;
    };
  }, [projectId, preset, applied.from, applied.to]);

  const [invoiceNonce, setInvoiceNonce] = useState(0);
  useEffect(() => {
    let live = true;
    setInvoiceBusy(true);
    fetch("/api/costs/invoices", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ projectId, fresh: invoiceNonce > 0 }),
    })
      .then(async (response) => {
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(body.message || "Azure did not return invoices.");
        return body;
      })
      .then((body) => {
        if (!live) return;
        setInvoices(body.invoices || []);
        setInvoiceNote(body.message || "");
      })
      .catch((err) => {
        if (live) setInvoiceNote(err.message);
      })
      .finally(() => {
        if (live) setInvoiceBusy(false);
      });
    return () => {
      live = false;
    };
  }, [projectId, invoiceNonce]);

  const choices = useMemo(() => billingChoices(rows || []), [rows]);
  const view = useMemo(
    () => buildChart(rows || [], { groupBy, services, groups, subscriptions, grain }),
    [rows, groupBy, services, groups, subscriptions, grain],
  );
  const shownEnd = preset === "custom" ? applied.to : inclusiveEnd(applied.to);
  const draftEnd = preset === "custom" ? to : inclusiveEnd(to);
  const span = `${prettyDay(applied.from)} – ${prettyDay(shownEnd)}`;
  const usingSaved = rows === null && preset === rangeId;
  const area = usingSaved ? (saved?.points || []) : view.points.map((point) => ({ label: point.label, spend: point.spend }));
  const bars = usingSaved ? (saved?.services || []) : view.breakdown;

  function pickPreset(id) {
    setPreset(id);
    setServices([]);
    setGroups([]);
    setSubscriptions([]);
    if (id === "custom") return;
    const next = billingWindow(id);
    if (!next) return;
    setFrom(next.from);
    setTo(next.to);
    setApplied(next);
  }

  function applyCustom() {
    if (!from || !to || from >= to) {
      setError("The end date has to be after the start date.");
      return;
    }
    setPreset("custom");
    setApplied({ from, to });
  }

  function downloadCsv() {
    const blob = new Blob([billingCsv(view.filtered)], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `cost-${applied.from}-${shownEnd}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  async function downloadInvoice(row) {
    setDownloading(row.id);
    try {
      const response = await fetch("/api/costs/invoices/file", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ projectId, name: row.name }),
      });
      const type = response.headers.get("content-type") || "";
      if (!response.ok || !type.includes("pdf")) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.message || "This invoice is not saved yet.");
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${row.file || row.name}.pdf`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setInvoiceNote(err.message);
    } finally {
      setDownloading("");
    }
  }

  return (
    <div className="space-y-4">
      <Panel
        title={`Spend · ${span}`}
        action={<span className="text-xs text-muted">{busy ? "Reading Azure…" : cash(usingSaved ? saved?.spend || 0 : view.total, currency)}</span>}
      >
        <div className="mb-3 flex flex-wrap items-center gap-2">
          {BILLING_PRESETS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`rounded-md px-3 py-1.5 text-xs font-semibold ${preset === item.id ? "bg-ink text-white" : "border border-line bg-white text-ink"}`}
              onClick={() => pickPreset(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
        <div className="mb-3 flex flex-wrap items-end gap-2">
          <label className="text-xs text-muted">
            From
            <input type="date" value={from} onChange={(event) => {
              setTo((current) => {
                const window = billingWindow(preset);
                return window && window.to === current ? inclusiveEnd(current) : current;
              });
              setPreset("custom");
              setFrom(event.target.value);
            }} className="mt-1 block rounded-md border border-line px-2 py-1 text-xs text-ink" />
          </label>
          <label className="text-xs text-muted">
            To
            <input type="date" value={draftEnd} onChange={(event) => {
              if (!event.target.value) return;
              setPreset("custom");
              setTo(event.target.value);
            }} className="mt-1 block rounded-md border border-line px-2 py-1 text-xs text-ink" />
          </label>
          <button type="button" className="rounded-md bg-brand px-3 py-1.5 text-xs font-semibold text-white" onClick={applyCustom}>Apply</button>
          <span className="text-xs text-muted">Dates apply when you press Apply. Filters stay on this result.</span>
        </div>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <FilterMenu label="Subscription" options={choices.subscriptions} selected={subscriptions} onToggle={(value) => setSubscriptions((list) => toggle(list, value))} onClear={() => setSubscriptions([])} />
          <FilterMenu label="Service" options={choices.services} selected={services} onToggle={(value) => setServices((list) => toggle(list, value))} onClear={() => setServices([])} />
          <FilterMenu label="Resource group" options={choices.groups} selected={groups} onToggle={(value) => setGroups((list) => toggle(list, value))} onClear={() => setGroups([])} />
          <label className="text-xs text-muted">
            Group by
            <select value={groupBy} onChange={(event) => setGroupBy(event.target.value)} className="ml-2 rounded-md border border-line bg-white px-2 py-1 text-xs text-ink">
              {GROUPS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
            </select>
          </label>
          <label className="text-xs text-muted">
            Grain
            <select value={grain} onChange={(event) => setGrain(event.target.value)} className="ml-2 rounded-md border border-line bg-white px-2 py-1 text-xs text-ink">
              <option value="day">Daily</option>
              <option value="month">Monthly</option>
            </select>
          </label>
          <button type="button" className={`rounded-md px-3 py-1.5 text-xs font-semibold ${chart === "area" ? "bg-ink text-white" : "border border-line bg-white"}`} onClick={() => setChart("area")}>Area</button>
          <button type="button" className={`rounded-md px-3 py-1.5 text-xs font-semibold ${chart === "columns" ? "bg-ink text-white" : "border border-line bg-white"}`} onClick={() => setChart("columns")}>Columns</button>
          <button type="button" className="rounded-md border border-line bg-white px-3 py-1.5 text-xs font-semibold" onClick={downloadCsv} disabled={!view.filtered.length}>Download CSV</button>
        </div>
        {error ? <p className="mb-2 text-sm text-danger">{error}</p> : null}
        {warnings.map((item) => <p key={item} className="mb-2 text-sm text-muted">{item}</p>)}
        {usingSaved && saved?.points?.length ? <p className="mb-2 text-xs text-muted">Showing the saved copy until Azure returns this range.</p> : null}
        {busy && !usingSaved && !view.points.length ? <p className="mb-2 text-sm text-muted">Reading this range from Azure…</p> : null}
        {!usingSaved && chart === "columns" && view.points.length ? <SpendColumns data={view.points} series={view.series} currency={currency} /> : null}
        {(usingSaved || chart === "area") && area.length ? <SpendArea data={area} /> : null}
        {!usingSaved && !view.points.length && !busy ? <p className="text-sm text-muted">No cost rows in this range.</p> : null}
      </Panel>
      <div className="grid gap-3 lg:grid-cols-2">
        <Panel title="By service"><CostBars data={bars} /></Panel>
        <Panel title="By resource group"><CostBars data={usingSaved ? (saved?.groups || []) : buildChart(rows || [], { groupBy: "ResourceGroupName", services, groups, subscriptions, grain }).breakdown} /></Panel>
      </div>
      <Panel title="Invoices" action={<button type="button" className="text-xs font-semibold text-brand" onClick={() => setInvoiceNonce((value) => value + 1)}>{invoiceBusy ? "Syncing…" : "Sync invoices"}</button>}>
        {invoiceNote ? <p className="mb-2 text-sm text-muted">{invoiceNote}</p> : null}
        {invoices.length ? (
          <DataTable
            rows={invoices}
            searchKeys={["name", "subscription", "status"]}
            placeholder="Search invoices"
            columns={[
              { key: "name", label: "Invoice" },
              { key: "subscription", label: "Subscription" },
              { key: "start", label: "Start", render: (row) => prettyDay(String(row.start || "").slice(0, 10)) || "—" },
              { key: "end", label: "End", render: (row) => prettyDay(String(row.end || "").slice(0, 10)) || "—" },
              { key: "status", label: "Status" },
              { key: "amount", label: "Amount", render: (row) => cash(row.amount, row.currency) },
              { key: "download", label: "PDF", render: (row) => (
                row.saved ? (
                  <button type="button" className="text-xs font-semibold text-brand" disabled={downloading === row.id} onClick={() => downloadInvoice(row)}>
                    {downloading === row.id ? "Saving…" : "Download"}
                  </button>
                ) : (
                  <span className="text-xs text-muted">Not saved</span>
                )
              ) },
            ]}
          />
        ) : (
          <p className="text-sm text-muted">{invoiceBusy ? "Checking the project folder…" : "No invoices are saved for this project yet."}</p>
        )}
      </Panel>
    </div>
  );
}
