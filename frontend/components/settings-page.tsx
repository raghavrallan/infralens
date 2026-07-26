"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { displayBrandText } from "../lib/branding";
import type { ConnectionStatus, JsonObject, Project } from "../lib/types";
import { Modal } from "./modal";
import { ProjectModal } from "./project-modal";
import { Shell } from "./shell";
import { ThemedSelect } from "./themed-select";

type Provider = "azure" | "aws" | "github";
const providerFields: Record<
  Provider,
  { label: string; name: string; type?: string; placeholder?: string }[]
> = {
  azure: [
    { label: "Tenant ID", name: "tenant_id" },
    { label: "Client ID", name: "client_id" },
    { label: "Client secret", name: "client_secret", type: "password" },
    { label: "Subscription ID (optional)", name: "subscription_id" },
  ],
  aws: [
    { label: "Access key ID", name: "access_key_id" },
    { label: "Secret access key", name: "secret_access_key", type: "password" },
    { label: "Region", name: "region", placeholder: "us-east-1" },
  ],
  github: [
    { label: "Username", name: "username" },
    { label: "Personal access token", name: "token", type: "password" },
  ],
};

function formatDate(iso?: string) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function ProviderCard({
  provider,
  projectId,
  status,
  onChanged,
}: {
  provider: Provider;
  projectId: string;
  status?: ConnectionStatus;
  onChanged: () => void;
}) {
  const [method, setMethod] = useState(
    status?.method ||
      (provider === "azure"
        ? "client_secret"
        : provider === "aws"
          ? "access_key"
          : "token"),
  );
  const [fields, setFields] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const labels = {
    azure: "Azure account",
    aws: "AWS account",
    github: "GitHub account",
  };
  const connectionDetails = [status?.method, status?.identity, status?.hint]
    .filter(Boolean)
    .join(" · ");
  useEffect(() => {
    if (status?.method) setMethod(status.method);
  }, [status?.method]);
  const update = (name: string, value: string) =>
    setFields((current) => ({ ...current, [name]: value }));
  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    if (method !== "sso" && !Object.values(fields).some(Boolean)) {
      setMessage("Please fill in at least one field.");
      return;
    }
    setMessage("Saving…");
    try {
      await api(`/api/projects/${projectId}/connections/${provider}`, {
        method: "PUT",
        body: JSON.stringify({ method, fields }),
      });
      setMessage("Connected.");
      onChanged();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not connect.");
    }
  };
  return (
    <section className="card provider">
      <div className="card-head">
        <h3>{labels[provider]}</h3>
        <span className={`pill ${status?.connected ? "ok" : "off"}`}>
          {status?.connected
            ? `connected${connectionDetails ? ` · ${connectionDetails}` : ""}`
            : "not connected"}
        </span>
      </div>
      <div className="method-tabs">
        <button
          type="button"
          className={`method-tab${method === (provider === "azure" ? "client_secret" : provider === "aws" ? "access_key" : "token") ? " active" : ""}`}
          onClick={() =>
            setMethod(
              provider === "azure"
                ? "client_secret"
                : provider === "aws"
                  ? "access_key"
                  : "token",
            )
          }
        >
          {provider === "github"
            ? "Token"
            : provider === "aws"
              ? "Access key"
              : "Client secret"}
        </button>
        <button
          type="button"
          className={`method-tab${method === "sso" ? " active" : ""}`}
          onClick={() => setMethod("sso")}
        >
          SSO
        </button>
      </div>
      <form onSubmit={(event) => void save(event)}>
        {method === "sso" ? (
          <div className="fields">
            <p className="muted small">
              Records the directory for single sign-on. Redirect-based login
              completes in a follow-up build.
            </p>
          </div>
        ) : (
          <div className="fields">
            {providerFields[provider].map((field) => (
              <label key={field.name}>
                {field.label}
                <input
                  name={field.name}
                  type={field.type || "text"}
                  value={fields[field.name] || ""}
                  placeholder={field.placeholder}
                  onChange={(event) => update(field.name, event.target.value)}
                />
              </label>
            ))}
          </div>
        )}
        <div className="actions">
          <button type="submit" className="primary">
            Connect
          </button>
          {status?.connected && (
            <button
              type="button"
              className="ghost"
              onClick={async () => {
                await api(
                  `/api/projects/${projectId}/connections/${provider}`,
                  { method: "DELETE" },
                );
                onChanged();
              }}
            >
              Disconnect
            </button>
          )}
        </div>
        <div className="form-msg muted">
          {message ||
            (status?.connected_at
              ? `Connected ${formatDate(status.connected_at)}`
              : "")}
        </div>
      </form>
    </section>
  );
}

