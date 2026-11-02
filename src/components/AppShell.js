"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { useConsole } from "@/context/ConsoleContext";
import { ago, clock } from "@/lib/format";
import { RANGES } from "@/lib/ranges";
import { PageHead } from "@/components/ui";
import { permissionForPath, serviceMenus } from "@/lib/nav";
import { can, roleLabel } from "@/lib/rbac";

const GROUP_ICONS = {
  compute: ServerIcon,
  data: LayersIcon,
  network: BoxIcon,
  platform: StackIcon,
};

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: GridIcon, permission: "module.dashboard" },
  { section: "Estate" },
  { href: "/resources", label: "All services", icon: StackIcon, permission: "module.services" },
  ...serviceMenus().map((group) => ({ ...group, icon: GROUP_ICONS[group.id] })),
  { section: "Control" },
  { href: "/costs", label: "Costs & billing", icon: CardIcon, permission: "module.costs" },
  { href: "/alerts", label: "Alerts", icon: BellIcon, permission: "module.alerts" },
  { href: "/insights", label: "Advisor", icon: SparkIcon, permission: "module.advisor" },
  { href: "/sandbox", label: "Sandbox", icon: ClockIcon, permission: "module.sandbox" },
  { href: "/settings", label: "Organization", icon: GridIcon, permission: "project.read" },
  { section: "Agentic" },
  { href: "/chat", label: "Chat", icon: SparkIcon, permission: "module.chat" },
  { href: "/wiki", label: "Wiki", icon: StackIcon, permission: "module.wiki" },
  { href: "/findings", label: "Findings", icon: BellIcon, permission: "module.findings" },
  { href: "/workflows", label: "Workflows", icon: LayersIcon, permission: "module.workflows" },
  { href: "/approvals", label: "Approvals", icon: CardIcon, permission: "module.approvals" },
  { href: "/architecture", label: "Architecture", icon: BoxIcon, permission: "module.architecture" },
  { href: "/engineering", label: "Engineering", icon: ServerIcon, permission: "module.engineering" },
  { href: "/break-glass", label: "Break-glass", icon: SparkIcon, permission: "module.break-glass" },
];

function allowedItem(item, orgRole, projectRole, customPermissions) {
  if (!item.permission) return true;
  return can(orgRole, projectRole, item.permission, customPermissions);
}

function navigationFor(orgRole, projectRole, customPermissions) {
  if (!orgRole) return NAV;
  const items = NAV.flatMap((item) => {
    if (item.children) {
      const children = item.children.filter((child) => allowedItem(child, orgRole, projectRole, customPermissions));
      if (!children.length || !allowedItem(item, orgRole, projectRole, customPermissions)) return [];
      return [{ ...item, children }];
    }
    return allowedItem(item, orgRole, projectRole, customPermissions) ? [item] : [];
  });
  return items.filter((item, index) => {
    if (!item.section) return true;
    const rest = items.slice(index + 1);
    const nextSection = rest.findIndex((entry) => entry.section);
    const block = nextSection === -1 ? rest : rest.slice(0, nextSection);
    return block.some((entry) => !entry.section);
  });
}

function isItemActive(href, pathname, searchParams) {
  const [path, query] = href.split("?");
  const pathMatch = pathname === path || (!query && pathname.startsWith(`${path}/`));
  if (!pathMatch) return false;
  if (!query) return !searchParams.get("kind") && !searchParams.get("service");
  const want = new URLSearchParams(query);
  for (const [key, value] of want.entries()) {
    if (searchParams.get(key) !== value) return false;
  }
  return true;
}

