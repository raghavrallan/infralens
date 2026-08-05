"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { fetchCurrentUser, getStoredUser } from "../lib/auth";
import { Shell } from "./shell";
import { Modal } from "./modal";

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
  const [orgPage, setOrgPage] = useState(1);
  const ORGS_PER_PAGE = 10;
  const paginatedOrgs = orgs.slice((orgPage - 1) * ORGS_PER_PAGE, orgPage * ORGS_PER_PAGE);
  const totalOrgPages = Math.ceil(orgs.length / ORGS_PER_PAGE);
  const [selectedOrg, setSelectedOrg] = useState("");
  const [tab, setTab] = useState<
    "overview" | "invites" | "requests" | "projects" | "admins" | "executors"
  >("overview");
  const [message, setMessage] = useState("");
  const [showCreateOrg, setShowCreateOrg] = useState(false);
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
    setShowCreateOrg(false);
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
    <Shell subtitle="Organizations">
      <main className="org-layout">
        <aside className="org-sidebar card">
          <div className="org-sidebar-header">
            <h3>Organizations</h3>
            <span className="pill ok-badge">{orgs.length}</span>
          </div>
          <div className="search-bar sidebar-search">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
            <input type="text" placeholder="Search organizations..." />
          </div>
          {isSuper && (
            <button type="button" className="create-org-btn primary-btn-full" onClick={() => setShowCreateOrg(true)}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
              Create organization
            </button>
          )}
          <div className="org-list">
            {paginatedOrgs.map((org) => (
              <button
                key={org.id}
                type="button"
                className={`org-list-item${selectedOrg === org.id ? " active" : ""}`}
                onClick={() => {
                  setSelectedOrg(org.id);
                  setTab("overview");
                }}
              >
                <div className={`org-icon ${selectedOrg === org.id ? 'blue' : 'green'}`}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="2" width="16" height="20" rx="2" ry="2"></rect><path d="M9 22v-4h6v4"></path><path d="M8 6h.01"></path><path d="M16 6h.01"></path><path d="M12 6h.01"></path><path d="M12 10h.01"></path><path d="M12 14h.01"></path><path d="M16 10h.01"></path><path d="M16 14h.01"></path><path d="M8 10h.01"></path><path d="M8 14h.01"></path></svg>
                </div>
                <div className="org-info">
                  <strong>{org.name}</strong>
                  <span>
                    {org.member_count || 0} user{org.member_count !== 1 ? 's' : ''} · {org.project_count || 0} project{org.project_count !== 1 ? 's' : ''}
                  </span>
                </div>
                <div className={`org-status-dot ${selectedOrg === org.id ? 'active' : 'inactive'}`}>
                  {selectedOrg === org.id ? 'Active' : 'Inactive'}
                </div>
              </button>
            ))}
            {!orgs.length && <p className="empty-note">No organizations yet.</p>}
            {orgs.length > ORGS_PER_PAGE && (
              <div className="org-sidebar-pagination">
                <button 
                  className="icon-btn-nav" 
                  disabled={orgPage === 1}
                  onClick={() => setOrgPage(p => Math.max(1, p - 1))}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="15 18 9 12 15 6"></polyline></svg>
                </button>
                <span className="page-info">{orgPage} / {totalOrgPages}</span>
                <button 
                  className="icon-btn-nav"
                  disabled={orgPage >= totalOrgPages}
                  onClick={() => setOrgPage(p => p + 1)}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="9 18 15 12 9 6"></polyline></svg>
                </button>
              </div>
            )}
          </div>
          
        </aside>

        <section className="org-main card">
          {!selectedOrg || !selected ? (
            <p className="empty-note">Select an organization to manage it.</p>
          ) : (
            <>
              <div className="org-main-head">
                <div className="org-main-title">
                  <p className="modal-eyebrow">ORGANIZATION</p>
                  <div className="org-title-row">
                    <h2>{selected.name}</h2>
                    <span className="pill active-pill">Active</span>
                  </div>
                  <div className="org-roles-row">
                    <div className="role-item">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>
                      Your access: <strong>{labelRole(me?.display_role || me?.org_role || me?.role)}</strong>
                    </div>
                    {me?.role && me?.org_role && me.role !== me.org_role ? (
                      <>
                        <div className="role-divider"></div>
                        <div className="role-item">
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect><line x1="8" y1="21" x2="16" y2="21"></line><line x1="12" y1="17" x2="12" y2="21"></line></svg>
                          Platform role: <strong>{labelRole(me.role)}</strong>
                        </div>
                        <div className="role-divider"></div>
                        <div className="role-item">
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="4" y="2" width="16" height="20" rx="2" ry="2"></rect><path d="M9 22v-4h6v4"></path><path d="M8 6h.01"></path><path d="M16 6h.01"></path><path d="M12 6h.01"></path><path d="M12 10h.01"></path><path d="M12 14h.01"></path><path d="M16 10h.01"></path><path d="M16 14h.01"></path><path d="M8 10h.01"></path><path d="M8 14h.01"></path></svg>
                          Org role: <strong>{labelRole(me.org_role)}</strong>
                        </div>
                      </>
                    ) : null}
                  </div>
                </div>
              </div>
              <div className="org-tabs-container">
                <div className="org-tabs">
                  {(
                    [
                      { id: "overview", label: "Overview", icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg> },
                      { id: "invites", label: "Invites", icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="8.5" cy="7" r="4"></circle><line x1="20" y1="8" x2="20" y2="14"></line><line x1="23" y1="11" x2="17" y2="11"></line></svg> },
                      { id: "requests", label: "Requests", icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg> },
                      { id: "projects", label: "Projects", icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg> },
                      { id: "admins", label: "Admins", icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg> },
                      { id: "executors", label: "Execution Capacity", icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M2 12h4l2-9 5 18 2-9h5"></path></svg> },
                    ] as const
                  ).map((t) => (
                    <button
                      key={t.id}
                      type="button"
                      className={`org-tab${tab === t.id ? " active" : ""}`}
                      onClick={() => setTab(t.id)}
                    >
                      {t.icon}
                      {t.label}
                    </button>
                  ))}
                </div>
              </div>

              {tab === "overview" && (
                <div className="org-panel ">
                  <div className="org-stat-row">
                    <div className="org-stat-card">
                      <div className="stat-header">
                        <div className="stat-content">
                          <span>Members</span>
                          <strong>{members.length}</strong>
                        </div>
                        <div className="stat-icon-wrapper bg-blue"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg></div>
                      </div>
                      <button className="stat-link" onClick={() => setTab("projects")}>View all members <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline></svg></button>
                    </div>
                    <div className="org-stat-card">
                      <div className="stat-header">
                        <div className="stat-content">
                          <span>Projects</span>
                          <strong>{orgProjects.length}</strong>
                        </div>
                        <div className="stat-icon-wrapper bg-green"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg></div>
                      </div>
                      <button className="stat-link" onClick={() => setTab("projects")}>View all projects <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline></svg></button>
                    </div>
                    <div className="org-stat-card">
                      <div className="stat-header">
                        <div className="stat-content">
                          <span>Pending requests</span>
                          <strong>{requests.length}</strong>
                        </div>
                        <div className="stat-icon-wrapper bg-orange"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg></div>
                      </div>
                      <button className="stat-link" onClick={() => setTab("requests")}>View requests <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline></svg></button>
                    </div>
                    <div className="org-stat-card">
                      <div className="stat-header">
                        <div className="stat-content">
                          <span>Org admins</span>
                          <strong>{admins.length}</strong>
                        </div>
                        <div className="stat-icon-wrapper bg-purple"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path><polyline points="9 22 9 12 15 12 15 22"></polyline></svg></div>
                      </div>
                      <button className="stat-link" onClick={() => setTab("admins")}>Manage admins <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline></svg></button>
                    </div>
                  </div>
                  <div className="org-table-container">
                    <div className="org-table-header">
                      <div>
                        <h4>People in this org</h4>
                        <span className="page-sub">Manage members and their roles</span>
                      </div>
                      <div className="org-table-actions">
                        <div className="search-bar table-search">
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
                          <input type="text" placeholder="Search members..." />
                        </div>
                        <div className="filter-dropdown">
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"></polygon></svg>
                          <span>All roles</span>
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="6 9 12 15 18 9"></polyline></svg>
                        </div>
                      </div>
                    </div>
                    <div className="org-table">
                      {members.map((m) => {
                        const initials = m.user.name.split(' ').map(n => n[0]).join('').substring(0,2).toUpperCase();
                        return (
                        <div key={m.user.id} className="org-row">
                          <div className="org-row-user">
                            <div className={`user-avatar ${m.org_role === 'org_admin' ? 'blue' : 'green'}`}>{initials}</div>
                            <div className="user-details">
                              <strong>{m.user.name}</strong>
                              <span>{m.user.email || m.user.username}</span>
                            </div>
                          </div>
                          <div className="org-row-roles">
                            <span className={`pill org-role-badge ${m.org_role === 'org_admin' ? 'org-admin' : 'org-member'}`}>{labelRole(m.org_role)} (org)</span>
                            <span className={`pill platform-role-badge ${m.user.role === 'super_admin' ? 'super-admin' : 'platform-dev'}`}>
                              {labelRole(m.user.role)} (platform)
                            </span>
                            <button className="icon-btn-dots">
                              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="1"></circle><circle cx="12" cy="5" r="1"></circle><circle cx="12" cy="19" r="1"></circle></svg>
                            </button>
                          </div>
                        </div>
                      )})}
                    </div>
                    <div className="org-table-pagination">
                      <span className="page-sub">Showing 1 to {members.length} of {members.length} member{members.length !== 1 ? 's' : ''}</span>
                      <div className="pagination-controls">
                        <div className="filter-dropdown limit-dropdown" style={{ marginRight: '8px' }}>
                          <span>10 per page</span>
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="6 9 12 15 18 9"></polyline></svg>
                        </div>
                        <button className="icon-btn-nav"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="15 18 9 12 15 6"></polyline></svg></button>
                        <button className="page-btn active">1</button>
                        <button className="icon-btn-nav"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="9 18 15 12 9 6"></polyline></svg></button>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {tab === "invites" && (
                <div className="org-panel">
                  {!isOrgAdmin ? (
                    <p className="empty-note">Org Admin required to invite users.</p>
                  ) : (
                    <>
                      <form className="invite-form-row" onSubmit={(e) => void sendInvite(e)}>
                        <div>
                          <h4>Invite new member</h4>
                          <span className="page-sub">Send an email invitation to join the organization</span>
                        </div>
                        <div className="invite-inputs">
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
                          <button type="submit" className="create-org-btn invite-btn">
                            Invite
                          </button>
                        </div>
                      </form>
                      <div className="org-table-container">
                        <div className="org-table-header">
                          <div>
                            <h4>Pending invites</h4>
                            <span className="page-sub">Users who havent accepted their invitations yet</span>
                          </div>
                        </div>
                        <div className="org-table">
                          {invites.map((inv) => {
                            const initials = inv.email.substring(0,2).toUpperCase();
                            return (
                            <div key={inv.id} className="org-row">
                              <div className="org-row-user">
                                <div className="user-avatar">{initials}</div>
                                <div className="user-details">
                                  <strong>{inv.email}</strong>
                                  <span>Invited as {labelRole(inv.invited_role)}</span>
                                </div>
                              </div>
                              <div className="org-row-roles">
                                <span className="pill off-badge">{labelRole(inv.invited_role)}</span>
                                <span className={`pill ${inv.status === "pending" ? "warn-badge" : "ok-badge-light"}`}>
                                  {inv.status}
                                </span>
                              </div>
                            </div>
                          )})}
                          {!invites.length && (
                            <div className="empty-note" style={{ padding: '2rem', textAlign: 'center' }}>No invites yet.</div>
                          )}
                        </div>
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
                <div className="org-panel org-projects" style={{ display: 'grid', gridTemplateColumns: 'minmax(250px, 280px) 1fr', gap: '1rem' }}>
                  <div className="org-project-list">
                    <h4>Projects</h4>
                    {orgProjects.map((p) => (
                      <button
                        key={p.id}
                        type="button"
                        className={`org-list-item${projectId === p.id ? " active" : ""}`}
                        onClick={() => setProjectId(p.id)}
                      >
                        <div className={`org-icon ${projectId === p.id ? 'blue' : 'green'}`}>
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>
                        </div>
                        <div className="org-info">
                          <strong>{p.name}</strong>
                          <span>{(p.repos || []).length} repos</span>
                        </div>
                      </button>
                    ))}
                    {!orgProjects.length && (
                      <p className="no-data">No projects in this organization.</p>
                    )}
                  </div>
                  {projectId && (
                    <div className="org-project-detail">
                      <div className="org-table-container" style={{ marginBottom: '2rem' }}>
                        <div className="org-table-header">
                          <div>
                            <h4>Project members</h4>
                            <span className="page-sub">People with access to this project</span>
                          </div>
                        </div>
                        <div className="org-table">
                          {projectMembers.map((m) => {
                            const initials = m.user.name.split(' ').map(n => n[0]).join('').substring(0,2).toUpperCase();
                            return (
                            <div key={m.membership_id} className="org-row">
                              <div className="org-row-user">
                                <div className="user-avatar">{initials}</div>
                                <div className="user-details">
                                  <strong>{m.user.name}</strong>
                                </div>
                              </div>
                              <div className="org-row-roles">
                                <span className="pill off-badge">{labelRole(m.project_role)}</span>
                              </div>
                            </div>
                          )})}
                        </div>
                      </div>
                      <form className="invite-form-row" onSubmit={(e) => void proposeMember(e)}>
                        <div>
                          <h4>Add member</h4>
                          <span className="page-sub">Add someone to this specific project</span>
                        </div>
                        <div className="invite-inputs">
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
                          <button type="submit" className="create-org-btn invite-btn">
                            {isOrgAdmin ? "Add member" : "Request add"}
                          </button>
                        </div>
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
                  <div className="org-table-container">
                    <div className="org-table-header">
                      <div>
                        <h4>Organization Admins</h4>
                        <span className="page-sub">Admins manage invites, projects, and execution capacity</span>
                      </div>
                    </div>
                    <div className="org-table">
                      {admins.map((m) => {
                        const initials = m.user.name.split(' ').map(n => n[0]).join('').substring(0,2).toUpperCase();
                        return (
                        <div key={m.user.id} className="org-row">
                          <div className="org-row-user">
                            <div className="user-avatar">{initials}</div>
                            <div className="user-details">
                              <strong>{m.user.name}</strong>
                              <span>{m.user.email || m.user.username}</span>
                            </div>
                          </div>
                          <div className="org-row-roles">
                            <span className="pill ok-badge">Org Admin</span>
                          </div>
                        </div>
                      )})}
                      {!admins.length && (
                        <div className="empty-note" style={{ padding: '2rem', textAlign: 'center' }}>No org admins assigned.</div>
                      )}
                    </div>
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
                    <div className="org-stat-card">
                      <div className="stat-header">
                        <div className="stat-content">
                          <span>Queue depth</span>
                          <strong>{executor?.queue_depth ?? 0}</strong>
                        </div>
                        <div className="stat-icon-wrapper bg-blue"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="8" y1="6" x2="21" y2="6"></line><line x1="8" y1="12" x2="21" y2="12"></line><line x1="8" y1="18" x2="21" y2="18"></line><line x1="3" y1="6" x2="3.01" y2="6"></line><line x1="3" y1="12" x2="3.01" y2="12"></line><line x1="3" y1="18" x2="3.01" y2="18"></line></svg></div>
                      </div>
                    </div>
                    <div className="org-stat-card">
                      <div className="stat-header">
                        <div className="stat-content">
                          <span>Mode</span>
                          <strong>{(executor?.mode || "—").replace(/_/g, " ")}</strong>
                        </div>
                        <div className="stat-icon-wrapper bg-purple"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg></div>
                      </div>
                    </div>
                    <div className="org-stat-card">
                      <div className="stat-header">
                        <div className="stat-content">
                          <span>Window ends</span>
                          <strong style={{ fontSize: '0.9rem' }}>
                            {executor?.window_ends_at
                              ? new Date(executor.window_ends_at).toLocaleString()
                              : "—"}
                          </strong>
                        </div>
                        <div className="stat-icon-wrapper bg-orange"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg></div>
                      </div>
                    </div>
                    <div className="org-stat-card">
                      <div className="stat-header">
                        <div className="stat-content">
                          <span>Last job</span>
                          <strong style={{ fontSize: '0.9rem' }}>
                            {executor?.last_job_at
                              ? new Date(executor.last_job_at).toLocaleString()
                              : "—"}
                          </strong>
                        </div>
                        <div className="stat-icon-wrapper bg-green"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline></svg></div>
                      </div>
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
                    <div className="invite-form-row" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
                      <div>
                        <h4>Execution Capacity Settings</h4>
                        <span className="page-sub">Configure how and when CLI executors are provisioned</span>
                      </div>
                      <div className="executor-mode-tabs" style={{ display: 'flex', background: 'var(--bg-2)', padding: '4px', borderRadius: '8px', width: 'fit-content', gap: '4px', marginBottom: '24px' }}>
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
                            onClick={() => setExecMode(value)}
                            style={{
                              padding: '8px 16px',
                              fontSize: '13px',
                              fontWeight: 500,
                              borderRadius: '6px',
                              border: 'none',
                              cursor: 'pointer',
                              background: execMode === value ? 'var(--panel)' : 'transparent',
                              color: execMode === value ? 'var(--text)' : 'var(--muted)',
                              boxShadow: execMode === value ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
                              transition: 'all 0.2s'
                            }}
                          >
                            {label}
                          </button>
                        ))}
                      </div>

                      {execMode === "window" && (
                        <div className="executor-window-tabs" style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginBottom: '24px', padding: '16px', background: 'var(--bg-2)', borderRadius: '8px', width: 'fit-content' }}>
                          <span style={{ fontSize: '13px', fontWeight: 500 }}>Select active duration</span>
                          <div style={{ display: 'flex', gap: '8px' }}>
                            {[6, 12, 24].map((hours) => (
                              <button
                                key={hours}
                                type="button"
                                className={`tiny-btn${windowHours === hours ? " solid" : ""}`}
                                onClick={() => setWindowHours(hours)}
                                style={{ padding: '8px 16px', fontSize: '13px' }}
                              >
                                {hours}h
                              </button>
                            ))}
                          </div>
                          <p className="empty-note" style={{ margin: 0, textAlign: 'left', padding: 0 }}>
                            Keep executors warm for the next {windowHours} hours from save.
                          </p>
                        </div>
                      )}

                      {execMode === "on_demand" && (
                        <div style={{ marginBottom: '24px', padding: '16px', background: 'var(--bg-2)', borderRadius: '8px', width: 'fit-content' }}>
                          <label className="executor-field invite-inputs" style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: '8px' }}>
                            <span style={{ fontSize: '13px', fontWeight: 500 }}>Idle scale-down (minutes)</span>
                            <input
                              type="number"
                              min={1}
                              max={1440}
                              value={idleMinutes}
                              onChange={(e) =>
                                setIdleMinutes(Number(e.target.value) || 15)
                              }
                              style={{ width: '120px' }}
                            />
                          </label>
                        </div>
                      )}

                      {execMode === "schedule" && (
                        <div className="executor-schedule" style={{ marginBottom: '24px', padding: '16px', background: 'var(--bg-2)', borderRadius: '8px', width: 'fit-content' }}>
                          <label className="executor-field invite-inputs">
                            <span>Timezone</span>
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
                          <div className="executor-time-row invite-inputs">
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

                      <div style={{ marginBottom: '24px', padding: '16px', background: 'var(--bg-2)', borderRadius: '8px', width: 'fit-content' }}>
                        <label className="executor-field invite-inputs" style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                          <span style={{ fontSize: '13px', fontWeight: 500 }}>Max replicas per provider</span>
                          <input
                            type="range"
                            min={1}
                            max={5}
                            value={maxReplicas}
                            onChange={(e) => setMaxReplicas(Number(e.target.value) || 1)}
                            style={{ width: '160px' }}
                          />
                          <span style={{ fontSize: '14px', fontWeight: 600, minWidth: '20px', textAlign: 'center' }}>{maxReplicas}</span>
                        </label>
                      </div>

                      <div className="executor-actions" style={{ display: 'flex', gap: '12px', marginTop: '12px', paddingTop: '24px', borderTop: '1px solid var(--border)' }}>
                        <button
                          type="button"
                          className="create-org-btn"
                          disabled={executorSaving}
                          onClick={() => void saveExecutorSettings()}
                          style={{ width: 'auto', padding: '0 24px' }}
                        >
                          {executorSaving ? "Saving…" : "Save capacity"}
                        </button>
                        <button
                          type="button"
                          className="tiny-btn"
                          onClick={() => void wakeExecutors()}
                          style={{ height: '36px', padding: '0 16px', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--panel)' }}
                        >
                          Wake now
                        </button>
                        <button
                          type="button"
                          className="tiny-btn"
                          onClick={() => void loadExecutor()}
                          style={{ height: '36px', padding: '0 16px', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--panel)' }}
                        >
                          Refresh status
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </>
          )}
          {message && (
            <div className={`form-msg ${
              message.toLowerCase().includes("failed") || message.toLowerCase().includes("unreachable") || message.toLowerCase().includes("error") ? "error" :
              message.toLowerCase().includes("created") || message.toLowerCase().includes("approved") || message.toLowerCase().includes("applied") || message.toLowerCase().includes("emailed") ? "success" : "info"
            }`}>
              {(message.toLowerCase().includes("ing.") || message.toLowerCase().includes("submitting")) && (
                <svg className="spinner" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="2" x2="12" y2="6"></line><line x1="12" y1="18" x2="12" y2="22"></line><line x1="4.93" y1="4.93" x2="7.76" y2="7.76"></line><line x1="16.24" y1="16.24" x2="19.07" y2="19.07"></line><line x1="2" y1="12" x2="6" y2="12"></line><line x1="18" y1="12" x2="22" y2="12"></line><line x1="4.93" y1="19.07" x2="7.76" y2="16.24"></line><line x1="16.24" y1="4.93" x2="19.07" y2="7.76"></line></svg>
              )}
              {message}
            </div>
          )}
          {showCreateOrg && (
            <Modal
              title="Create Organization"
              description="Enter a name for the new organization."
              onClose={() => setShowCreateOrg(false)}
            >
              <form className="modal-body" onSubmit={(e) => void createOrg(e)}>
                <label className="modal-label">
                  <span>Organization Name</span>
                  <input
                    type="text"
                    required
                    className="modal-input"
                    placeholder="My Organization"
                    value={newOrgName}
                    onChange={(e) => setNewOrgName(e.target.value)}
                  />
                </label>
                <div className="modal-actions" style={{ marginTop: '1.5rem', display: 'flex', justifyContent: 'flex-end', gap: '1rem' }}>
                  <button type="button" className="btn-secondary" onClick={() => setShowCreateOrg(false)} style={{ padding: '0.5rem 1rem', background: 'transparent', border: '1px solid var(--border)', color: 'var(--fg)', borderRadius: 'var(--radius)' }}>Cancel</button>
                  <button type="submit" className="create-org-btn" style={{ padding: '0.5rem 1rem' }}>Create</button>
                </div>
              </form>
            </Modal>
          )}
        </section>
      </main>
    </Shell>
  );
}
