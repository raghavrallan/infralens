import { readFileSync } from "fs";
import { randomBytes } from "crypto";

const envFile = new URL("../.env", import.meta.url);
for (const line of readFileSync(envFile, "utf8").split("\n")) {
  const trimmed = line.trim();
  if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) continue;
  const name = trimmed.slice(0, trimmed.indexOf("=")).trim();
  let value = trimmed.slice(trimmed.indexOf("=") + 1).trim();
  if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
    value = value.slice(1, -1);
  }
  if (!process.env[name]) process.env[name] = value;
}

process.env.INFRALENS_SCHEMA = `ilcheck_${randomBytes(4).toString("hex")}`;
process.env.APP_SECRET = "test-secret";

const { closeDb, dropConsoleSchema, ensureConsoleSchema, many, one, run } = await import("../src/lib/db.js");
const { hashPassword, id, usernameFor } = await import("../src/lib/ids.js");
const { can } = await import("../src/lib/rbac.js");
const { bindConnections, replaceSubscriptions, subscriptionsForProject, visibleProjects } = await import("../src/lib/access.js");
const { createSession, readSession } = await import("../src/lib/session.js");
const { eachDay, foldCosts } = await import("../src/lib/azure/fold.js");
const { encrypt, decrypt } = await import("../src/lib/crypto.js");

try {
  await ensureConsoleSchema();
  const now = Date.now();
  const orgA = id();
  const orgB = id();
  const userA = id();
  const userB = id();
  await run(
    "INSERT INTO organizations (id, name, slug, created_by) VALUES (?, ?, ?, ?)",
    [orgA, "North Client", "north", userA],
  );
  await run(
    "INSERT INTO organizations (id, name, slug, created_by) VALUES (?, ?, ?, ?)",
    [orgB, "South Client", "south", userB],
  );
  await run(
    "INSERT INTO users (id, username, email, display_name, password_hash, role) VALUES (?, ?, ?, ?, ?, 'org_admin')",
    [userA, usernameFor("a@north.test", userA), "a@north.test", "A", hashPassword("password-a")],
  );
  await run(
    "INSERT INTO users (id, username, email, display_name, password_hash, role) VALUES (?, ?, ?, ?, ?, 'viewer')",
    [userB, usernameFor("b@south.test", userB), "b@south.test", "B", hashPassword("password-b")],
  );
  await run("INSERT INTO org_memberships (id, org_id, user_id, org_role) VALUES (?, ?, ?, 'org_owner')", [id(), orgA, userA]);
  await run("INSERT INTO org_memberships (id, org_id, user_id, org_role) VALUES (?, ?, ?, 'member')", [id(), orgB, userB]);

  const projectA = id();
  const projectB = id();
  const projectB2 = id();
  await run(
    "INSERT INTO projects (id, org_id, name, slug, budget_usd) VALUES (?, ?, ?, ?, ?)",
    [projectA, orgA, "North prod", "prod", 1000],
  );
  await run(
    "INSERT INTO projects (id, org_id, name, slug, budget_usd) VALUES (?, ?, ?, ?, ?)",
    [projectB, orgB, "South prod", "prod", 1000],
  );
  await run(
    "INSERT INTO projects (id, org_id, name, slug, budget_usd) VALUES (?, ?, ?, ?, ?)",
    [projectB2, orgB, "South other", "other", 1000],
  );
  await run(
    "INSERT INTO project_memberships (id, project_id, user_id, project_role) VALUES (?, ?, ?, 'operator')",
    [id(), projectB, userB],
  );

  const subA = "11111111-1111-1111-1111-111111111111";
  const subB = "22222222-2222-2222-2222-222222222222";
  const connectionA = id();
  const connectionB = id();
  await run(
    "INSERT INTO azure_connections (id, org_id, name, tenant_id, client_id, secret_cipher, status, created_at) VALUES (?, ?, 'A', ?, ?, ?, 'connected', ?)",
    [connectionA, orgA, subA, subA, encrypt("secret-a"), now],
  );
  await run(
    "INSERT INTO azure_connections (id, org_id, name, tenant_id, client_id, secret_cipher, status, created_at) VALUES (?, ?, 'B', ?, ?, ?, 'connected', ?)",
    [connectionB, orgB, subB, subB, encrypt("secret-b"), now],
  );
  await replaceSubscriptions(orgA, connectionA, [{ id: subA, name: "North sub", state: "Enabled" }]);
  await replaceSubscriptions(orgB, connectionB, [{ id: subB, name: "South sub", state: "Enabled" }]);
  await bindConnections(orgA, projectA, [connectionA]);
  await bindConnections(orgB, projectB, [connectionB, connectionB]);
  await bindConnections(orgB, projectB2, [connectionB]);
  const mapped = await one("SELECT COUNT(*)::int AS n FROM project_connections WHERE project_id = ?", [projectB]);
  if (mapped.n !== 1) throw new Error("duplicate connection on one project was stored");
  if ((await subscriptionsForProject(projectB2, orgB)).map((item) => item.id).join() !== subB) {
    throw new Error("the same connection could not be mapped to a second project");
  }

  const actorB = {
    user: { id: userB },
    org: { id: orgB },
    membership: { role: "member" },
  };
  const visible = (await visibleProjects(actorB)).map((item) => item.id);
  if (visible.includes(projectA) || visible.includes(projectB2) || !visible.includes(projectB)) {
    throw new Error(`project isolation failed: ${visible.join(",")}`);
  }
  const subs = (await subscriptionsForProject(projectB, orgB)).map((item) => item.id);
  if (subs.includes(subA) || !subs.includes(subB)) throw new Error("subscription isolation failed");
  if ((await subscriptionsForProject(projectA, orgB)).length !== 0) throw new Error("cross-org subscription lookup leaked");

  let blocked = false;
  try {
    await replaceSubscriptions(orgA, connectionA, [{ id: subB, name: "Stolen", state: "Enabled" }]);
  } catch {
    blocked = true;
  }
  if (!blocked) throw new Error("cross-org subscription claim was allowed");

  if (can("member", "operator", "billing.read")) throw new Error("operator can see billing");
  if (!can("member", "viewer", "billing.read")) throw new Error("viewer cannot see billing");
  if (can("member", "project_admin", "connection.manage")) throw new Error("project admin can manage the connection");
  if (!can("org_owner", null, "connection.manage")) throw new Error("owner cannot manage the connection");

  const token = await createSession(userA, orgA);
  const session = await readSession(token);
  if (session.org_id !== orgA || session.user_id !== userA) throw new Error("session org binding failed");
  const secret = await one("SELECT secret_cipher FROM azure_connections WHERE id = ?", [connectionA]);
  if (decrypt(secret.secret_cipher) !== "secret-a") throw new Error("secret round-trip failed");

  const days = eachDay("2026-10-01", "2026-10-04");
  const folded = foldCosts(
    [
      { UsageDate: 20261001, ServiceName: "Virtual Machines", Cost: 10, Currency: "USD" },
      { UsageDate: 20261003, ServiceName: "Virtual Machines", Cost: 5, Currency: "USD" },
    ],
    days,
  );
  if (folded.points.length !== 3 || folded.points[1].spend !== 0 || folded.total !== 15) {
    throw new Error(`cost fold failed: ${JSON.stringify(folded)}`);
  }

  const leaked = await many("SELECT id FROM organizations");
  if (leaked.length !== 2) throw new Error("check schema saw the wrong organizations");
  console.log("access isolation ok");
} finally {
  await dropConsoleSchema();
  await closeDb();
}
