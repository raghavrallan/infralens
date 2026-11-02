"use client";

import Link from "next/link";
import { CostBars, DonutLegend, RankBars, SpendArea, SplitDonut, UsageLines } from "@/components/Charts";
import { Kpi, PageHead, Panel } from "@/components/ui";
import { useConsole } from "@/context/ConsoleContext";
import { ago, cash, num } from "@/lib/format";
import { prettyDay } from "@/lib/billing";
import { rangeById, rangeWindow } from "@/lib/ranges";
import { computeHref } from "@/lib/compute";
import { dataHref } from "@/lib/data";
import { networkHref } from "@/lib/network";
import { platformHref } from "@/lib/platform";
import { SERVICE_GROUPS, SERVICES } from "@/lib/services";

const AREA_COLORS = { compute: "#E2773C", data: "#0084FF", network: "#0BAA60", platform: "#7C6AE8" };
const SERVICE_COLORS = ["#E2773C", "#C45E28", "#0084FF", "#0BAA60", "#7C6AE8", "#0E7490", "#D4537E", "#717171"];
const SEVERITY = [
  ["0", "Sev 0", "#D4537E"],
  ["1", "Sev 1", "#E2773C"],
  ["2", "Sev 2", "#F2A365"],
  ["3", "Sev 3", "#0084FF"],
  ["4", "Sev 4", "#717171"],
];
const IMPACTS = [
  ["High", "#D4537E"],
  ["Medium", "#E2773C"],
  ["Low", "#0BAA60"],
];

function spendTitle(trend) {
  if (trend.from && trend.end) return `${trend.title} · ${prettyDay(trend.from)} – ${prettyDay(trend.end)}`;
  const first = trend.points[0]?.label;
  const last = trend.points.at(-1)?.label;
  if (first && last && first !== last) return `${trend.title} · ${first} – ${last}`;
  return trend.title;
}

function serviceHref(id) {
  return computeHref(id) || dataHref(id) || networkHref(id) || platformHref(id) || `/resources?service=${id}`;
}

function ChartCard({ title, href, link, children }) {
  return (
    <Panel title={title} action={href ? <Link href={href} className="shrink-0 text-xs font-semibold text-brand">{link}</Link> : null} className="flex h-full flex-col">
      <div className="h-60">{children}</div>
    </Panel>
  );
}

function Mix({ data }) {
  return (
    <div className="grid h-full items-center gap-3 sm:grid-cols-[9.5rem_1fr]">
      <SplitDonut data={data} valueKey="count" format={num} />
      <DonutLegend data={data} valueKey="count" limit={4} />
    </div>
  );
}

