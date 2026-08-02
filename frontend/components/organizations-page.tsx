"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { fetchCurrentUser, getStoredUser } from "../lib/auth";
import { Shell } from "./shell";

type Org = {
  id: string;
  name: string;
  slug: string;
  member_count?: number;
  project_count?: number;
};

type Invite = {
  id: string;
  email: string;
  invited_role: string;
  status: string;
  created_at?: string;
};

type MemberRequest = {
  id: string;
  project_name: string;
  action: string;
  target_email: string;
  target_user_id: string;
  project_role: string;
  requester_name: string;
  status: string;
  reason?: string;
};

type OrgMember = {
  org_role: string;
  user: {
    id: string;
    username: string;
    email?: string;
    name: string;
    role: string;
    role_label?: string;
  };
};

type ProjectRow = { id: string; name: string; repos?: string[] };

type ProjectMember = {
  membership_id: string;
  project_role: string;
  user: { id: string; username: string; email?: string; name: string };
};

type Me = {
  id?: string;
  role?: string;
  role_label?: string;
  display_role?: string;
  org_role?: string | null;
  primary_org_id?: string;
};

type ExecutorStatus = {
  org_id: string;
  mode: "on_demand" | "window" | "schedule" | string;
  window_hours: number;
  window_ends_at?: string | null;
  schedule?: {
    timezone?: string;
    weekly?: Array<{ days: number[]; start: string; end: string }>;
  };
  idle_scale_down_minutes: number;
  max_replicas: number;
  desired_state: string;
  actual_state: string;
  last_job_at?: string | null;
  last_error?: string;
  in_warm_window?: boolean;
  queue_depth?: number;
  message?: string;
};

const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const ROLE_LABELS: Record<string, string> = {
  super_admin: "Super Admin",
  org_admin: "Org Admin",
  devops_lead: "DevOps Lead",
  devops_engineer: "DevOps Engineer",
  developer: "Developer",
  viewer: "Viewer",
  member: "Member",
};

function labelRole(role?: string | null) {
  if (!role) return "—";
  return ROLE_LABELS[role] || role;
}

