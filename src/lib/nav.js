import { SERVICE_GROUPS, SERVICES } from "./services.js";

export function serviceMenus() {
  return SERVICE_GROUPS.map((group) => ({
    id: group.id,
    label: group.label,
    permission: `module.${group.id}`,
    children: SERVICES.filter((service) => service.group === group.id).map((service) => ({
      href: service.group === "compute" ? `/compute/${service.id}` : service.group === "data" ? `/data/${service.id}` : service.group === "network" ? `/network/${service.id}` : service.group === "platform" ? `/platform/${service.id}` : `/resources?service=${service.id}`,
      label: service.label,
      permission: `module.${group.id}`,
    })),
  }));
}

const ROUTE_RULES = [
  ["/break-glass", "module.break-glass"],
  ["/approvals", "module.approvals"],
  ["/architecture", "module.architecture"],
  ["/engineering", "module.engineering"],
  ["/workflows", "module.workflows"],
  ["/findings", "module.findings"],
  ["/wiki", "module.wiki"],
  ["/chat", "module.chat"],
  ["/costs", "module.costs"],
  ["/settings", "project.read"],
  ["/dashboard", "module.dashboard"],
  ["/resources", "module.services"],
  ["/compute", "module.compute"],
  ["/data", "module.data"],
  ["/network", "module.network"],
  ["/platform", "module.platform"],
  ["/vms", "module.compute"],
  ["/containers", "module.compute"],
  ["/databricks", "module.data"],
  ["/lakes", "module.data"],
  ["/pipelines", "module.data"],
  ["/alerts", "module.alerts"],
  ["/insights", "module.advisor"],
  ["/sandbox", "module.sandbox"],
  ["/sync", "module.sandbox"],
];

export function permissionForPath(pathname) {
  const hit = ROUTE_RULES.find(([path]) => pathname === path || pathname.startsWith(`${path}/`));
  return hit ? hit[1] : "project.read";
}
