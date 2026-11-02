import { randomBytes } from "node:crypto";
import { one, run } from "./db.js";
import { HttpError } from "./access.js";
import { hashPassword, id, sha256, usernameFor, verifyPassword } from "./ids.js";
import { sendInviteEmail, INVITE_MINUTES } from "./invite-mail.js";
import { ensureOrgColumns, assertAssignableRole, roleRank } from "./org-lifecycle.js";
import { rankOf, roleLabel, suiteRoleFor } from "./rbac.js";

async function roleNameFor(orgId, orgRole, projectRole) {
  if (orgRole === "org_admin") return "Organization admin";
  const label = roleLabel(projectRole);
  if (label !== projectRole) return label;
  const custom = await one("SELECT name FROM org_roles WHERE id = ? AND org_id = ?", [projectRole, orgId]);
  return custom?.name || "Member";
}

function appOrigin(request) {
  const proto = request.headers.get("x-forwarded-proto") || "http";
  const host = request.headers.get("x-forwarded-host") || request.headers.get("host");
  if (host) return `${proto}://${host}`;
  return String(process.env.PUBLIC_APP_URL || "http://127.0.0.1:3001").replace(/\/$/, "");
}

async function loadInvite(token) {
  await ensureOrgColumns();
  const row = await one(
    `SELECT i.id, i.org_id, i.email, i.invitee_name, i.org_role, i.project_id, i.project_role, i.status, i.expires_at,
            o.name AS org_name, p.name AS project_name
     FROM invites i
     JOIN organizations o ON o.id = i.org_id
     LEFT JOIN projects p ON p.id = i.project_id
     WHERE i.token_hash = ?`,
    [sha256(String(token || "").trim())],
  );
  if (!row) throw new HttpError(404, "This invite link is not valid.");
  if (row.status !== "pending") throw new HttpError(410, "This invite link has already been used.");
  if (new Date(row.expires_at).getTime() <= Date.now()) {
    await run("UPDATE invites SET status = 'expired' WHERE id = ? AND status = 'pending'", [row.id]);
    throw new HttpError(410, "This invite link has expired. Ask for a new one.");
  }
  return row;
}

export async function createMemberInvite(request, actor, body) {
  await ensureOrgColumns();
  const name = String(body.name || "").trim();
  const email = String(body.email || "").trim().toLowerCase();
  const orgRole = String(body.orgRole || "member");
  const projectId = String(body.projectId || "");
  const projectRole = String(body.projectRole || "");
  if (name.length < 2) throw new HttpError(400, "Enter the member's name.");
  if (!email.includes("@")) throw new HttpError(400, "Enter a valid email.");
  if (orgRole !== "member" && orgRole !== "org_admin") throw new HttpError(400, "Choose organization admin or member.");
  const actorRank = rankOf(actor.membership.role);
  let projectName = "";
  if (orgRole === "org_admin") {
    if (actorRank <= rankOf("org_admin")) throw new HttpError(403, "Only the organization owner can invite an admin.");
  } else {
    if (!projectId) throw new HttpError(400, "A member needs a project and a project role.");
    try {
      await assertAssignableRole(actor.org.id, projectRole);
    } catch (err) {
      throw new HttpError(err.status || 400, err.message);
    }
    const targetRank = await roleRank(actor.org.id, projectRole);
    if (actorRank <= targetRank) throw new HttpError(403, "Choose a role below your own level.");
    const project = await one(
      "SELECT id, name FROM projects WHERE id = ? AND org_id = ? AND COALESCE(status, 'active') = 'active'",
      [projectId, actor.org.id],
    );
    if (!project) throw new HttpError(404, "Project not found.");
    projectName = project.name;
  }
  const existingMember = await one(
    `SELECT u.id FROM users u
     JOIN org_memberships m ON m.user_id = u.id
     WHERE m.org_id = ? AND lower(u.email) = lower(?)`,
    [actor.org.id, email],
  );
  if (existingMember) throw new HttpError(409, "That person is already in this organization.");
  await run(
    "UPDATE invites SET status = 'revoked' WHERE org_id = ? AND lower(email) = lower(?) AND status = 'pending'",
    [actor.org.id, email],
  );
  const token = randomBytes(32).toString("base64url");
  const inviteId = id();
  await run(
    `INSERT INTO invites (
       id, org_id, email, token_hash, invited_role, org_role, project_id, project_role,
       status, invited_by, invitee_name, expires_at, created_at
     ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, now() + interval '${INVITE_MINUTES} minutes', now())`,
    [
      inviteId,
      actor.org.id,
      email,
      sha256(token),
      orgRole === "org_admin" ? "org_admin" : projectRole,
      orgRole,
      orgRole === "member" ? projectId : null,
      orgRole === "member" ? projectRole : "developer",
      actor.user.id,
      name,
    ],
  );
  const acceptUrl = `${appOrigin(request)}/accept-invite?token=${encodeURIComponent(token)}`;
  const roleName = await roleNameFor(actor.org.id, orgRole, projectRole);
  const emailSent = await sendInviteEmail({
    to: email,
    orgName: actor.org.name,
    inviterName: actor.user.name || "An organization admin",
    recipientName: name,
    roleName,
    projectName,
    acceptUrl,
  });
  return {
    ok: true,
    emailSent,
    acceptUrl: emailSent ? null : acceptUrl,
    expiresMinutes: INVITE_MINUTES,
  };
}