export default function AppShell({ children }) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const router = useRouter();
  const { model, projectId, rangeId, now, error, selectProject, selectRange, switchOrg } = useConsole();
  const [navOpen, setNavOpen] = useState(false);
  const [projectOpen, setProjectOpen] = useState(false);
  const [userOpen, setUserOpen] = useState(false);
  const [openGroups, setOpenGroups] = useState({ compute: true, data: true, network: true, platform: true });
  const [mounted, setMounted] = useState(false);
  const workspace = model?.workspace;
  const projects = workspace?.projects || [];
  const project = projects.find((item) => item.id === projectId) || projects[0];
  const routeKey = `${pathname}?${searchParams.toString()}`;
  const [seenRoute, setSeenRoute] = useState(routeKey);
  if (seenRoute !== routeKey) {
    setSeenRoute(routeKey);
    setNavOpen(false);
  }

  async function logout() {
    await fetch("/api/logout", { method: "POST" });
    router.push("/login");
    router.refresh();
  }

  const onSuite = ["/chat", "/wiki", "/findings", "/workflows", "/approvals", "/architecture", "/engineering", "/break-glass"].some(
    (path) => pathname === path || pathname.startsWith(`${path}/`),
  );
  const onSync = pathname === "/sandbox" || pathname === "/sync";
  const showSetup = model?.status === "setup" && pathname !== "/settings" && !onSuite && !onSync;
  useEffect(() => setMounted(true), []);
  const orgName = mounted && workspace?.org?.name ? workspace.org.name : "Azure";
  const projectName = mounted && project?.name ? project.name : "No project";

  return (
    <div className="min-h-screen bg-canvas">
      {navOpen && (
        <button type="button" aria-label="Close menu" className="fixed inset-0 z-30 bg-ink/30 lg:hidden" onClick={() => setNavOpen(false)} />
      )}
      <aside className={`sidebar-scroll fixed inset-y-0 left-0 z-40 flex w-[280px] flex-col bg-sidebar px-3 pb-4 transition-transform ${navOpen ? "translate-x-0" : "-translate-x-full"} lg:translate-x-0`}>
        <div className="sticky top-0 z-10 flex h-[72px] items-center gap-2.5 border-b border-[#e4e4e4] bg-sidebar px-2">
          <span className="grid h-9 w-9 place-items-center rounded-xl bg-brand text-sm font-bold text-white">IF</span>
          <div className="min-w-0">
            <div className="text-[15px] font-bold leading-none">Infralens</div>
            <div className="mt-1 truncate text-[11px] text-muted">{orgName}</div>
          </div>
        </div>
        <nav className="mt-3 flex-1 space-y-1 overflow-y-auto">
          {navigationFor(workspace?.orgRole, project?.role, project?.permissions).map((item) => {
            if (item.section) {
              return (
                <div key={item.section} className="px-3 pb-1 pt-4 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted">
                  {item.section}
                </div>
              );
            }
            if (item.children) {
              const open = openGroups[item.id];
              const childActive = item.children.some((child) => isItemActive(child.href, pathname, searchParams));
              return (
                <div key={item.id}>
                  <button
                    type="button"
                    onClick={() => setOpenGroups((state) => ({ ...state, [item.id]: !open }))}
                    className={`flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm font-semibold ${childActive ? "text-ink" : "text-[#5f5f5f]"}`}
                  >
                    <item.icon />
                    <span className="flex-1">{item.label}</span>
                    <span className="text-xs text-muted">{open ? "–" : "+"}</span>
                  </button>
                  {open && (
                    <div className="ml-4 space-y-0.5 border-l border-[#e4e4e4] pl-2">
                      {item.children.map((child) => (
                        <Link
                          key={child.href}
                          href={child.href}
                          className={`block rounded-xl px-3 py-1.5 text-sm ${isItemActive(child.href, pathname, searchParams) ? "bg-orange-50 font-semibold text-ink shadow-[inset_3px_0_0_#E2773C]" : "text-[#5f5f5f] hover:bg-white"}`}
                        >
                          {child.label}
                        </Link>
                      ))}
                    </div>
                  )}
                </div>
              );
            }
            const active = isItemActive(item.href, pathname, searchParams);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-2 rounded-xl px-3 py-2 text-sm font-semibold ${active ? "bg-orange-50 text-ink shadow-[inset_3px_0_0_#E2773C]" : "text-[#5f5f5f] hover:bg-white"}`}
              >
                <item.icon />
                {item.label}
              </Link>
            );
          })}
        </nav>
      </aside>
      <div className="lg:pl-[280px]">
        <header className="sticky top-0 z-20 flex h-[72px] items-center gap-2 border-b border-line bg-canvas/90 px-4 backdrop-blur sm:px-6">
          <button type="button" className="rounded-xl border border-line px-3 py-2 text-sm lg:hidden" onClick={() => setNavOpen(true)}>
            Menu
          </button>
          <div className="relative">
            <button type="button" onClick={() => setProjectOpen((open) => !open)} className="rounded-2xl border border-line bg-white px-3 py-2 text-left">
              <span className="block text-sm font-semibold">{projectName}</span>
              <span className="block text-[11px] text-muted">{mounted && workspace?.org?.name ? workspace.org.name : "Select a project"}</span>
            </button>
            {projectOpen && (
              <div className="absolute left-0 top-14 z-30 w-72 rounded-2xl border border-line bg-white p-1.5 shadow-[0_8px_24px_rgba(149,157,165,0.2)]">
                {projects.length === 0 && <div className="px-3 py-2 text-sm text-muted">No projects yet.</div>}
                {projects.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => {
                      selectProject(item.id);
                      setProjectOpen(false);
                    }}
                    className={`flex w-full flex-col rounded-xl px-3 py-2 text-left hover:bg-canvas ${item.id === project?.id ? "bg-canvas" : ""}`}
                  >
                    <span className="text-sm font-semibold">{item.name}</span>
                    <span className="text-xs text-muted">{roleLabel(item.role)}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="hidden items-center gap-1 rounded-2xl bg-sidebar p-1 md:flex">
            {RANGES.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => selectRange(item.id)}
                className={`rounded-xl px-2.5 py-1.5 text-xs font-semibold ${item.id === rangeId ? "bg-white text-ink shadow-sm" : "text-muted"}`}
              >
                {item.label}
              </button>
            ))}
          </div>
          <div className="ml-auto flex items-center gap-2">
            <Link href="/sandbox" className="inline-flex items-center gap-2 rounded-full border border-line px-3 py-1.5 text-xs font-semibold">
              <span>{mounted && model?.refreshing ? "Syncing in background" : mounted && model?.syncedAt && now ? `Saved ${ago((now - model.syncedAt) / 60000)}` : "Sandbox"}</span>
              <span className="text-muted" suppressHydrationWarning>
                {mounted && now ? clock(new Date(now)) : "--:--:--"}
              </span>
            </Link>
            <div className="relative">
              <button type="button" onClick={() => setUserOpen((open) => !open)} className="grid h-9 w-9 place-items-center rounded-full bg-ink text-xs font-bold text-white">
                {(mounted && workspace?.user?.name ? workspace.user.name : "U").slice(0, 1)}
              </button>
              {userOpen && (
                <div className="absolute right-0 top-12 z-30 w-64 rounded-2xl border border-line bg-white p-3 shadow-[0_8px_24px_rgba(149,157,165,0.2)]">
                  <div className="text-sm font-semibold">{workspace?.user?.name}</div>
                  <div className="text-xs text-muted">{workspace?.user?.email}</div>
                  <div className="mt-1 text-xs text-muted">{roleLabel(workspace?.orgRole)}</div>
                  {(workspace?.orgs || []).length > 1 && (
                    <div className="mt-3 space-y-1">
                      {workspace.orgs.map((org) => (
                        <button key={org.id} type="button" onClick={() => switchOrg(org.id)} className="block w-full rounded-xl px-2 py-1 text-left text-xs hover:bg-canvas">
                          {org.name}
                        </button>
                      ))}
                    </div>
                  )}
                  <button type="button" onClick={logout} className="mt-3 text-sm font-semibold text-brand">
                    Sign out
                  </button>
                </div>
              )}
            </div>
          </div>
        </header>
        <main className="relative px-4 py-5 sm:px-6">
          {error && <div className="mb-4 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-danger">{error}</div>}
          {model?.refreshing && model.status === "ready" && (
            <div className="mb-4 rounded-2xl border border-line bg-white px-4 py-3 text-sm text-muted">Updating this view in the background. The figures on screen stay until the new copy is ready.</div>
          )}
          {showSetup ? (
            <SetupCard message={model.message} />
          ) : model?.status === "syncing" && !onSync ? (
            <section className="mx-auto max-w-2xl rounded-2xl border border-line bg-white p-6">
              <h1 className="text-2xl font-semibold">Preparing {model.project?.name || "this view"}</h1>
              <p className="mt-2 text-sm text-muted">{model.message}</p>
            </section>
          ) : workspace && !can(workspace.orgRole, project?.role, permissionForPath(pathname), project?.permissions) ? (
            <PageHead title="Not available for this role" description="Your role does not include this page. An organization admin can change the role from Organization." />
          ) : (
            children
          )}
          <p className="mt-8 text-center text-[11px] text-muted">
            Infralens · {orgName} · {mounted && project?.name ? project.name : "no project"} · Azure CLI
          </p>
        </main>
      </div>
    </div>
  );
}

function SetupCard({ message }) {
  return (
    <section className="mx-auto max-w-2xl rounded-2xl border border-line bg-white p-6">
      <h1 className="text-2xl font-semibold">Connect this organization to Azure</h1>
      <p className="mt-2 text-sm text-muted">{message}</p>
      <ol className="mt-4 list-decimal space-y-2 pl-5 text-sm">
        <li>Create an app registration and a client secret.</li>
        <li>Grant that app Reader and Cost Management Reader on the subscriptions it should see.</li>
        <li>Save the tenant ID, client ID, and secret under Organization.</li>
        <li>Create a project and attach only the subscriptions that belong to it.</li>
      </ol>
      <Link href="/settings" className="mt-5 inline-flex h-11 items-center rounded-2xl bg-brand px-4 text-sm font-semibold text-white">
        Open organization settings
      </Link>
    </section>
  );
}

function ServerIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <rect x="3" y="4" width="18" height="6" rx="1.5" />
      <rect x="3" y="14" width="18" height="6" rx="1.5" />
      <path d="M7 7h.01M7 17h.01" />
    </svg>
  );
}
function GridIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </svg>
  );
}
function LayersIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="M12 3 3 8l9 5 9-5-9-5Z" />
      <path d="m3 12 9 5 9-5" />
      <path d="m3 16 9 5 9-5" />
    </svg>
  );
}
function BoxIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="M21 8 12 3 3 8l9 5 9-5Z" />
      <path d="M3 8v8l9 5 9-5V8" />
      <path d="M12 13v8" />
    </svg>
  );
}
function StackIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="M4 7h16M4 12h16M4 17h10" />
    </svg>
  );
}
function CardIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="M3 10h18" />
    </svg>
  );
}
function BellIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15L6 16Z" />
      <path d="M10 19a2 2 0 0 0 4 0" />
    </svg>
  );
}
function ClockIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <circle cx="12" cy="12" r="8" />
      <path d="M12 8v5l3 2" />
    </svg>
  );
}
function SparkIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M18.4 5.6l-2.8 2.8M8.4 15.6l-2.8 2.8" />
    </svg>
  );
}
