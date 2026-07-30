"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { fetchCurrentUser, getStoredUser } from "../lib/auth";

type Role = { id: string; label: string };
type UserRow = {
  id: string;
  username: string;
  name: string;
  email?: string;
  role: string;
  role_label?: string;
  is_active?: boolean;
};

export function UsersRolesPanel() {
  const [me, setMe] = useState(getStoredUser());
  const canManage =
    me?.role === "super_admin" ||
    me?.role === "org_admin" ||
    me?.display_role === "org_admin" ||
    me?.org_role === "org_admin";
  const [roles, setRoles] = useState<Role[]>([]);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [orgId, setOrgId] = useState(me?.primary_org_id || "");
  const [message, setMessage] = useState("");
  const [invite, setInvite] = useState({
    email: "",
    invited_role: "developer",
  });

  useEffect(() => {
    void fetchCurrentUser().then((u) => {
      if (u) {
        setMe(u);
        if (u.primary_org_id) setOrgId(u.primary_org_id);
      }
    });
  }, []);

  const load = useCallback(async () => {
    if (!canManage) return;
    try {
      const orgs = await api<{ id: string }[]>("/api/orgs");
      const activeOrg = orgId || orgs[0]?.id || "";
      if (activeOrg && activeOrg !== orgId) setOrgId(activeOrg);
      const [roleList, userList] = await Promise.all([
        api<Role[]>("/api/roles"),
        api<UserRow[]>(
          activeOrg ? `/api/users?org_id=${encodeURIComponent(activeOrg)}` : "/api/users",
        ),
      ]);
      setRoles(roleList.filter((r) => r.id !== "super_admin"));
      setUsers(userList);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not load users");
    }
  }, [canManage, orgId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!canManage) {
    return (
      <section className="card">
        <div className="card-head">
          <h3>Users &amp; roles</h3>
        </div>
        <p className="empty-note">
          Org Admin required. Manage invites in{" "}
          <a href="/organizations">Organizations</a>.
        </p>
      </section>
    );
  }

  const sendInvite = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!orgId) {
      setMessage("Select an organization first (Organizations page).");
      return;
    }
    setMessage("Sending invite…");
    try {
      const result = await api<{
        email_sent?: boolean;
        accept_token?: string;
        accept_url?: string;
      }>(`/api/orgs/${orgId}/invites`, {
        method: "POST",
        body: JSON.stringify({
          email: invite.email,
          invited_role: invite.invited_role,
          org_role: invite.invited_role === "org_admin" ? "org_admin" : "member",
        }),
      });
      setInvite({ email: "", invited_role: "developer" });
      setMessage(
        result.email_sent
          ? "Invite emailed."
          : result.accept_url
            ? `Email not sent (SMTP unreachable). Share: ${result.accept_url}`
            : "Invite created.",
      );
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Invite failed");
    }
  };

  const patch = async (userId: string, body: Record<string, unknown>) => {
    setMessage("Saving…");
    try {
      await api(`/api/users/${userId}`, { method: "PATCH", body: JSON.stringify(body) });
      setMessage("Updated.");
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Update failed");
    }
  };

  return (
    <section className="card users-roles">
      <div className="card-head">
        <h3>Users &amp; roles</h3>
        <span className="pill ok">{users.length} users</span>
      </div>
      <p className="empty-note">
        Invite by email. Full console: <a href="/organizations">Organizations</a>.
      </p>
      <form className="users-create" onSubmit={(e) => void sendInvite(e)}>
        <input
          type="email"
          placeholder="Email"
          value={invite.email}
          onChange={(e) => setInvite({ ...invite, email: e.target.value })}
          required
        />
        <select
          value={invite.invited_role}
          onChange={(e) => setInvite({ ...invite, invited_role: e.target.value })}
        >
          {roles.map((role) => (
            <option key={role.id} value={role.id}>
              {role.label}
            </option>
          ))}
        </select>
        <button type="submit" className="tiny-btn solid">
          Invite
        </button>
      </form>
      <div className="users-table">
        {users.map((user) => (
          <div key={user.id} className="user-row">
            <div>
              <strong>{user.name}</strong>
              <div className="empty-note">
                {user.username}
                {user.email ? ` · ${user.email}` : ""}
              </div>
            </div>
            <select
              value={user.role}
              onChange={(e) => void patch(user.id, { role: e.target.value })}
            >
              {roles.map((role) => (
                <option key={role.id} value={role.id}>
                  {role.label}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="tiny-btn"
              onClick={() => void patch(user.id, { is_active: !user.is_active })}
            >
              {user.is_active ? "Disable" : "Enable"}
            </button>
          </div>
        ))}
      </div>
      {message && <div className="form-msg">{message}</div>}
    </section>
  );
}