export async function peekInvite(token) {
  const invite = await loadInvite(token);
  const account = await one("SELECT id FROM users WHERE lower(email) = lower(?)", [invite.email]);
  return {
    email: invite.email,
    name: invite.invitee_name || "",
    orgName: invite.org_name,
    projectName: invite.project_name || "",
    role: await roleNameFor(invite.org_id, invite.org_role, invite.project_role),
    expiresAt: invite.expires_at,
    accountExists: Boolean(account),
  };
}

export async function acceptInvite({ token, name, password }) {
  const invite = await loadInvite(token);
  const chosen = String(name || invite.invitee_name || "").trim();
  const secret = String(password || "");
  if (chosen.length < 2) throw new HttpError(400, "Enter your name.");
  if (secret.length < 8) throw new HttpError(400, "Use a password of at least 8 characters.");
  let user = await one("SELECT id, password_hash FROM users WHERE lower(email) = lower(?)", [invite.email]);
  if (!user) {
    user = { id: id() };
    await run(
      "INSERT INTO users (id, username, email, display_name, password_hash, role, is_active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, true, now(), now())",
      [user.id, usernameFor(invite.email, user.id), invite.email, chosen, hashPassword(secret), suiteRoleFor(invite.org_role, invite.project_role)],
    );
  } else if (!verifyPassword(secret, user.password_hash)) {
    throw new HttpError(401, "That password does not match this account.");
  } else if (chosen) {
    await run("UPDATE users SET display_name = ?, updated_at = now() WHERE id = ?", [chosen, user.id]);
  }
  const membership = await one("SELECT id FROM org_memberships WHERE org_id = ? AND user_id = ?", [invite.org_id, user.id]);
  if (!membership) {
    await run(
      "INSERT INTO org_memberships (id, org_id, user_id, org_role, status, created_at) VALUES (?, ?, ?, ?, 'active', now())",
      [id(), invite.org_id, user.id, invite.org_role],
    );
  }
  if (invite.org_role === "member" && invite.project_id) {
    const projectMembership = await one(
      "SELECT id FROM project_memberships WHERE project_id = ? AND user_id = ?",
      [invite.project_id, user.id],
    );
    if (!projectMembership) {
      await run(
        "INSERT INTO project_memberships (id, project_id, user_id, project_role, created_at) VALUES (?, ?, ?, ?, now())",
        [id(), invite.project_id, user.id, invite.project_role],
      );
    }
  }
  await run("UPDATE invites SET status = 'accepted', accepted_at = now() WHERE id = ? AND status = 'pending'", [invite.id]);
  return { ok: true, email: invite.email };
}
