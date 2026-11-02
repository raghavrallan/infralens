import { assertCan, holds, visibleProjects } from "./access.js";
import { claimSync, enqueueSync, readSchedule, readSnapshotKeys, releaseSync, scheduleDue, syncRunning } from "./estate-store.js";
import { estateMessage } from "./estate-messages.js";
import { currentActor } from "./http.js";
import { rangeById } from "./ranges.js";
import { workspacePayload } from "./workspace.js";

const EMPTY_KPIS = { spend: null, currency: "USD", forecast: null, resourceCount: 0, vmCount: 0, vmRunning: 0, groupCount: 0 };

function workspaceFor(actor, rangeId) {
  return workspacePayload(actor).then((workspace) => ({
    user: workspace.user,
    org: workspace.org,
    orgs: workspace.orgs,
    orgRole: workspace.orgRole,
    canManage: workspace.canManage,
    projects: workspace.projects,
    rangeId,
  }));
}

export async function resolveEstate(request) {
  const actor = await currentActor();
  const url = new URL(request.url);
  const range = rangeById(url.searchParams.get("range"));
  const projects = await visibleProjects(actor);
  if (!projects.length) {
    return {
      kind: "setup",
      actor,
      range,
      message: estateMessage(actor.membership.role === "member" ? "project.setupMember" : "project.setupAdmin"),
    };
  }
  const requested = url.searchParams.get("projectId");
  const project = projects.find((item) => item.id === requested) || projects[0];
  await assertCan(actor, "project.read", project.id);
  return {
    kind: "project",
    actor,
    project,
    range,
    url,
    canSeeCost: await holds(actor, "billing.read", project.id),
  };
}

function projectCard(project) {
  return { id: project.id, name: project.name, budget: project.budget_usd };
}

export async function controlEstate(request) {
  const opened = await resolveEstate(request);
  const workspace = await workspaceFor(opened.actor, opened.range.id);
  if (opened.kind === "setup") {
    return {
      status: "setup",
      workspace,
      range: opened.range,
      canSeeCost: false,
      warnings: [],
      subscriptions: [],
      project: null,
      message: opened.message,
      schedule: { cadence: "12h" },
      refreshing: false,
      syncedAt: null,
    };
  }
  const { actor, project, range, canSeeCost, url } = opened;
  const cadence = await readSchedule(actor.org.id, project.id);
  const meta = await readSnapshotKeys(actor.org.id, project.id, range.id, "status");
  const open = url.searchParams.get("open") === "1";
  const fresh = url.searchParams.get("fresh") === "1";
  const due = fresh || !meta && open || scheduleDue(cadence, meta?.syncedAt, open);
  let workerDown = false;
  if (due && !(await syncRunning(actor.org.id, project.id, range.id))) {
    const claimed = await claimSync(actor.org.id, project.id, range.id);
    if (claimed) {
      const code = await enqueueSync(actor.org.id, project.id, range.id);
      if (code !== 0) {
        workerDown = true;
        await releaseSync(actor.org.id, project.id, range.id);
      }
    }
  }
  const refreshing = await syncRunning(actor.org.id, project.id, range.id);
  const schedule = { cadence };
  if (!meta) {
    return {
      status: "syncing",
      message: estateMessage(workerDown ? "sync.workerDown" : "sync.preparing"),
      workspace,
      range,
      canSeeCost,
      warnings: [],
      subscriptions: [],
      project: projectCard(project),
      schedule,
      refreshing,
      syncedAt: null,
    };
  }
  return {
    status: meta.status || "ready",
    message: meta.message || "",
    warnings: meta.warnings || [],
    workspace,
    range,
    canSeeCost,
    subscriptions: meta.subscriptions || [],
    project: meta.project || projectCard(project),
    schedule,
    refreshing,
    syncedAt: meta.syncedAt,
  };
}

function hideCost(body) {
  return {
    ...body,
    canSeeCost: false,
    kpis: { ...(body.kpis || EMPTY_KPIS), spend: null, forecast: null },
    trend: { ...(body.trend || {}), points: [] },
    services: [],
    groups: [],
    databricks: { series: [], points: [] },
  };
}

function filterResources(rows, url) {
  const service = url.searchParams.get("service") || "";
  const group = url.searchParams.get("group") || "";
  if (service && !/^[a-z0-9-]{1,40}$/.test(service)) return [];
  return (rows || []).filter((item) => {
    if (service && item.service !== service) return false;
    if (group && item.group !== group) return false;
    return true;
  });
}

export async function estatePart(request, part) {
  const opened = await resolveEstate(request);
  if (opened.kind === "setup") return { part, status: "setup", message: opened.message };
  const row = await readSnapshotKeys(opened.actor.org.id, opened.project.id, opened.range.id, part);
  if (!row) return { part, status: "syncing", syncedAt: null };
  if (part === "overview") {
    const body = {
      part,
      status: row.status || "ready",
      message: row.message || "",
      warnings: row.warnings || [],
      project: row.project,
      canSeeCost: opened.canSeeCost,
      kpis: row.kpis || EMPTY_KPIS,
      trend: row.trend || { points: [] },
      services: row.services || [],
      groups: row.groups || [],
      databricks: row.databricks || { series: [], points: [] },
      syncedAt: row.syncedAt,
    };
    return opened.canSeeCost ? body : hideCost(body);
  }
  if (part === "resources") {
    return {
      part,
      resources: filterResources(row.resources, opened.url),
      vms: row.vms || [],
      hosting: row.hosting || [],
      workspaces: row.workspaces || [],
      storage: row.storage || [],
      pipelines: row.pipelines || [],
      subscriptions: row.subscriptions || [],
      project: row.project,
      syncedAt: row.syncedAt,
    };
  }
  if (part === "activity") {
    return { part, activity: row.activity || [], operations: row.operations || [], syncedAt: row.syncedAt };
  }
  if (part === "alerts") return { part, alerts: row.alerts || [], syncedAt: row.syncedAt };
  if (part === "advisor") return { part, advisor: row.advisor || [], syncedAt: row.syncedAt };
  return { part, syncedAt: row.syncedAt };
}
