import { assertCan, visibleProjects } from "@/lib/access";
import { sandboxCalls } from "@/lib/azure/calls";
import { estateErrorResponse } from "@/lib/estate-errors";
import { currentActor } from "@/lib/http";
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET(request) {
  try {
    const actor = await currentActor();
    const url = new URL(request.url);
    const projects = await visibleProjects(actor);
    const requested = url.searchParams.get("projectId");
    const project = projects.find((item) => item.id === requested) || projects[0];
    if (!project) return NextResponse.json({ calls: [] });
    await assertCan(actor, "project.read", project.id);
    const calls = await sandboxCalls(actor.org.id, project.id);
    return NextResponse.json({ calls });
  } catch (err) {
    return estateErrorResponse("calls", err);
  }
}
