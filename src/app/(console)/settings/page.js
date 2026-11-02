"use client";

import { useEffect, useState } from "react";
import { PageHead, Panel } from "@/components/ui";
import { useFeedback } from "@/components/Feedback";
import { useConsole } from "@/context/ConsoleContext";
import { SuiteSettingsBody } from "@/app/(console)/suite-settings/page";
import { SuiteGate } from "@/components/suite/SuiteScreen";
import { can, LADDER, levelOf, MODULES, permissionsFor, rankOf, roleLabel, rolePower } from "@/lib/rbac";

const field = "mt-1 h-11 w-full rounded-2xl border border-line px-3 text-sm outline-none focus:border-brand";

export default function SettingsPage() {
  const { refresh, notify } = useConsole();
  const { startBusy, stopBusy } = useFeedback();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [connection, setConnection] = useState({ name: "Production reader", tenantId: "", clientId: "", clientSecret: "" });
  const [project, setProject] = useState({ name: "", budget: "", connectionIds: [] });
  const [editing, setEditing] = useState(null);
  const [savingConnection, setSavingConnection] = useState(false);
  const [connectionError, setConnectionError] = useState("");
  const [refreshingId, setRefreshingId] = useState("");
  const [savingProject, setSavingProject] = useState(false);
  const [member, setMember] = useState({ name: "", email: "", orgRole: "member", projectId: "", projectRole: "developer" });
  const [tab, setTab] = useState("projects");
  const [creating, setCreating] = useState(false);
  const [inviteLink, setInviteLink] = useState("");
  const [roleName, setRoleName] = useState("");
  const [roleRank, setRoleRank] = useState(10);
  const [rolePermissions, setRolePermissions] = useState(["module.dashboard"]);

  async function load() {
    const res = await fetch("/api/workspace", { cache: "no-store" });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      setError(body.message || "Could not load the organization.");
      return;
    }
    setData(body);
    setError("");
  }

  useEffect(() => {
    document.title = "Organization · Infralens";
    load();
  }, []);

  async function submit(url, payload, method = "POST") {
    let res;
    try {
      res = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    } catch {
      const message = "The network request failed.";
      notify(message, "error");
      return { ok: false, message };
    }
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      const message = body.message || "That did not save.";
      notify(message, "error");
      return { ok: false, message };
    }
    await load();
    refresh();
    return { ok: true, body };
  }

  function labelFor(role) {
    return (data?.roles || []).find((item) => item.id === role)?.name || roleLabel(role);
  }

  function keptUntil(value) {
    const time = new Date(value);
    if (!Number.isFinite(time.getTime())) return "";
    return new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeZone: "UTC" }).format(time);
  }

  if (!data) return <p className="text-sm text-muted">{error || "Loading organization…"}</p>;
  const canSuite = data.canManage || (data.projects || []).some((item) => can(data.orgRole, item.role, "suite.manage", item.permissions));
  const actorRank = rankOf(data.orgRole, data.roles || []);
  function personRank(item) {
    return Math.max(rankOf(item.role, data.roles || []), ...(item.projects || []).map((entry) => rankOf(entry.role, data.roles || [])));
  }
  function moduleLabel(key) {
    return MODULES.find((item) => item[0] === key)?.[1] || key;
  }
  const tabs = [
    ["projects", "Projects"],
    ["people", "People"],
    ["roles", "Roles"],
    ["azure", "Azure"],
    ...(canSuite ? [["suite", "Agentic"]] : []),
  ];

  return (
    <div className="space-y-4">
      <PageHead eyebrow={data.org.name} title="Organization" description={`${roleLabel(data.orgRole)}. Each project keeps its own estate, cost, invoices, and skills data. Deactivating a project keeps that history for 60 days.`} />
      {data.canManage && (
        <div className="flex flex-wrap gap-2">
          {tabs.map(([id, label]) => (
            <button key={id} type="button" onClick={() => setTab(id)} className={`rounded-full px-3 py-1.5 text-xs font-semibold ${tab === id ? "bg-ink text-white" : "bg-white text-muted"}`}>
              {label}
            </button>
          ))}
        </div>
      )}
      {error && <p className="text-sm text-danger">{error}</p>}
      {!data.canManage && canSuite && (
        <SuiteGate>
          <SuiteSettingsBody />
        </SuiteGate>
      )}
      {!data.canManage && (
        <Panel title="Your access">
          <ul className="space-y-2 text-sm">
            {data.projects.map((item) => (
              <li key={item.id}>
                {item.name} · {roleLabel(item.role)}
              </li>
            ))}
            {data.projects.length === 0 && <li className="text-muted">You are not on a project yet.</li>}
          </ul>
        </Panel>
      )}
      {data.canManage && tab === "azure" && (
        <>
          <Panel title="Azure app registration">
            <p className="mb-3 text-sm text-muted">
              The secret is encrypted on this server and is only passed to Azure CLI for this organization. Grant the app Reader and Cost Management Reader. Do not grant Owner.
            </p>
            <form
              className="grid gap-3 md:grid-cols-2"
              onSubmit={async (event) => {
                event.preventDefault();
                if (savingConnection) return;
                const payload = { ...connection };
                setConnection((current) => ({ ...current, clientSecret: "" }));
                setSavingConnection(true);
                setConnectionError("");
                startBusy("Testing the Azure connection…");
                let saved = { ok: false, message: "That did not save." };
                try {
                  saved = await submit("/api/connections", payload);
                } finally {
                  stopBusy();
                  setSavingConnection(false);
                }
                if (!saved.ok) {
                  setConnectionError(saved.message);
                  return;
                }
                setConnection({ name: "Production reader", tenantId: "", clientId: "", clientSecret: "" });
                notify(saved.body?.updated ? "Existing connection updated." : "Azure connection saved.", "ok");
              }}
            >
              <label className="text-xs font-semibold text-muted">Name<input className={field} value={connection.name} onChange={(event) => setConnection({ ...connection, name: event.target.value })} disabled={savingConnection} /></label>
              <label className="text-xs font-semibold text-muted">Tenant ID<input className={field} value={connection.tenantId} onChange={(event) => setConnection({ ...connection, tenantId: event.target.value })} disabled={savingConnection} /></label>
              <label className="text-xs font-semibold text-muted">Client ID<input className={field} value={connection.clientId} onChange={(event) => setConnection({ ...connection, clientId: event.target.value })} disabled={savingConnection} /></label>
              <label className="text-xs font-semibold text-muted">Client secret<input type="password" autoComplete="new-password" className={field} value={connection.clientSecret} onChange={(event) => setConnection({ ...connection, clientSecret: event.target.value })} disabled={savingConnection} /></label>
              {connectionError && <p className="text-sm text-danger md:col-span-2">{connectionError}</p>}
              <button className="h-11 rounded-2xl bg-brand px-4 text-sm font-semibold text-white disabled:opacity-60 md:col-span-2" type="submit" disabled={savingConnection}>
                {savingConnection ? "Testing connection…" : "Test and save"}
              </button>
            </form>
            <ul className="mt-4 space-y-2 text-sm">
              {(data.connections || []).map((item) => (
                <li key={item.id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-line px-3 py-2">
                  <span>
                    <span className="font-semibold">{item.name}</span>
                    <span className="block text-xs text-muted">
                      {item.status} · {item.statusDetail || "Secret stored"} · client ••••{item.clientHint}
                    </span>
                  </span>
                  <button
                    type="button"
                    className="text-xs font-semibold text-brand disabled:opacity-60"
                    disabled={refreshingId === item.id}
                    onClick={async () => {
                      setRefreshingId(item.id);
                      startBusy("Refreshing subscriptions…");
                      let saved = { ok: false, message: "Could not refresh subscriptions." };
                      try {
                        saved = await submit(`/api/connections/${item.id}/refresh`, {});
                      } finally {
                        stopBusy();
                        setRefreshingId("");
                      }
                      if (!saved.ok) setConnectionError(saved.message);
                    }}
                  >
                    {refreshingId === item.id ? "Refreshing…" : "Refresh subscriptions"}
                  </button>
                </li>
              ))}
            </ul>
          </Panel>
        </>
      )}
      {data.canManage && tab === "projects" && (
        <>
          <Panel title="Projects">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm text-muted">Each project keeps its own Azure connection. A connection mapped to one project cannot be used by another.</p>
              <button type="button" className="h-11 rounded-2xl bg-brand px-4 text-sm font-semibold text-white" onClick={() => setCreating((open) => !open)}>
                {creating ? "Close" : "Create project"}
              </button>
            </div>
            {creating && (
              <form
                className="mb-4 space-y-3 rounded-2xl border border-line p-3"
                onSubmit={async (event) => {
                  event.preventDefault();
                  if (savingProject) return;
                  setSavingProject(true);
                  startBusy("Creating the project…");
                  const saved = await submit("/api/projects", { name: project.name, budget: project.budget, connectionIds: [] });
                  stopBusy();
                  setSavingProject(false);
                  if (saved.ok) {
                    setProject({ name: "", budget: "", connectionIds: [] });
                    setCreating(false);
                    notify("Project created. Map its connection on the project row.", "ok");
                  }
                }}
              >
                <div className="grid gap-3 md:grid-cols-2">
                  <label className="text-xs font-semibold text-muted">Name<input className={field} value={project.name} onChange={(event) => setProject({ ...project, name: event.target.value })} /></label>
                  <label className="text-xs font-semibold text-muted">Monthly budget USD<input className={field} value={project.budget} onChange={(event) => setProject({ ...project, budget: event.target.value })} /></label>
                </div>
                <button className="h-11 rounded-2xl bg-ink px-4 text-sm font-semibold text-white disabled:opacity-60" type="submit" disabled={savingProject}>
                  {savingProject ? "Creating project…" : "Save project"}
                </button>
              </form>
            )}
            <ul className="space-y-2 text-sm">
              {data.projects.map((item) => (
                <li key={item.id} className="rounded-xl border border-line px-3 py-2">
                  <div className="flex items-center justify-between gap-2">
                    <span>
                      <span className="font-semibold">{item.name}</span>
                      <span className="block text-xs text-muted">{item.connectionIds.length} connections · {item.subscriptionIds.length} subscriptions</span>
                    </span>
                    <span className="flex items-center gap-3">
                      <button type="button" className="text-xs font-semibold text-brand" onClick={() => setEditing({ id: item.id, name: item.name, budget: item.budget ?? "", connectionIds: [...new Set(item.connectionIds)] })}>
                        Map connections
                      </button>
                      <button
                        type="button"
                        className="text-xs font-semibold text-danger"
                        onClick={async () => {
                          if (!window.confirm(`Deactivate ${item.name}? Its data stays isolated for 60 days, then it is deleted.`)) return;
                          const saved = await submit(`/api/projects/${item.id}`, { status: "inactive" }, "PATCH");
                          if (saved.ok) notify("Project deactivated. History is kept for 60 days.", "ok");
                        }}
                      >
                        Deactivate
                      </button>
                    </span>
                  </div>
                  {editing?.id === item.id && (
                    <form
                      className="mt-3 space-y-2"
                      onSubmit={async (event) => {
                        event.preventDefault();
                        startBusy("Saving the project mapping…");
                        let saved = { ok: false, message: "Could not save the mapping." };
                        try {
                          saved = await submit(`/api/projects/${item.id}`, { ...editing, connectionIds: [...new Set(editing.connectionIds)] }, "PATCH");
                        } finally {
                          stopBusy();
                        }
                        if (saved.ok) {
                          setEditing(null);
                          notify("Project mapping saved.", "ok");
                        }
                      }}
                    >
                      {(data.connections || []).map((entry) => {
                        const taken = entry.projectId && entry.projectId !== item.id;
                        return (
                          <label key={entry.id} className={`flex items-center gap-2 ${taken ? "text-muted" : ""}`}>
                            <input
                              type="checkbox"
                              disabled={taken}
                              checked={!taken && editing.connectionIds.includes(entry.id)}
                              onChange={(event) => {
                                setEditing((current) => ({
                                  ...current,
                                  connectionIds: event.target.checked
                                    ? [...new Set([...current.connectionIds, entry.id])]
                                    : current.connectionIds.filter((id) => id !== entry.id),
                                }));
                              }}
                            />
                            <span>{entry.name}</span>
                            <span className="text-xs text-muted">{taken ? `Already on ${entry.projectName}` : `${entry.status} · client ••••${entry.clientHint}`}</span>
                          </label>
                        );
                      })}
                      {(data.connections || []).length === 0 && <p className="text-sm text-muted">Add an Azure app registration on the Azure tab first.</p>}
                      <button className="h-9 rounded-xl bg-brand px-3 text-xs font-semibold text-white" type="submit">Save mapping</button>
                    </form>
                  )}
                </li>
              ))}
            </ul>
            {(data.archivedProjects || []).length > 0 && (
              <div className="mt-4 space-y-2">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Deactivated</h3>
                {data.archivedProjects.map((item) => (
                  <div key={item.id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-line px-3 py-2">
                    <span>
                      <span className="font-semibold">{item.name}</span>
                      <span className="block text-xs text-muted">History kept until {keptUntil(item.purgeAt)}. After that the project data is deleted.</span>
                    </span>
                    <button
                      type="button"
                      className="text-xs font-semibold text-brand"
                      onClick={async () => {
                        const saved = await submit(`/api/projects/${item.id}`, { status: "active" }, "PATCH");
                        if (saved.ok) notify("Project activated.", "ok");
                      }}
                    >
                      Activate
                    </button>
                  </div>
                ))}
              </div>
            )}
          </Panel>
        </>
      )}
      {data.canManage && tab === "people" && (
          <Panel title="Members">
            <form
              className="grid gap-3 md:grid-cols-2"
              onSubmit={async (event) => {
                event.preventDefault();
                setInviteLink("");
                const saved = await submit("/api/members", member);
                if (saved.ok) {
                  setMember({ name: "", email: "", orgRole: "member", projectId: "", projectRole: "developer" });
                  if (saved.body.emailSent) notify("Invite sent. The link expires in 15 minutes.", "ok");
                  else {
                    setInviteLink(saved.body.acceptUrl || "");
                    notify("Invite is ready. Email sends once SMTP is connected. The link expires in 15 minutes.", "ok");
                  }
                }
              }}
            >
              <p className="text-sm text-muted md:col-span-2">No password is set here. The person gets an invite and chooses their own password. The link lasts 15 minutes.</p>
              <label className="text-xs font-semibold text-muted">Name<input className={field} value={member.name} onChange={(event) => setMember({ ...member, name: event.target.value })} /></label>
              <label className="text-xs font-semibold text-muted">Email<input className={field} value={member.email} onChange={(event) => setMember({ ...member, email: event.target.value })} /></label>
              <label className="text-xs font-semibold text-muted">
                Organization role
                <select className={field} value={member.orgRole} onChange={(event) => setMember({ ...member, orgRole: event.target.value })}>
                  <option value="member">Member</option>
                  {actorRank > rankOf("org_admin") && <option value="org_admin">Organization admin · level 8</option>}
                </select>
              </label>
              {member.orgRole === "member" && (
                <>
                  <label className="text-xs font-semibold text-muted">
                    Project
                    <select className={field} value={member.projectId} onChange={(event) => setMember({ ...member, projectId: event.target.value })}>
                      <option value="">Choose</option>
                      {data.projects.map((item) => (
                        <option key={item.id} value={item.id}>{item.name}</option>
                      ))}
                    </select>
                  </label>
                  <label className="text-xs font-semibold text-muted">
                    Project role
                    <select className={field} value={member.projectRole} onChange={(event) => setMember({ ...member, projectRole: event.target.value })}>
                      {LADDER.filter((role) => role.rank < actorRank).map((role) => (
                        <option key={role.key} value={role.key}>{role.label} · level {levelOf(role.rank)}</option>
                      ))}
                      {(data.roles || []).filter((item) => Number(item.rank) < actorRank).map((item) => (
                        <option key={item.id} value={item.id}>{item.name} · level {levelOf(item.rank)}</option>
                      ))}
                    </select>
                    <span className="mt-1 block font-normal">{rolePower(member.projectRole) || "A custom role can open only the modules you selected. It sits below your level."}</span>
                  </label>
                </>
              )}
              <button className="h-11 rounded-2xl bg-brand px-4 text-sm font-semibold text-white md:col-span-2" type="submit">Send invite</button>
            </form>
            {inviteLink && (
              <div className="mt-3 rounded-xl border border-line bg-canvas px-3 py-2 text-sm">
                <p className="font-semibold">Invite link</p>
                <p className="mt-1 break-all text-xs text-muted">{inviteLink}</p>
              </div>
            )}
            <ul className="mt-4 space-y-2 text-sm">
              {(data.members || []).map((item) => (
                <li key={item.id} className="flex items-center justify-between gap-3 rounded-xl border border-line px-3 py-2">
                  <span>
                    <span className="font-semibold">{item.name}</span>
                    <span className="block text-xs text-muted">{item.email} · {labelFor(item.role)} · {item.status === "suspended" ? "Suspended" : "Active"}{item.projects?.[0] ? ` · ${item.projects.map((entry) => `${entry.name} (${labelFor(entry.role)})`).join(", ")}` : ""}</span>
                  </span>
                  {item.id !== data.user.id && personRank(item) < actorRank && (
                    <button
                      type="button"
                      className="text-xs font-semibold text-brand"
                      onClick={async () => {
                        const saved = await submit("/api/members", { userId: item.id, status: item.status === "suspended" ? "active" : "suspended" }, "PATCH");
                        if (saved.ok) notify(item.status === "suspended" ? "Member activated." : "Member suspended.", "ok");
                      }}
                    >
                      {item.status === "suspended" ? "Activate" : "Suspend"}
                    </button>
                  )}
                  {item.id !== data.user.id && personRank(item) < actorRank && (
                    <button
                      type="button"
                      className="text-xs font-semibold text-danger"
                      onClick={async () => {
                        startBusy("Removing the member…");
                        const res = await fetch(`/api/members?userId=${item.id}`, { method: "DELETE" });
                        stopBusy();
                        if (!res.ok) {
                          const body = await res.json().catch(() => ({}));
                          notify(body.message || "Could not remove that member.", "error");
                          return;
                        }
                        notify("Member removed.", "ok");
                        load();
                      }}
                    >
                      Remove
                    </button>
                  )}
                </li>
              ))}
            </ul>
            {(data.invites || []).length > 0 && (
              <div className="mt-4 space-y-2">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Pending invites</h3>
                {data.invites.map((item) => (
                  <div key={item.id} className="rounded-xl border border-line px-3 py-2 text-sm">
                    <span className="font-semibold">{item.name || item.email}</span>
                    <span className="block text-xs text-muted">{item.email} · {item.orgRole === "org_admin" ? "Organization admin" : labelFor(item.projectRole)}{item.projectName ? ` · ${item.projectName}` : ""} · expires {new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }).format(new Date(item.expiresAt))} UTC</span>
                  </div>
                ))}
              </div>
            )}
          </Panel>
      )}
      {data.canManage && tab === "roles" && (
        <Panel title="Roles">
          <p className="mb-3 text-sm text-muted">The ladder runs from the bottom up. A person can assign only roles below their own level. A custom role opens the modules you tick and sits on the level you choose.</p>
          <ul className="space-y-2 text-sm">
            {LADDER.map((role) => (
              <li key={role.key} className="rounded-xl border border-line px-3 py-2">
                <span className="font-semibold">Level {levelOf(role.rank)} · {role.label}</span>
                <span className="mt-1 block text-xs text-muted">{role.power}</span>
                <span className="mt-1 block text-xs text-muted">{permissionsFor(role.key).map(moduleLabel).join(" · ")}</span>
              </li>
            ))}
            <li className="rounded-xl border border-line px-3 py-2">
              <span className="font-semibold">Level 8 · Organization admin</span>
              <span className="mt-1 block text-xs text-muted">Create projects, map each project&apos;s connection, and invite people below this level.</span>
            </li>
            <li className="rounded-xl border border-line px-3 py-2">
              <span className="font-semibold">Level 10 · Organization owner</span>
              <span className="mt-1 block text-xs text-muted">Everything an admin can do, including inviting another admin.</span>
            </li>
          </ul>
          <form
            className="mt-4 space-y-3"
            onSubmit={async (event) => {
              event.preventDefault();
              const saved = await submit("/api/org/roles", { name: roleName, permissions: rolePermissions, rank: Number(roleRank) });
              if (saved.ok) {
                setRoleName("");
                setRoleRank(10);
                setRolePermissions(["module.dashboard"]);
                notify("Role created.", "ok");
              }
            }}
          >
            <div className="grid gap-3 md:grid-cols-2">
              <label className="text-xs font-semibold text-muted">Custom role name<input className={field} value={roleName} onChange={(event) => setRoleName(event.target.value)} /></label>
              <label className="text-xs font-semibold text-muted">
                Hierarchy level
                <select className={field} value={roleRank} onChange={(event) => setRoleRank(Number(event.target.value))}>
                  {LADDER.filter((role) => role.rank < actorRank).map((role) => (
                    <option key={role.rank} value={role.rank}>Level {levelOf(role.rank)} · same power band as {role.label}</option>
                  ))}
                </select>
              </label>
            </div>
            {["Estate", "Agentic"].map((group) => (
              <div key={group}>
                <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">{group}</div>
                <div className="grid gap-2 md:grid-cols-2">
                  {MODULES.filter((item) => item[2] === group).map(([key, label]) => (
                    <label key={key} className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={rolePermissions.includes(key)}
                        onChange={(event) => {
                          setRolePermissions((current) => event.target.checked ? [...current, key] : current.filter((item) => item !== key));
                        }}
                      />
                      {label}
                    </label>
                  ))}
                </div>
              </div>
            ))}
            <button className="h-11 rounded-2xl bg-brand px-4 text-sm font-semibold text-white" type="submit">Create role</button>
          </form>
          <ul className="mt-4 space-y-2 text-sm">
            {(data.roles || []).map((item) => (
              <li key={item.id} className="flex items-center justify-between gap-3 rounded-xl border border-line px-3 py-2">
                <span>
                  <span className="font-semibold">Level {levelOf(item.rank)} · {item.name}</span>
                  <span className="block text-xs text-muted">{(item.permissions || []).map(moduleLabel).join(" · ")}</span>
                </span>
                <button
                  type="button"
                  className="text-xs font-semibold text-danger"
                  onClick={async () => {
                    const saved = await submit(`/api/org/roles?id=${item.id}`, {}, "DELETE");
                    if (saved.ok) notify("Role removed.", "ok");
                  }}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        </Panel>
      )}
      {data.canManage && canSuite && tab === "suite" && (
        <SuiteGate>
          <SuiteSettingsBody />
        </SuiteGate>
      )}
    </div>
  );
}
