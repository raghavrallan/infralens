import { assertCan, visibleProjects } from "@/lib/access";
import { estateErrorResponse } from "@/lib/estate-errors";
import { EstateError } from "@/lib/estate-messages";
import { cadenceOf, writeSchedule } from "@/lib/estate-store";
import { currentActor } from "@/lib/http";
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function POST(request) {
  try {
    const actor = await currentActor();
    const body = await request.json().catch(() => ({}));
    const projects = await visibleProjects(actor);
    const project = projects.find((item) => item.id === body.projectId) || projects[0];
    if (!project) throw new EstateError("project.missing");
    await assertCan(actor, "project.read", project.id);
    const cadence = await writeSchedule(actor.org.id, project.id, cadenceOf(body.cadence));
    return NextResponse.json({ cadence });
  } catch (err) {
    return estateErrorResponse("schedule", err);
  }
}