export function SettingsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [projectMessage, setProjectMessage] = useState("");
  const [projectModalOpen, setProjectModalOpen] = useState(false);
  const [azure, setAzure] = useState({
    endpoint: "",
    api_key: "",
    deployment: "gpt-4o",
    api_version: "2024-10-21",
    configured: false,
    has_key: false,
  });
  const [azureMessage, setAzureMessage] = useState("");
  const [connections, setConnections] = useState<ConnectionStatus[]>([]);
  const [repos, setRepos] = useState<{
    mapped: string[];
    available: string[];
    github_connected: boolean;
    error?: string;
  }>({ mapped: [], available: [], github_connected: false });
  const [repoMessage, setRepoMessage] = useState("");
  const [repoSearch, setRepoSearch] = useState("");

  const loadProjects = useCallback(async () => {
    const list = await api<Project[]>("/api/projects");
    setProjects(list);
    const saved = window.localStorage.getItem("projectId");
    const selected =
      saved && list.some((project) => project.id === saved)
        ? saved
        : list.find((project) => project.is_default)?.id || list[0]?.id || null;
    setProjectId(selected);
  }, []);
  const loadConnections = useCallback(async (selected?: string) => {
    if (!selected) return;
    const list = await api<ConnectionStatus[]>(
      `/api/projects/${selected}/connections`,
    );
    setConnections(
      list.map(
        (item) => ({ ...item, project_id: selected }) as ConnectionStatus,
      ),
    );
    const repoData = await api<typeof repos>(`/api/projects/${selected}/repos`);
    setRepos({
      ...repoData,
      mapped: repoData.mapped || [],
      available: repoData.available || [],
    });
  }, []);
  useEffect(() => {
    void loadProjects();
    void api<typeof azure>("/api/config/azure-openai").then(setAzure);
  }, [loadProjects]);
  useEffect(() => {
    void loadConnections(projectId || undefined);
  }, [loadConnections, projectId]);
  const current = projects.find((project) => project.id === projectId);
  const connection = (provider: Provider) =>
    connections.find((item) => item.provider === provider);
  const switchProject = (id: string) => {
    setProjectId(id);
    window.localStorage.setItem("projectId", id);
  };
  const makeDefault = async () => {
    if (!projectId || current?.is_default) return;
    await api(`/api/projects/${projectId}/default`, { method: "PUT" });
    setProjects((items) =>
      items.map((project) => ({
        ...project,
        is_default: project.id === projectId,
      })),
    );
    setProjectMessage("Default project updated.");
  };
  const createProject = async (name: string) => {
    await api("/api/projects", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    setProjectMessage("Project created.");
    await loadProjects();
  };
  const [renameModal, setRenameModal] = useState(false);
  const [renameDraft, setRenameDraft] = useState("");
  const [deleteModal, setDeleteModal] = useState(false);
  const [deletingProject, setDeletingProject] = useState(false);
  const openRenameModal = () => {
    setRenameDraft(current?.name || "");
    setRenameModal(true);
  };
  const openDeleteModal = () => {
    if (!projectId) return;
    if (current?.is_default) {
      setProjectMessage(
        "Cannot delete the default project. Click Make default on another project first, then delete this one.",
      );
      return;
    }
    setDeleteModal(true);
  };
  const submitRename = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!renameDraft.trim()) return;
    await api(`/api/projects/${projectId}`, {
      method: "PATCH",
      body: JSON.stringify({ name: renameDraft.trim() }),
    });
    setRenameModal(false);
    setProjectMessage("Project renamed.");
    await loadProjects();
  };
  const confirmDeleteProject = async () => {
    if (!projectId || current?.is_default) return;
    setDeletingProject(true);
    try {
      await api(`/api/projects/${projectId}`, { method: "DELETE" });
      window.localStorage.removeItem("projectId");
      setDeleteModal(false);
      setProjectMessage("Project deleted.");
      await loadProjects();
    } catch (error) {
      setProjectMessage(
        error instanceof Error ? error.message : "Could not delete project.",
      );
    } finally {
      setDeletingProject(false);
    }
  };
  const saveAzure = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setAzureMessage("Saving…");
    await api("/api/config/azure-openai", {
      method: "PUT",
      body: JSON.stringify({
        endpoint: azure.endpoint,
        api_key: azure.api_key,
        deployment: azure.deployment,
        api_version: azure.api_version,
      }),
    });
    setAzureMessage("Saved.");
    setAzure(await api<typeof azure>("/api/config/azure-openai"));
  };
  const saveRepos = async () => {
    await api(`/api/projects/${projectId}/repos`, {
      method: "PUT",
      body: JSON.stringify({ repos: repos.mapped }),
    });
    setRepoMessage("Repositories saved.");
  };
  const allRepoNames = useMemo(
    () => [...new Set([...repos.available, ...repos.mapped])].sort(),
    [repos.available, repos.mapped],
  );
  const visibleRepos = useMemo(
    () =>
      allRepoNames.filter((repo) =>
        repo.toLowerCase().includes(repoSearch.toLowerCase()),
      ),
    [allRepoNames, repoSearch],
  );
  const toggleRepo = (repo: string) =>
    setRepos((current) => ({
      ...current,
      mapped: current.mapped.includes(repo)
        ? current.mapped.filter((item) => item !== repo)
        : [...current.mapped, repo],
    }));

  return (
    <Shell scroll>
      <main className="content">
        <h2 className="page-title">Settings</h2>
        <p className="page-sub">
          Configure the assistant and connect the accounts your skills operate
          against. Everything here is stored in Postgres — never in environment
          files — and secrets are never sent back to the browser.
        </p>
        <section className="card">
          <div className="card-head">
            <h3>Project</h3>
            <span className="pill ok">
              {displayBrandText(current?.name) || "Selecting project"}
            </span>
          </div>
          <p className="muted small">
            Connections and repositories below are isolated per project. The
            default project is used when no project has been selected on a new
            session.
          </p>
          <div className="project-controls">
            <ThemedSelect
              className="project-select"
              value={projectId || ""}
              ariaLabel="Project"
              onChange={switchProject}
              options={projects.map((project) => ({
                value: project.id,
                label: `${displayBrandText(project.name)}${project.is_default ? " (default)" : ""}`,
              }))}
            />
            <button
              className="primary"
              onClick={() => setProjectModalOpen(true)}
            >
              New project
            </button>
            <button
              className="ghost"
              disabled={!projectId}
              onClick={openRenameModal}
            >
              Rename
            </button>
            <button
              className="ghost"
              disabled={!projectId || current?.is_default}
              onClick={() => void makeDefault()}
            >
              Make default
            </button>
            <button
              className="ghost danger"
              disabled={!projectId || current?.is_default}
              title={
                current?.is_default
                  ? "Make another project the default before deleting this one"
                  : "Delete this project"
              }
              onClick={openDeleteModal}
            >
              Delete
            </button>
          </div>
          <div className="form-msg">
            {projectMessage}
            {current?.is_default
              ? " This is the default project — make another project default before deleting it."
              : ""}
          </div>
        </section>
        <section className="card">
          <div className="card-head">
            <h3>Azure OpenAI</h3>
            <span className={`pill ${azure.configured ? "ok" : "off"}`}>
              {azure.configured ? "connected" : "not configured"}
            </span>
          </div>
          <p className="muted small">
            Global · powers the assistant and every skill across all projects.
            Stored in the database.
          </p>
          <form onSubmit={(event) => void saveAzure(event)}>
            <div className="fields">
              <label>
                Endpoint
                <input
                  value={azure.endpoint}
                  onChange={(event) =>
                    setAzure((current) => ({
                      ...current,
                      endpoint: event.target.value,
                    }))
                  }
                  placeholder="https://my-resource.openai.azure.com/"
                />
              </label>
              <label>
                API key
                <input
                  type="password"
                  value={azure.api_key}
                  onChange={(event) =>
                    setAzure((current) => ({
                      ...current,
                      api_key: event.target.value,
                    }))
                  }
                  placeholder={
                    azure.has_key ? "stored — leave blank to keep" : "API key"
                  }
                />
              </label>
              <label>
                Deployment name
                <input
                  value={azure.deployment}
                  onChange={(event) =>
                    setAzure((current) => ({
                      ...current,
                      deployment: event.target.value,
                    }))
                  }
                />
              </label>
              <label>
                API version
                <input
                  value={azure.api_version}
                  onChange={(event) =>
                    setAzure((current) => ({
                      ...current,
                      api_version: event.target.value,
                    }))
                  }
                />
              </label>
            </div>
            <div className="actions">
              <button type="submit" className="primary">
                Save
              </button>
            </div>
            <div className="form-msg">{azureMessage}</div>
          </form>
        </section>
        {projectId && (
          <>
            <ProviderCard
              provider="azure"
              projectId={projectId}
              status={connection("azure")}
              onChanged={() => void loadConnections(projectId)}
            />
            <ProviderCard
              provider="aws"
              projectId={projectId}
              status={connection("aws")}
              onChanged={() => void loadConnections(projectId)}
            />
            <ProviderCard
              provider="github"
              projectId={projectId}
              status={connection("github")}
              onChanged={() => void loadConnections(projectId)}
            />
            <section className="card">
              <div className="card-head">
                <h3>Repositories</h3>
                <span
                  className={`pill ${repos.github_connected ? "ok" : "off"}`}
                >
                  {repos.github_connected
                    ? `${repos.mapped.length} of ${repos.available.length} mapped`
                    : "GitHub not connected"}
                </span>
              </div>
              <p className="muted small">
                Only selected repositories are available to repository-aware
                skills.
              </p>
              {repos.github_connected && (
                <>
                  <div className="repos-toolbar">
                    <input
                      className="repos-search"
                      value={repoSearch}
                      onChange={(event) => setRepoSearch(event.target.value)}
                      placeholder="Search repositories…"
                    />
                    <button
                      className="ghost small-btn"
                      onClick={() =>
                        setRepos((current) => ({
                          ...current,
                          mapped: [...current.available],
                        }))
                      }
                    >
                      Select all
                    </button>
                    <button
                      className="ghost small-btn"
                      onClick={() =>
                        setRepos((current) => ({ ...current, mapped: [] }))
                      }
                    >
                      Clear
                    </button>
                  </div>
                  <div className="repos-list">
                    {visibleRepos.map((repo) => (
                      <label className="repo-row" key={repo}>
                        <input
                          type="checkbox"
                          checked={repos.mapped.includes(repo)}
                          onChange={() => toggleRepo(repo)}
                        />
                        {repo}
                      </label>
                    ))}
                  </div>
                </>
              )}
              <div className="actions">
                <button className="primary" onClick={() => void saveRepos()}>
                  Save repositories
                </button>
                <button
                  className="ghost"
                  onClick={() => void loadConnections(projectId)}
                >
                  Refresh list
                </button>
              </div>
              <div className="form-msg">{repoMessage || repos.error}</div>
            </section>
          </>
        )}{" "}
      </main>
      {projectModalOpen && (
        <ProjectModal
          onClose={() => setProjectModalOpen(false)}
          onCreate={createProject}
        />
      )}
      {renameModal && (
        <Modal
          eyebrow="Project"
          title="Rename project"
          description="Enter a new name for this project."
          onClose={() => setRenameModal(false)}
        >
          <form className="modal-body" onSubmit={(e) => void submitRename(e)}>
            <label className="modal-label">
              <span>Project name</span>
              <input
                autoFocus
                value={renameDraft}
                onChange={(e) => setRenameDraft(e.target.value)}
                placeholder="My project"
              />
            </label>
            <div className="modal-actions">
              <button type="button" className="modal-btn ghost" onClick={() => setRenameModal(false)}>
                Cancel
              </button>
              <button type="submit" className="modal-btn primary" disabled={!renameDraft.trim()}>
                Rename
              </button>
            </div>
          </form>
        </Modal>
      )}
      {deleteModal && (
        <Modal
          eyebrow="Project"
          title="Delete project?"
          description={`This will permanently delete “${displayBrandText(current?.name) || "this project"}”, including its connections, repositories, chats, workflows and findings. This cannot be undone.`}
          onClose={() => !deletingProject && setDeleteModal(false)}
        >
          <div className="modal-body">
            <div className="modal-actions">
              <button
                type="button"
                className="modal-btn ghost"
                disabled={deletingProject}
                onClick={() => setDeleteModal(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="modal-btn danger"
                disabled={deletingProject}
                onClick={() => void confirmDeleteProject()}
              >
                {deletingProject ? "Deleting…" : "Delete project"}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </Shell>
  );
}
