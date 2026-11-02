import { assertCan, visibleProjects } from "@/lib/access";
import { cacheReport, deleteCachedRead, deleteProjectCache } from "@/lib/read-cache";
import { estateErrorResponse } from "@/lib/estate-errors";
import { currentActor, ok } from "@/lib/http";
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

async function projectFor(actor, projectId) {
  const projects = await visibleProjects(actor);
  const project = projects.find((item) => item.id === projectId) || projects[0];
  if (!project) return null;
  await assertCan(actor, "project.read", project.id);
  return project;
}

export async function GET(request) {
  try {
    const actor = await currentActor();
    const url = new URL(request.url);
    const project = await projectFor(actor, url.searchParams.get("projectId") || "");
    if (!project) return NextResponse.json({ bytes: 0, count: 0, entries: [] });
    return NextResponse.json(await cacheReport(actor.org.id, project.id));
  } catch (err) {
    return estateErrorResponse("cache", err);
  }
}

export async function POST(request) {
  try {
    const actor = await currentActor();
    const body = await request.json().catch(() => ({}));
    const project = await projectFor(actor, String(body.projectId || ""));
    if (!project) return ok({ removed: 0, bytes: 0, count: 0, entries: [] });
    if (body.all === true) await deleteProjectCache(actor.org.id, project.id);
    else await deleteCachedRead(actor.org.id, project.id, String(body.id || ""));
    const report = await cacheReport(actor.org.id, project.id);
    return ok(report);
  } catch (err) {
    return estateErrorResponse("cache", err);
  }
}
