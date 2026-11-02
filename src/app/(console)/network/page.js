"use client";

import Link from "next/link";
import { Kpi, PageHead, Panel, Pill, stateTone } from "@/components/ui";
import { useConsole } from "@/context/ConsoleContext";
import { healthBucket } from "@/lib/compute";
import { NETWORK_DEPTH, resourcesFor } from "@/lib/network";
import { num } from "@/lib/format";
import { SERVICES } from "@/lib/services";

const ORDER = ["virtual-networks", "application-gateways", "load-balancers", "front-door", "firewalls"];

export default function NetworkPage() {
  const { model } = useConsole();
  if (!model || model.status !== "ready") return null;
  const cards = ORDER.map((id) => {
    const service = SERVICES.find((item) => item.id === id);
    const rows = resourcesFor(model, id);
    const healthy = rows.filter((row) => healthBucket(row.status) === "healthy").length;
    const attention = rows.filter((row) => healthBucket(row.status) === "attention").length;
    return { id, label: service?.label || id, summary: NETWORK_DEPTH[id].summary, total: rows.length, healthy, attention };
  });
  const total = cards.reduce((sum, card) => sum + card.total, 0);
  const healthy = cards.reduce((sum, card) => sum + card.healthy, 0);
  const attention = cards.reduce((sum, card) => sum + card.attention, 0);
  return (
    <div className="space-y-4">
      <PageHead eyebrow={model.project.name} title="Network" description="Virtual networks, Application Gateway, load balancers, Front Door, and Azure Firewall. Each service opens onto address space, listeners, rules, metrics, and availability." />
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <Kpi label="Resources" value={num(total)} hint="Across five network services" />
        <Kpi label="Healthy" value={num(healthy)} hint="Succeeded or running" tone="ok" />
        <Kpi label="Attention" value={num(attention)} hint="Failed or degraded" tone={attention ? "danger" : "ok"} />
        <Kpi label="Services" value={num(cards.filter((card) => card.total).length)} hint="With resources in this project" tone="info" />
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {cards.map((card) => (
          <Link key={card.id} href={`/network/${card.id}`} className="block">
            <Panel className="h-full hover:border-brand">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h2 className="text-base font-semibold">{card.label}</h2>
                  <p className="mt-1 text-sm text-muted">{card.summary}</p>
                </div>
                <div className="text-2xl font-semibold tabular-nums">{num(card.total)}</div>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Pill tone="ok">{num(card.healthy)} healthy</Pill>
                {card.attention > 0 && <Pill tone={stateTone("failed")}>{num(card.attention)} attention</Pill>}
              </div>
            </Panel>
          </Link>
        ))}
      </div>
    </div>
  );
}
