"use client";

/* Static export navigation must use plain anchors. */
/* eslint-disable @next/next/no-html-link-for-pages */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { usePathname } from "next/navigation";
import { api } from "../lib/api";
import {
  emptyCatalog,
  pickDefaultProjectId,
  TIME_RANGES,
  timeAgo,
} from "../lib/dashboard";
import type { Catalog, Project } from "../lib/types";
import { Shell } from "./shell";
import { ThemedSelect } from "./themed-select";

export type DashboardContextValue = {
  projects: Project[];
  projectId: string | null;
  selectProject: (id: string) => void;
  timeRange: string;
  setTimeRange: (value: string) => void;
  catalog: Catalog;
  azureConfigured: boolean | null;
  updated: Date | null;
  setUpdated: (value: Date | null) => void;
  loading: boolean;
  setLoading: (value: boolean) => void;
  refreshKey: number;
  bumpRefresh: () => void;
};

const DashboardContext = createContext<DashboardContextValue | null>(null);

export function useDashboardContext() {
  const value = useContext(DashboardContext);
  if (!value) {
    throw new Error("useDashboardContext must be used inside DashboardShell");
  }
  return value;
}

const NAV_ITEMS = [
  {
    href: "/dashboard/",
    label: "Overview",
    match: (path: string) => {
      const normalized = path.replace(/\/$/, "") || "/";
      return normalized === "/dashboard";
    },
  },
  { href: "/dashboard/findings/", label: "Findings", match: (path: string) => path.includes("/dashboard/findings") },
  { href: "/dashboard/approvals/", label: "Approvals", match: (path: string) => path.includes("/dashboard/approvals") },
  { href: "/dashboard/workflows/", label: "Workflows", match: (path: string) => path.includes("/dashboard/workflows") },
  { href: "/dashboard/architecture/", label: "Architecture", match: (path: string) => path.includes("/dashboard/architecture") },
  { href: "/dashboard/engineering/", label: "Engineering", match: (path: string) => path.includes("/dashboard/engineering") },
  { href: "/dashboard/break-glass/", label: "Break-glass", match: (path: string) => path.includes("/dashboard/break-glass") },
];

export function DashboardShell({
  children,
  title,
  actions,
}: {
  children: ReactNode;
  title: string;
  actions?: ReactNode;
}) {
  const pathname = usePathname() || "/dashboard/";
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [timeRange, setTimeRange] = useState("all");
  const [catalog, setCatalog] = useState<Catalog>(emptyCatalog);
  const [azureConfigured, setAzureConfigured] = useState<boolean | null>(null);
  const [updated, setUpdated] = useState<Date | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);

  const bumpRefresh = useCallback(() => {
    setRefreshKey((value) => value + 1);
    window.dispatchEvent(new Event("infralens-refresh"));
  }, []);

  const selectProject = useCallback((id: string) => {
    setUpdated(null);
    setLoading(true);
    setProjectId(id);
    window.localStorage.setItem("projectId", id);
  }, []);

  useEffect(() => {
    void Promise.all([
      api<Project[]>("/api/projects").then((list) => {
        setProjects(list);
        const saved = window.localStorage.getItem("projectId");
        const selected = pickDefaultProjectId(list, saved);
        setProjectId(selected);
        if (!selected) setLoading(false);
      }),
      api<Catalog>("/api/intelligence/catalog").then(setCatalog).catch(() => setCatalog(emptyCatalog())),
      api<{ azure_configured: boolean }>("/api/health")
        .then((health) => setAzureConfigured(health.azure_configured))
        .catch(() => setAzureConfigured(false)),
    ]);
  }, []);

  const contextValue = useMemo<DashboardContextValue>(
    () => ({
      projects,
      projectId,
      selectProject,
      timeRange,
      setTimeRange,
      catalog,
      azureConfigured,
      updated,
      setUpdated,
      loading,
      setLoading,
      refreshKey,
      bumpRefresh,
    }),
    [
      projects,
      projectId,
      selectProject,
      timeRange,
      catalog,
      azureConfigured,
      updated,
      loading,
      refreshKey,
      bumpRefresh,
    ],
  );

  return (
    <DashboardContext.Provider value={contextValue}>
      <Shell subtitle="Intelligence Layer" scroll loading={loading}>
        <div className="dash-layout">
          <aside className="dash-sidebar-nav">
            <h3 className="nav-heading">Dashboard</h3>
            <nav className="module-tabs dash-subnav" aria-label="Dashboard sections">
              {NAV_ITEMS.map((item) => {
                const isActive = item.match(pathname);
                return (
                  <a
                    key={item.href}
                    href={item.href}
                    className={`module-tab${isActive ? " active" : ""}`}
                    aria-current={isActive ? "page" : undefined}
                  >
                    <span>{item.label}</span>
                  </a>
                );
              })}
            </nav>
          </aside>
          <main className="dash">
            <div className="dash-head">
              <div className="dash-context">
                <span className="dash-context-label">Dashboard</span>
                <strong>{title}</strong>
              </div>
              <div className="dash-head-controls">
                <label className="control">
                  <span>Project</span>
                  <ThemedSelect
                    className="project-select"
                    value={projectId || ""}
                    ariaLabel="Project"
                    onChange={selectProject}
                    options={projects.map((project) => ({
                      value: project.id,
                      label: `${project.name}${project.is_default ? " (default)" : ""}`,
                    }))}
                  />
                </label>
                <label className="control">
                  <span>Time</span>
                  <ThemedSelect
                    className="time-select"
                    value={timeRange}
                    ariaLabel="Time range"
                    onChange={setTimeRange}
                    options={TIME_RANGES}
                  />
                </label>
                <span className="updated-note">
                  {updated
                    ? `Updated ${timeAgo(updated.toISOString())}`
                    : projectId
                      ? "Loading"
                      : "Selecting project"}
                </span>
                <button
                  type="button"
                  className="ghost"
                  onClick={bumpRefresh}
                  disabled={!projectId}
                >
                  Refresh
                </button>
                {actions}
              </div>
            </div>
            {children}
          </main>
        </div>
      </Shell>
    </DashboardContext.Provider>
  );
}