export default function DashboardPage() {
  const { model: loaded, rangeId, projectId } = useConsole();
  const range = rangeById(rangeId);
  const view = loaded?.range?.id === range.id && loaded?.project?.id === projectId ? loaded : null;
  if (!loaded || loaded.status === "setup") return null;
  if (!view) {
    return (
      <PageHead
        eyebrow={loaded.project?.name}
        title="Estate overview"
        description={`Loading ${range.label} for this project.`}
      />
    );
  }
  const model = view;
  const currency = model.kpis?.currency || "USD";
  const budget = Number(model.project?.budget);
  const forecast = model.kpis?.forecast;
  const delta = Number.isFinite(budget) && forecast != null ? forecast - budget : null;
  const counts = new Map();
  const regions = new Map();
  for (const resource of model.resources || []) {
    counts.set(resource.service, (counts.get(resource.service) || 0) + 1);
    const place = resource.location || "Unknown";
    regions.set(place, (regions.get(place) || 0) + 1);
  }
  const byService = [...counts.entries()]
    .map(([id, value]) => {
      const service = SERVICES.find((item) => item.id === id);
      return { name: service?.label || id, value, href: serviceHref(id), color: SERVICE_COLORS[0] };
    })
    .sort((a, b) => b.value - a.value)
    .slice(0, 8)
    .map((item, index) => ({ ...item, color: SERVICE_COLORS[index % SERVICE_COLORS.length] }));
  const byArea = SERVICE_GROUPS.map((group) => ({
    name: group.label,
    count: SERVICES.filter((service) => service.group === group.id).reduce((sum, service) => sum + (counts.get(service.id) || 0), 0),
    color: AREA_COLORS[group.id],
  })).filter((item) => item.count > 0);
  const byRegion = [...regions.entries()]
    .map(([name, value], index) => ({ name, value, color: SERVICE_COLORS[index % SERVICE_COLORS.length] }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 6);
  const bySeverity = SEVERITY.map(([key, name, color]) => ({
    name,
    count: (model.alerts || []).filter((item) => String(item.severity) === key).length,
    color,
  })).filter((item) => item.count > 0);
  const byImpact = IMPACTS.map(([name, color]) => ({
    name,
    count: (model.advisor || []).filter((item) => item.impact === name).length,
    color,
  })).filter((item) => item.count > 0);
  const topServices = (model.services || []).slice(0, 6);
  const window = rangeWindow(model.range.id);
  const from = Date.parse(`${window.from}T00:00:00Z`);
  const to = Date.parse(`${window.to}T00:00:00Z`);
  const activity = (model.activity || [])
    .filter((item) => {
      const time = Date.parse(item.time);
      return Number.isFinite(time) && time >= from && time < to;
    })
    .slice(0, 6);
  const spendHint = !model.canSeeCost
    ? "Billing is hidden for this role"
    : delta == null
      ? "Actual cost for this range"
      : delta > 0
        ? `Forecast is over budget by ${cash(delta, currency)}`
        : `Forecast is under budget by ${cash(Math.abs(delta), currency)}`;

  return (
    <div className="space-y-4">
      <PageHead
        eyebrow={model.project?.name}
        title="Estate overview"
        description={`${model.range.label}. ${num(model.kpis.resourceCount)} resources across ${SERVICES.length} tracked services.`}
      />
      {!!model.warnings?.length && (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-warn">{model.warnings[0]}</div>
      )}
      <div className={`grid gap-3 sm:grid-cols-2 ${model.canSeeCost ? "xl:grid-cols-4" : "xl:grid-cols-3"}`}>
        <Link href="/resources" className="block">
          <Kpi label="Resources" value={num(model.kpis.resourceCount)} hint={`${num(model.subscriptions.length)} subscriptions · ${num(model.kpis.groupCount)} groups`} tone="info" />
        </Link>
        {model.canSeeCost && (
          <Link href="/costs" className="block">
            <Kpi label={model.range.spendLabel} value={cash(model.kpis.spend, currency)} hint={spendHint} tone={delta > 0 ? "danger" : "brand"} />
          </Link>
        )}
        <Link href="/alerts" className="block">
          <Kpi label="Alerts" value={num(model.alerts.length)} hint="Metric alert rules" tone="ok" />
        </Link>
        <Link href="/insights" className="block">
          <Kpi label="Advisor" value={num(model.advisor.length)} hint={(model.advisor[0]?.problem || "Recommendations in scope").slice(0, 72)} tone="warn" />
        </Link>
      </div>

      <Panel title="This project" action={<Link href="/resources" className="text-xs font-semibold text-brand">All services</Link>}>
        <div className="mb-3 flex flex-wrap gap-1">
          {SERVICE_GROUPS.map((group) => {
            const total = SERVICES.filter((service) => service.group === group.id).reduce((sum, service) => sum + (counts.get(service.id) || 0), 0);
            return (
              <Link key={group.id} href={group.id === "compute" ? "/compute" : group.id === "data" ? "/data" : group.id === "network" ? "/network" : group.id === "platform" ? "/platform" : `/resources?group=${group.id}`} className="rounded-xl bg-canvas px-3 py-1.5 text-xs font-semibold text-ink hover:text-brand">
                {group.label}
                <span className="ml-1.5 tabular-nums text-muted">{num(total)}</span>
              </Link>
            );
          })}
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
          {SERVICES.map((service) => (
            <Link key={service.id} href={serviceHref(service.id)} className="rounded-xl border border-line px-3 py-2 hover:border-brand">
              <div className="truncate text-xs text-muted">{service.label}</div>
              <div className="mt-1 text-lg font-semibold tabular-nums leading-none">{num(counts.get(service.id) || 0)}</div>
            </Link>
          ))}
        </div>
      </Panel>

      <div key={`${model.project.id}:${model.range.id}`} className="grid grid-cols-1 items-stretch gap-4 md:grid-cols-2 xl:grid-cols-3">
        {byService.length > 0 && (
          <ChartCard title="Resources by service" href="/resources" link="All services">
            <RankBars data={byService} fill />
          </ChartCard>
        )}
        {byRegion.length > 0 && (
          <ChartCard title="Regions" href="/resources" link="Resources">
            <RankBars data={byRegion} fill />
          </ChartCard>
        )}
        {byArea.length > 0 && (
          <ChartCard title="Estate mix">
            <Mix data={byArea} />
          </ChartCard>
        )}
        {bySeverity.length > 0 && (
          <ChartCard title="Alerts by severity" href="/alerts" link="Alerts">
            <Mix data={bySeverity} />
          </ChartCard>
        )}
        {byImpact.length > 0 && (
          <ChartCard title="Advisor by impact" href="/insights" link="Advisor">
            <Mix data={byImpact} />
          </ChartCard>
        )}
        {model.canSeeCost && model.trend.points.length > 0 && (
          <ChartCard title={spendTitle(model.trend)} href="/costs" link={currency}>
            <SpendArea data={model.trend.points} xKey="label" className="h-full" />
          </ChartCard>
        )}
        {model.canSeeCost && model.services.length > 0 && (
          <ChartCard title="Spend split" href="/costs" link="Billing">
            <div className="grid h-full items-center gap-3 sm:grid-cols-[9.5rem_1fr]">
              <SplitDonut data={model.services} />
              <DonutLegend data={model.services} limit={4} />
            </div>
          </ChartCard>
        )}
        {model.canSeeCost && topServices.length > 0 && (
          <ChartCard title="Top services" href="/costs" link="Billing">
            <CostBars data={topServices} fill />
          </ChartCard>
        )}
        {model.canSeeCost && model.groups?.length > 0 && (
          <ChartCard title="Resource group spend" href="/costs" link="Billing">
            <CostBars data={model.groups.slice(0, 6)} fill />
          </ChartCard>
        )}
        {model.canSeeCost && model.databricks.series.length > 0 && (
          <ChartCard title="Databricks usage" href="/data/databricks" link="Workspaces">
            <div className="h-full overflow-hidden">
              <UsageLines data={model.databricks.points} series={model.databricks.series} />
            </div>
          </ChartCard>
        )}
        <ChartCard title="Recent activity">
          <ul className="flex h-full flex-col justify-evenly">
            {activity.length === 0 && <li className="text-sm text-muted">No activity log events in the last 7 days.</li>}
            {activity.map((item) => (
              <li key={item.id} className="min-w-0">
                <div className="flex items-center justify-between gap-2 text-[11px] font-semibold uppercase tracking-wide text-muted">
                  <span>{item.status || "Activity"}</span>
                  <span>{item.time ? ago((Date.now() - Date.parse(item.time)) / 60000) : ""}</span>
                </div>
                <p className="truncate text-sm">{item.text}</p>
              </li>
            ))}
          </ul>
        </ChartCard>
      </div>
    </div>
  );
}
