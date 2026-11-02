"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";
import { DataTable, PageHead, Panel, Pill, stateTone } from "@/components/ui";
import { useConsole } from "@/context/ConsoleContext";
import { isCompute } from "@/lib/compute";
import { isData } from "@/lib/data";
import { isNetwork } from "@/lib/network";
import { isPlatform } from "@/lib/platform";
import { SERVICE_GROUPS, SERVICES, serviceById, servicesForKind } from "@/lib/services";

function ResourcesBody() {
  const params = useSearchParams();
  const router = useRouter();
  const service = serviceById(params.get("service"));
  const groupId = params.get("group");
  const kind = params.get("kind");
  useEffect(() => {
    if (service && isCompute(service.id)) router.replace(`/compute/${service.id}`);
    else if (service && isData(service.id)) router.replace(`/data/${service.id}`);
    else if (service && isNetwork(service.id)) router.replace(`/network/${service.id}`);
    else if (service && isPlatform(service.id)) router.replace(`/platform/${service.id}`);
    else if (groupId === "compute") router.replace("/compute");
    else if (groupId === "data") router.replace("/data");
    else if (groupId === "network") router.replace("/network");
    else if (groupId === "platform") router.replace("/platform");
    else if (kind === "database") router.replace("/data");
    else if (kind === "storage") router.replace("/data/storage");
    else if (kind === "cdn") router.replace("/network/front-door");
  }, [service, groupId, kind, router]);
  const group = SERVICE_GROUPS.find((item) => item.id === params.get("group"));
  const legacy = servicesForKind(params.get("kind"));
  const { model } = useConsole();
  if ((service && (isCompute(service.id) || isData(service.id) || isNetwork(service.id) || isPlatform(service.id))) || groupId === "compute" || groupId === "data" || groupId === "network" || groupId === "platform" || kind === "database" || kind === "storage" || kind === "cdn") return null;
  if (!model || model.status !== "ready") return null;
  const rows = model.resources.filter((item) => {
    if (service) return item.service === service.id;
    if (group) return SERVICES.some((entry) => entry.id === item.service && entry.group === group.id);
    if (legacy) return legacy.includes(item.service);
    return true;
  });
  const title = service?.label || group?.label || "All services";
  const columns = [
    { key: "name", label: "Name" },
    ...(!service ? [{ key: "serviceLabel", label: "Service" }] : []),
    { key: "type", label: "Type" },
    { key: "group", label: "Resource group" },
    { key: "location", label: "Region" },
    ...(service?.id === "virtual-machines"
      ? [
          { key: "size", label: "Size" },
          { key: "state", label: "Power", render: (row) => row.state ? <Pill tone={stateTone(row.state)}>{row.state}</Pill> : "" },
        ]
      : []),
  ];
  return (
    <div className="space-y-4">
      <PageHead
        eyebrow={model.project.name}
        title={title}
        description={`Infralens tracks ${SERVICES.length} Azure services for this project. Other resource types stay out of these tables.`}
      />
      <Panel>
        <DataTable rows={rows} searchKeys={["name", "serviceLabel", "type", "group", "location"]} columns={columns} />
      </Panel>
    </div>
  );
}

export default function ResourcesPage() {
  return (
    <Suspense fallback={<p className="text-sm text-muted">Loading resources…</p>}>
      <ResourcesBody />
    </Suspense>
  );
}
