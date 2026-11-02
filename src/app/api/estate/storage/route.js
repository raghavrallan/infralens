import { assertCan, holds, visibleProjects } from "@/lib/access";
import { readSchedule, syncRunning } from "@/lib/estate-store";
import { many, one } from "@/lib/db";
import { estateErrorResponse } from "@/lib/estate-errors";
import { currentActor } from "@/lib/http";
import { RANGES } from "@/lib/ranges";
import { describeSandbox } from "@/lib/azure/sandbox";
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const LABELS = {
  estate_snapshots: "Saved Azure copies",
  estate_schedules: "Sync schedules",
  estate_syncs: "Syncs in progress",
  subscriptions: "Azure subscriptions",
  azure_connections: "Azure connections",
  projects: "Projects",
  organizations: "Organizations",
  users: "People",
  org_memberships: "Organization memberships",
  project_memberships: "Project memberships",
  project_connections: "Project connections",
  project_subscriptions: "Project subscriptions",
  sessions: "Sign-in sessions",
  audit_log: "Audit log",
};

export async function GET(request) {
  try {
    const actor = await currentActor();
    const url = new URL(request.url);
    const projects = await visibleProjects(actor);
    const requested = url.searchParams.get("projectId");
    const project = projects.find((item) => item.id === requested) || projects[0];
    if (!project) return NextResponse.json({ snapshots: [], services: [], tables: [], running: [], cadence: "12h" });
    await assertCan(actor, "project.read", project.id);
    const seeCost = await holds(actor, "billing.read", project.id);
    const cadence = await readSchedule(actor.org.id, project.id);
    const snapshots = await many(
      `SELECT range_id, synced_at, pg_column_size(payload) AS bytes,
              COALESCE(jsonb_array_length(payload->'resources'), 0) AS resources,
              COALESCE(jsonb_array_length(payload->'subscriptions'), 0) AS subscriptions,
              COALESCE(jsonb_array_length(payload->'services'), 0) AS services,
              COALESCE(jsonb_array_length(payload->'groups'), 0) AS groups,
              COALESCE(jsonb_array_length(payload->'activity'), 0) AS activity,
              COALESCE(jsonb_array_length(payload->'alerts'), 0) AS alerts,
              COALESCE(jsonb_array_length(payload->'advisor'), 0) AS advisor,
              payload->'kpis'->>'spend' AS spend,
              payload->'kpis'->>'currency' AS currency,
              payload->>'status' AS status
       FROM estate_snapshots
       WHERE org_id = ? AND project_id = ?`,
      [actor.org.id, project.id],
    );
    const services = await many(
      `SELECT s.range_id, item->>'serviceLabel' AS name, COUNT(*)::int AS count
       FROM estate_snapshots s
       CROSS JOIN LATERAL jsonb_array_elements(COALESCE(s.payload->'resources', '[]'::jsonb)) item
       WHERE s.org_id = ? AND s.project_id = ?
       GROUP BY s.range_id, item->>'serviceLabel'
       ORDER BY COUNT(*) DESC`,
      [actor.org.id, project.id],
    );
    const tables = await many(
      `SELECT c.relname AS name, pg_total_relation_size(c.oid)::bigint AS bytes
       FROM pg_class c
       JOIN pg_namespace n ON n.oid = c.relnamespace
       WHERE n.nspname = current_schema() AND c.relkind = 'r'
       ORDER BY pg_total_relation_size(c.oid) DESC`,
    );
    const counted = [];
    for (const table of tables) {
      if (!/^[a-z_]+$/.test(table.name)) continue;
      const row = await one(`SELECT COUNT(*)::int AS rows FROM ${table.name}`);
      counted.push({
        name: table.name,
        label: LABELS[table.name] || table.name,
        rows: row?.rows || 0,
        bytes: Number(table.bytes) || 0,
      });
    }
    const byRange = new Map(snapshots.map((row) => [row.range_id, row]));
    const copies = [];
    for (const range of RANGES) {
      const row = byRange.get(range.id);
      const running = await syncRunning(actor.org.id, project.id, range.id);
      copies.push({
        id: range.id,
        label: range.label,
        saved: Boolean(row),
        syncedAt: row ? Number(row.synced_at) : null,
        bytes: row ? Number(row.bytes) : 0,
        resources: row ? Number(row.resources) : 0,
        subscriptions: row ? Number(row.subscriptions) : 0,
        services: row ? Number(row.services) : 0,
        groups: row ? Number(row.groups) : 0,
        activity: row ? Number(row.activity) : 0,
        alerts: row ? Number(row.alerts) : 0,
        advisor: row ? Number(row.advisor) : 0,
        spend: seeCost && row?.spend != null ? Number(row.spend) : null,
        currency: row?.currency || "USD",
        status: running ? "syncing" : row?.status || "missing",
      });
    }
    const connections = await many(
      `SELECT c.id, c.name, c.status, c.last_checked_at
       FROM azure_connections c
       JOIN project_connections pc ON pc.connection_id = c.id
       WHERE pc.project_id = ? AND c.org_id = ?`,
      [project.id, actor.org.id],
    );
    const sandboxes = connections.map((row) => {
      const profile = describeSandbox(row.id);
      return {
        id: row.id,
        name: row.name,
        status: row.status,
        checkedAt: row.last_checked_at ? Number(row.last_checked_at) : null,
        ready: profile.ready,
        lastLoginAt: profile.lastLoginAt,
        transport: "az-cli",
      };
    });
    return NextResponse.json({
      project: { id: project.id, name: project.name },
      cadence,
      queue: "estate",
      redisDb: 1,
      sandboxes,
      seeCost,
      copies,
      services: services.map((row) => ({ rangeId: row.range_id, name: row.name || "Other", count: Number(row.count) })),
      tables: counted,
      storedBytes: counted.reduce((sum, table) => sum + table.bytes, 0),
      snapshotBytes: copies.reduce((sum, copy) => sum + copy.bytes, 0),
    });
  } catch (err) {
    return estateErrorResponse("storage", err);
  }
}
