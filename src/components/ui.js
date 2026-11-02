"use client";

import { useEffect, useMemo, useState } from "react";

export function useTitle(title) {
  useEffect(() => {
    document.title = `${title} · Infralens`;
  }, [title]);
}

export function PageHead({ eyebrow, title, description, action }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div>
        {eyebrow && (
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-brand">
            {eyebrow}
          </div>
        )}
        <h1 className="mt-1 text-[28px] font-semibold leading-none tracking-tight text-ink">
          {title}
        </h1>
        {description && (
          <p className="mt-2 max-w-2xl text-sm text-muted">{description}</p>
        )}
      </div>
      {action}
    </div>
  );
}

const BARS = {
  brand: "bg-brand",
  ok: "bg-ok",
  info: "bg-info",
  warn: "bg-warn",
  danger: "bg-danger",
};

export function Kpi({ label, value, hint, tone = "brand" }) {
  return (
    <div className="relative overflow-hidden rounded-2xl border border-line bg-white px-4 py-3.5">
      <span className={`absolute bottom-3 left-0 top-3 w-1 rounded-r ${BARS[tone] || BARS.brand}`} />
      <div className="pl-2">
        <div className="text-[11px] font-semibold uppercase tracking-wide text-muted">
          {label}
        </div>
        <div className="mt-1.5 text-[26px] font-semibold leading-none tabular-nums text-ink">
          {value}
        </div>
        {hint && <div className="mt-2 text-xs text-muted">{hint}</div>}
      </div>
    </div>
  );
}

export function Panel({ title, action, children, className = "" }) {
  return (
    <section className={`min-w-0 rounded-2xl border border-line bg-white p-4 ${className}`}>
      {(title || action) && (
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-ink">{title}</h2>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

const PILL = {
  ok: "bg-emerald-50 text-ok",
  warn: "bg-amber-50 text-warn",
  danger: "bg-red-50 text-danger",
  info: "bg-sky-50 text-info",
  muted: "bg-stone-100 text-muted",
  brand: "bg-orange-50 text-brand-deep",
};

export function Pill({ tone = "ok", children }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-semibold ${PILL[tone] || PILL.muted}`}>
      {children}
    </span>
  );
}

export function Dot({ tone = "ok" }) {
  const color = {
    ok: "bg-ok",
    warn: "bg-warn",
    danger: "bg-danger",
    info: "bg-info",
    muted: "bg-stone-300",
  }[tone];
  return <span className={`inline-block h-2 w-2 rounded-full ${color}`} />;
}

export function stateTone(state) {
  const value = String(state || "").toLowerCase();
  if (/fail|degrad|unavailable|critical/.test(value)) return "danger";
  if (/stop|deallocat|scale to 0|disabled|paused|idle/.test(value)) return "muted";
  if (/provisioning|updating|starting|activating|scaling|attention|syncing/.test(value)) return "warn";
  if (/running|succeeded|ready|available|healthy|provisioned|active/.test(value)) return "ok";
  return "info";
}

export function DataTable({
  rows,
  columns,
  searchKeys = [],
  placeholder = "Filter by keyword",
  toolbar = null,
  onRow,
  hideMeta = false,
  pageSize = 25,
}) {
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const keys = searchKeys.join("|");
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((row) =>
      keys.split("|").filter(Boolean).some((key) => String(row[key] ?? "").toLowerCase().includes(q))
    );
  }, [rows, query, keys]);
  const signature = `${query}:${rows.length}:${rows[0]?.id || ""}:${rows.at?.(-1)?.id || ""}`;
  const [seen, setSeen] = useState(signature);
  if (seen !== signature) {
    setSeen(signature);
    setPage(1);
  }
  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const safePage = Math.min(page, pageCount);
  const start = (safePage - 1) * pageSize;
  const visible = filtered.slice(start, start + pageSize);
  const from = filtered.length ? start + 1 : 0;
  const to = Math.min(start + pageSize, filtered.length);

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={placeholder}
            className="h-9 w-52 rounded-xl border border-line bg-white px-3 text-sm outline-none focus:border-brand"
          />
          {toolbar}
        </div>
        {!hideMeta && (
          <div className="ml-auto text-xs text-muted">
            Showing {from}–{to} of {filtered.length}
          </div>
        )}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] border-collapse text-left text-sm">
          <thead>
            <tr className="border-b border-line text-[11px] uppercase tracking-wide text-muted">
              {columns.map((col) => (
                <th key={col.key} className={`px-3 py-2 font-semibold ${col.align === "right" ? "text-right" : ""}`}>
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 && (
              <tr>
                <td colSpan={columns.length} className="px-3 py-8 text-center text-muted">
                  Nothing matches that filter.
                </td>
              </tr>
            )}
            {visible.map((row, index) => (
              <tr
                key={row.id || row.name || index}
                onClick={onRow ? () => onRow(row) : undefined}
                className={`border-b border-line/80 last:border-0 hover:bg-canvas ${onRow ? "cursor-pointer" : ""}`}
              >
                {columns.map((col) => (
                  <td
                    key={col.key}
                    className={`px-3 py-2.5 align-middle text-ink ${col.align === "right" ? "text-right tabular-nums" : ""} ${col.className || ""}`}
                  >
                    {col.render ? col.render(row) : row[col.key]}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex items-center justify-between gap-3">
        <span className="text-xs text-muted">Page {safePage} of {pageCount}</span>
        <div className="flex gap-2">
          <button type="button" className="rounded-xl border border-line px-3 py-1.5 text-xs font-semibold disabled:opacity-40" disabled={safePage <= 1} onClick={() => setPage(safePage - 1)}>
            Previous
          </button>
          <button type="button" className="rounded-xl border border-line px-3 py-1.5 text-xs font-semibold disabled:opacity-40" disabled={safePage >= pageCount} onClick={() => setPage(safePage + 1)}>
            Next
          </button>
        </div>
      </div>
    </div>
  );
}

export function Drawer({ open, title, subtitle, onClose, children }) {
  useEffect(() => {
    if (!open) return undefined;
    function onKey(e) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-ink/30" onClick={onClose}>
      <aside
        className="h-full w-full max-w-md overflow-y-auto bg-white p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-lg font-semibold">{title}</h3>
            {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
          </div>
          <button type="button" onClick={onClose} className="rounded-xl px-2 py-1 text-sm text-muted hover:bg-canvas">
            Close
          </button>
        </div>
        <div className="mt-4">{children}</div>
      </aside>
    </div>
  );
}

export function RunDots({ runs }) {
  return (
    <div className="flex items-center gap-1">
      {runs.map((run, i) => (
        <span
          key={`${run}-${i}`}
          title={run === "ok" ? "Succeeded" : run === "fail" ? "Failed" : "No run"}
          className={`h-2.5 w-2.5 rounded-full ${
            run === "ok" ? "bg-ok" : run === "fail" ? "bg-danger" : "bg-stone-200"
          }`}
        />
      ))}
    </div>
  );
}

export function Tags({ tags }) {
  return (
    <div className="flex flex-wrap gap-1">
      {tags.map((tag) => (
        <span key={tag} className="rounded-md bg-canvas px-1.5 py-0.5 text-[11px] font-medium text-muted">
          {tag}
        </span>
      ))}
    </div>
  );
}