export function OrganizationsPage() {
  const [me, setMe] = useState<Me | null>(getStoredUser() as Me | null);
  const isSuper = me?.role === "super_admin" || me?.display_role === "super_admin";
  const isOrgAdmin =
    isSuper ||
    me?.display_role === "org_admin" ||
    me?.org_role === "org_admin" ||
    me?.role === "org_admin";

  const [orgs, setOrgs] = useState<Org[]>([]);
  const [selectedOrg, setSelectedOrg] = useState("");
  const [tab, setTab] = useState<
    "overview" | "invites" | "requests" | "projects" | "admins" | "executors"
  >("overview");
  const [message, setMessage] = useState("");
  const [newOrgName, setNewOrgName] = useState("");
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("developer");
  const [invites, setInvites] = useState<Invite[]>([]);
  const [requests, setRequests] = useState<MemberRequest[]>([]);
  const [members, setMembers] = useState<OrgMember[]>([]);
  const [orgProjects, setOrgProjects] = useState<ProjectRow[]>([]);
  const [projectId, setProjectId] = useState("");
  const [projectMembers, setProjectMembers] = useState<ProjectMember[]>([]);
  const [memberEmail, setMemberEmail] = useState("");
  const [memberRole, setMemberRole] = useState("developer");
  const [executor, setExecutor] = useState<ExecutorStatus | null>(null);
  const [execMode, setExecMode] = useState<"on_demand" | "window" | "schedule">(
    "on_demand",
  );
  const [windowHours, setWindowHours] = useState(12);
  const [maxReplicas, setMaxReplicas] = useState(1);
  const [idleMinutes, setIdleMinutes] = useState(15);
  const [scheduleTz, setScheduleTz] = useState("UTC");
  const [scheduleDays, setScheduleDays] = useState<number[]>([0, 1, 2, 3, 4]);
  const [scheduleStart, setScheduleStart] = useState("09:00");
  const [scheduleEnd, setScheduleEnd] = useState("18:00");
  const [executorSaving, setExecutorSaving] = useState(false);

  useEffect(() => {
    void fetchCurrentUser().then((u) => {
      if (u) setMe(u as Me);
    });
  }, []);

  const loadOrgs = useCallback(async () => {
    try {
      const list = await api<Org[]>("/api/orgs");
      setOrgs(list);
      if (!selectedOrg && list.length) {
        const preferred =
          list.find((o) => o.id === me?.primary_org_id)?.id || list[0].id;
        setSelectedOrg(preferred);
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not load orgs");
    }
  }, [me?.primary_org_id, selectedOrg]);

  const loadExecutor = useCallback(async () => {
    if (!selectedOrg) {
      setExecutor(null);
      return;
    }
    try {
      const status = await api<ExecutorStatus>(
        `/api/orgs/${selectedOrg}/executor-status`,
      );
      setExecutor(status);
      const mode = (status.mode || "on_demand") as
        | "on_demand"
        | "window"
        | "schedule";
      setExecMode(mode);
      setWindowHours(status.window_hours || 12);
      setMaxReplicas(status.max_replicas || 1);
      setIdleMinutes(status.idle_scale_down_minutes || 15);
      const weekly = status.schedule?.weekly?.[0];
      setScheduleTz(status.schedule?.timezone || "UTC");
      if (weekly) {
        setScheduleDays(weekly.days || [0, 1, 2, 3, 4]);
        setScheduleStart(weekly.start || "09:00");
        setScheduleEnd(weekly.end || "18:00");
      }
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Could not load executor status",
      );
    }
  }, [selectedOrg]);

  const loadOrgDetail = useCallback(async () => {
    if (!selectedOrg) return;
    try {
      const [memberList, projectList] = await Promise.all([
        api<OrgMember[]>(`/api/orgs/${selectedOrg}/members`),
        api<ProjectRow[]>(`/api/orgs/${selectedOrg}/projects`),
      ]);
      setMembers(memberList);
      setOrgProjects(projectList);
      if (projectList.length && !projectList.some((p) => p.id === projectId)) {
        setProjectId(projectList[0].id);
      }
      if (isOrgAdmin) {
        const [inviteList, requestList] = await Promise.all([
          api<Invite[]>(`/api/orgs/${selectedOrg}/invites`),
          api<MemberRequest[]>(
            `/api/orgs/${selectedOrg}/member-requests?status=pending`,
          ),
        ]);
        setInvites(inviteList);
        setRequests(requestList);
      }
      await loadExecutor();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not load org detail");
    }
  }, [selectedOrg, isOrgAdmin, projectId, loadExecutor]);

  const loadProjectMembers = useCallback(async () => {
    if (!projectId) {
      setProjectMembers([]);
      return;
    }
    try {
      setProjectMembers(
        await api<ProjectMember[]>(`/api/projects/${projectId}/members`),
      );
    } catch {
      setProjectMembers([]);
    }
  }, [projectId]);

  useEffect(() => {
    void loadOrgs();
  }, [loadOrgs]);

  useEffect(() => {
    void loadOrgDetail();
  }, [loadOrgDetail]);

  useEffect(() => {
    void loadProjectMembers();
  }, [loadProjectMembers]);

  const saveExecutorSettings = async () => {
    if (!selectedOrg) return;
    setExecutorSaving(true);
    setMessage("Saving executor capacity…");
    try {
      const body: Record<string, unknown> = {
        mode: execMode,
        window_hours: windowHours,
        idle_scale_down_minutes: idleMinutes,
        max_replicas: maxReplicas,
        refresh_window: execMode === "window",
      };
      if (execMode === "schedule") {
        body.schedule = {
          timezone: scheduleTz || "UTC",
          weekly: [
            {
              days: scheduleDays,
              start: scheduleStart,
              end: scheduleEnd,
            },
          ],
        };
      }
      const status = await api<ExecutorStatus>(
        `/api/orgs/${selectedOrg}/executor-settings`,
        { method: "PUT", body: JSON.stringify(body) },
      );
      setExecutor(status);
      setMessage("Executor capacity updated.");
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Could not save executor settings",
      );
    } finally {
      setExecutorSaving(false);
    }
  };

  const wakeExecutors = async () => {
    if (!selectedOrg) return;
    setMessage("Waking executor pool…");
    try {
      const status = await api<ExecutorStatus>(
        `/api/orgs/${selectedOrg}/executor-wake`,
        { method: "POST", body: "{}" },
      );
      setExecutor(status);
      setMessage(status.message || "Wake requested.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Wake failed");
    }
  };

  const toggleScheduleDay = (day: number) => {
    setScheduleDays((prev) =>
      prev.includes(day) ? prev.filter((d) => d !== day) : [...prev, day].sort(),
    );
  };

  const createOrg = async (event: React.FormEvent) => {
    event.preventDefault();
    setMessage("Creating organization…");
    try {
      await api("/api/orgs", {
        method: "POST",
        body: JSON.stringify({ name: newOrgName }),
      });
      setNewOrgName("");
      setMessage("Organization created.");
      setSelectedOrg("");
      await loadOrgs();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Create org failed");
    }
  };

  const sendInvite = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!selectedOrg) return;
    setMessage("Sending invite…");
    try {
      const result = await api<{
        email_sent?: boolean;
        accept_token?: string;
        accept_url?: string;
        smtp_error?: string;
      }>(`/api/orgs/${selectedOrg}/invites`, {
        method: "POST",
        body: JSON.stringify({
          email: inviteEmail,
          invited_role: inviteRole,
          org_role: inviteRole === "org_admin" ? "org_admin" : "member",
        }),
      });
      setInviteEmail("");
      setMessage(
        result.email_sent
          ? "Invite emailed."
          : result.accept_url
            ? `Email not sent (SMTP unreachable). Share this link: ${result.accept_url}`
            : "Invite created.",
      );
      await loadOrgDetail();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Invite failed");
    }
  };

  const decideRequest = async (id: string, decision: "approved" | "rejected") => {
    setMessage("Saving…");
    try {
      await api(`/api/member-requests/${id}/decide`, {
        method: "POST",
        body: JSON.stringify({ decision }),
      });
      setMessage(decision === "approved" ? "Approved." : "Rejected.");
      await loadOrgDetail();
      await loadProjectMembers();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Decision failed");
    }
  };

  const proposeMember = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!projectId) return;
    setMessage("Submitting member request…");
    try {
      const result = await api<{ requires_approval?: boolean }>(
        `/api/projects/${projectId}/member-requests`,
        {
          method: "POST",
          body: JSON.stringify({
            action: "add",
            target_email: memberEmail,
            project_role: memberRole,
          }),
        },
      );
      setMemberEmail("");
      setMessage(
        result.requires_approval
          ? "Submitted — waiting for Org Admin approval."
          : "Member change applied.",
      );
      await loadOrgDetail();
      await loadProjectMembers();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Request failed");
    }
  };

  const selected = orgs.find((o) => o.id === selectedOrg);
  const admins = members.filter((m) => m.org_role === "org_admin");

  return (
    <Shell subtitle="Organizations" scroll>
      <main className="org-layout">
        <aside className="org-sidebar card">
          <div className="card-head">
            <h3>Organizations</h3>
            <span className="pill ok">{orgs.length}</span>
          </div>
          {isSuper && (
            <form className="org-create" onSubmit={(e) => void createOrg(e)}>
              <input
                placeholder="New organization name"
                value={newOrgName}
                onChange={(e) => setNewOrgName(e.target.value)}
                required
              />
              <button type="submit" className="tiny-btn solid">
                Create
              </button>
            </form>
          )}
          <div className="org-list">
            {orgs.map((org) => (
              <button
                key={org.id}
                type="button"
                className={`org-list-item${selectedOrg === org.id ? " active" : ""}`}
                onClick={() => {
                  setSelectedOrg(org.id);
                  setTab("overview");
                }}
              >
                <strong>{org.name}</strong>
                <span>
                  {org.member_count || 0} users · {org.project_count || 0} projects
                </span>
              </button>
            ))}
            {!orgs.length && <p className="empty-note">No organizations yet.</p>}
          </div>
        </aside>

        <section className="org-main card">
          {!selectedOrg || !selected ? (
            <p className="empty-note">Select an organization to manage it.</p>
          ) : (
            <>
              <div className="org-main-head">
                <div>
                  <p className="modal-eyebrow">Organization</p>
                  <h2>{selected.name}</h2>
                  <p className="page-sub">
                    Your access: <strong>{labelRole(me?.display_role || me?.org_role || me?.role)}</strong>
                    {me?.role && me?.org_role && me.role !== me.org_role ? (
                      <>
                        {" "}
                        · platform role {labelRole(me.role)} · org role{" "}
                        {labelRole(me.org_role)}
                      </>
                    ) : null}
                  </p>
                </div>
                <div className="org-tabs">
                  {(
                    [
                      "overview",
                      "invites",
                      "requests",
                      "projects",
                      "admins",
                      "executors",
                    ] as const
                  ).map((t) => (
                    <button
                      key={t}
                      type="button"
                      className={`org-tab${tab === t ? " active" : ""}`}
                      onClick={() => setTab(t)}
                    >
                      {t === "admins"
                        ? "Admins"
                        : t === "executors"
                          ? "Executor capacity"
                          : t}
                    </button>
                  ))}
                </div>
              </div>

              {tab === "overview" && (
                <div className="org-panel">
                  <div className="org-stat-row">
                    <div className="org-stat">
                      <span>Members</span>
                      <strong>{members.length}</strong>
                    </div>
                    <div className="org-stat">
                      <span>Projects</span>
                      <strong>{orgProjects.length}</strong>
                    </div>
                    <div className="org-stat">
                      <span>Pending requests</span>
                      <strong>{requests.length}</strong>
                    </div>
                    <div className="org-stat">
                      <span>Org admins</span>
                      <strong>{admins.length}</strong>
                    </div>
                  </div>
                  <h4>People in this org</h4>
                  <div className="org-table">
                    {members.map((m) => (
                      <div key={m.user.id} className="org-row">
                        <div>
                          <strong>{m.user.name}</strong>
                          <span>
                            {m.user.email || m.user.username}
                          </span>
                        </div>
                        <span className="pill off">{labelRole(m.org_role)} (org)</span>
                        <span className="pill ok">
                          {labelRole(m.user.role)} (platform)
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {tab === "invites" && (
                <div className="org-panel">
                  {!isOrgAdmin ? (
                    <p className="empty-note">Org Admin required to invite users.</p>
                  ) : (
                    <>
                      <form className="org-create" onSubmit={(e) => void sendInvite(e)}>
                        <input
                          type="email"
                          placeholder="user@company.com"
                          value={inviteEmail}
                          onChange={(e) => setInviteEmail(e.target.value)}
                          required
                        />
                        <select
                          value={inviteRole}
                          onChange={(e) => setInviteRole(e.target.value)}
                        >
                          <option value="org_admin">Org Admin</option>
                          <option value="devops_lead">DevOps Lead</option>
                          <option value="devops_engineer">DevOps Engineer</option>
                          <option value="developer">Developer</option>
                          <option value="viewer">Viewer</option>
                        </select>
                        <button type="submit" className="tiny-btn solid">
                          Invite by email
                        </button>
                      </form>
                      <div className="org-table">
                        {invites.map((inv) => (
                          <div key={inv.id} className="org-row">
                            <strong>{inv.email}</strong>
                            <span className="pill off">{labelRole(inv.invited_role)}</span>
                            <span
                              className={`pill ${inv.status === "pending" ? "warn" : "ok"}`}
                            >
                              {inv.status}
                            </span>
                          </div>
                        ))}
                        {!invites.length && (
                          <p className="empty-note">No invites yet.</p>
                        )}
                      </div>
                    </>
                  )}
                </div>
              )}

              {tab === "requests" && (
                <div className="org-panel">
                  {!isOrgAdmin ? (
                    <p className="empty-note">Org Admin required to approve member requests.</p>
                  ) : !requests.length ? (
                    <p className="empty-note">No pending membership requests.</p>
                  ) : (
                    <div className="org-table">
                      {requests.map((req) => (
                        <div key={req.id} className="org-row">
                          <div>
                            <strong>
                              {req.action} {req.target_email || req.target_user_id}
                            </strong>
                            <span>
                              {req.project_name} · by {req.requester_name} ·{" "}
                              {labelRole(req.project_role)}
                            </span>
                          </div>
                          <button
                            type="button"
                            className="tiny-btn solid"
                            onClick={() => void decideRequest(req.id, "approved")}
                          >
                            Approve
                          </button>
                          <button
                            type="button"
                            className="tiny-btn danger"
                            onClick={() => void decideRequest(req.id, "rejected")}
                          >
                            Reject
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {tab === "projects" && (
                <div className="org-panel org-projects">
                  <div className="org-project-list">
                    <h4>Projects</h4>
                    {orgProjects.map((p) => (
                      <button
                        key={p.id}
                        type="button"
                        className={`org-list-item${projectId === p.id ? " active" : ""}`}
                        onClick={() => setProjectId(p.id)}
                      >
                        <strong>{p.name}</strong>
                        <span>{(p.repos || []).length} repos</span>
                      </button>
                    ))}
                    {!orgProjects.length && (
                      <p className="empty-note">No projects in this org yet.</p>
                    )}
                  </div>
                  {projectId && (
                    <div className="org-project-detail">
                      <h4>Project members</h4>
                      <div className="org-table">
                        {projectMembers.map((m) => (
                          <div key={m.membership_id} className="org-row">
                            <strong>{m.user.name}</strong>
                            <span className="pill off">{labelRole(m.project_role)}</span>
                          </div>
                        ))}
                      </div>
                      <form className="org-create" onSubmit={(e) => void proposeMember(e)}>
                        <input
                          type="email"
                          placeholder="Add member by email"
                          value={memberEmail}
                          onChange={(e) => setMemberEmail(e.target.value)}
                          required
                        />
                        <select
                          value={memberRole}
                          onChange={(e) => setMemberRole(e.target.value)}
                        >
                          <option value="devops_lead">DevOps Lead</option>
                          <option value="devops_engineer">DevOps Engineer</option>
                          <option value="developer">Developer</option>
                          <option value="viewer">Viewer</option>
                        </select>
                        <button type="submit" className="tiny-btn solid">
                          {isOrgAdmin ? "Add member" : "Request add"}
                        </button>
                      </form>
                      {!isOrgAdmin && (
                        <p className="empty-note">
                          DevOps Lead requests need Org Admin approval.
                        </p>
                      )}
                    </div>
                  )}
                </div>
              )}

              {tab === "admins" && (
                <div className="org-panel">
                  <p className="empty-note">
                    Org Admins manage invites, projects, and Lead member requests for this
                    organization only. Super Admin can create orgs globally.
                  </p>
                  <div className="org-table">
                    {admins.map((m) => (
                      <div key={m.user.id} className="org-row">
                        <div>
                          <strong>{m.user.name}</strong>
                          <span>{m.user.email || m.user.username}</span>
                        </div>
                        <span className="pill ok">Org Admin</span>
                      </div>
                    ))}
                    {!admins.length && (
                      <p className="empty-note">No org admins assigned.</p>
                    )}
                  </div>
                </div>
              )}

              {tab === "executors" && (
                <div className="org-panel executor-panel">
                  <div className="executor-status-row">
                    <div>
                      <p className="modal-eyebrow">CLI executor pool</p>
                      <h4>Azure · AWS · GitHub workers for this org</h4>
                      <p className="page-sub">
                        Shared by every project in the org. Chat stays always-on; only CLI
                        executors scale.
                      </p>
                    </div>
                    <div className="executor-pills">
                      <span
                        className={`pill ${
                          executor?.actual_state === "active"
                            ? "ok"
                            : executor?.actual_state === "error"
                              ? "warn"
                              : "off"
                        }`}
                      >
                        {(executor?.actual_state || "unknown").replace(/_/g, " ")}
                      </span>
                      {executor?.in_warm_window ? (
                        <span className="pill ok">warm window</span>
                      ) : null}
                    </div>
                  </div>

                  <div className="org-stat-row">
                    <div className="org-stat">
                      <span>Queue depth</span>
                      <strong>{executor?.queue_depth ?? 0}</strong>
                    </div>
                    <div className="org-stat">
                      <span>Mode</span>
                      <strong>{(executor?.mode || "—").replace(/_/g, " ")}</strong>
                    </div>
                    <div className="org-stat">
                      <span>Window ends</span>
                      <strong>
                        {executor?.window_ends_at
                          ? new Date(executor.window_ends_at).toLocaleString()
                          : "—"}
                      </strong>
                    </div>
                    <div className="org-stat">
                      <span>Last job</span>
                      <strong>
                        {executor?.last_job_at
                          ? new Date(executor.last_job_at).toLocaleString()
                          : "—"}
                      </strong>
                    </div>
                  </div>

                  {executor?.message ? (
                    <p className="executor-message">{executor.message}</p>
                  ) : null}
                  {executor?.last_error ? (
                    <p className="executor-error">{executor.last_error}</p>
                  ) : null}

                  {!isOrgAdmin ? (
                    <p className="empty-note">
                      Org Admin required to change executor capacity.
                    </p>
                  ) : (
                    <>
                      <div className="executor-mode-tabs">
                        {(
                          [
                            ["on_demand", "On demand"],
                            ["window", "Timed window"],
                            ["schedule", "Custom schedule"],
                          ] as const
                        ).map(([value, label]) => (
                          <button
                            key={value}
                            type="button"
                            className={`org-tab${execMode === value ? " active" : ""}`}
                            onClick={() => setExecMode(value)}
                          >
                            {label}
                          </button>
                        ))}
                      </div>

                      {execMode === "window" && (
                        <div className="executor-window-tabs">
                          {[6, 12, 24].map((hours) => (
                            <button
                              key={hours}
                              type="button"
                              className={`tiny-btn${windowHours === hours ? " solid" : ""}`}
                              onClick={() => setWindowHours(hours)}
                            >
                              {hours}h
                            </button>
                          ))}
                          <p className="empty-note">
                            Keep executors warm for the next {windowHours} hours from save.
                          </p>
                        </div>
                      )}

                      {execMode === "on_demand" && (
                        <label className="executor-field">
                          Idle scale-down (minutes)
                          <input
                            type="number"
                            min={1}
                            max={1440}
                            value={idleMinutes}
                            onChange={(e) =>
                              setIdleMinutes(Number(e.target.value) || 15)
                            }
                          />
                        </label>
                      )}

                      {execMode === "schedule" && (
                        <div className="executor-schedule">
                          <label className="executor-field">
                            Timezone
                            <input
                              value={scheduleTz}
                              onChange={(e) => setScheduleTz(e.target.value)}
                              placeholder="UTC"
                            />
                          </label>
                          <div className="executor-days">
                            {WEEKDAY_LABELS.map((label, index) => (
                              <button
                                key={label}
                                type="button"
                                className={`tiny-btn${
                                  scheduleDays.includes(index) ? " solid" : ""
                                }`}
                                onClick={() => toggleScheduleDay(index)}
                              >
                                {label}
                              </button>
                            ))}
                          </div>
                          <div className="executor-time-row">
                            <label className="executor-field">
                              Start
                              <input
                                type="time"
                                value={scheduleStart}
                                onChange={(e) => setScheduleStart(e.target.value)}
                              />
                            </label>
                            <label className="executor-field">
                              End
                              <input
                                type="time"
                                value={scheduleEnd}
                                onChange={(e) => setScheduleEnd(e.target.value)}
                              />
                            </label>
                          </div>
                          <p className="empty-note">
                            Outside the schedule the pool stays scaled to zero.
                          </p>
                        </div>
                      )}

                      <label className="executor-field">
                        Max replicas per provider
                        <input
                          type="range"
                          min={1}
                          max={5}
                          value={maxReplicas}
                          onChange={(e) => setMaxReplicas(Number(e.target.value) || 1)}
                        />
                        <span>{maxReplicas}</span>
                      </label>

                      <div className="executor-actions">
                        <button
                          type="button"
                          className="tiny-btn solid"
                          disabled={executorSaving}
                          onClick={() => void saveExecutorSettings()}
                        >
                          {executorSaving ? "Saving…" : "Save capacity"}
                        </button>
                        <button
                          type="button"
                          className="tiny-btn"
                          onClick={() => void wakeExecutors()}
                        >
                          Wake now
                        </button>
                        <button
                          type="button"
                          className="tiny-btn"
                          onClick={() => void loadExecutor()}
                        >
                          Refresh status
                        </button>
                      </div>
                    </>
                  )}
                </div>
              )}
            </>
          )}
          {message && <div className="form-msg">{message}</div>}
        </section>
      </main>
    </Shell>
  );
}
