"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { Modal } from "./modal";

type PathId = "existing" | "new";
type Step =
  | "welcome"
  | "path"
  | "github"
  | "repos"
  | "create-repo"
  | "azure"
  | "done";

type AuthOptions = {
  github: {
    oauth: boolean;
    pat: boolean;
    methods: string[];
    oauth_note?: string | null;
  };
  azure: {
    oauth: boolean;
    secrets: boolean;
    methods: string[];
    oauth_note?: string | null;
  };
};

type Repo = {
  full_name: string;
  name?: string;
  private?: boolean;
  html_url?: string;
};

const STEP_BACK: Partial<Record<Step, Step>> = {
  path: "welcome",
  github: "path",
  repos: "github",
  "create-repo": "github",
  azure: "repos",
  done: "azure",
};

const FLOW_STEPS: { id: Step; label: string }[] = [
  { id: "welcome", label: "Welcome" },
  { id: "path", label: "Project" },
  { id: "github", label: "GitHub" },
  { id: "repos", label: "Repos" },
  { id: "azure", label: "Azure" },
  { id: "done", label: "Done" },
];

function stepIndex(step: Step, path: PathId): number {
  if (step === "welcome") return 0;
  if (step === "path") return 1;
  if (step === "github") return 2;
  if (step === "repos" || step === "create-repo") return 3;
  if (step === "azure") return 4;
  if (step === "done") return 5;
  return path === "new" ? 3 : 3;
}

function IconGithub({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0 1 12 6.844a9.59 9.59 0 0 1 2.504.337c1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.02 10.02 0 0 0 22 12.017C22 6.484 17.522 2 12 2Z" />
    </svg>
  );
}

function IconAzure({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M13.05 4.24 6.02 19.76h4.14l1.65-3.88h5.44l-4.2-11.64Zm1.18 2.9 3.02 8.38h-3.66l-.98-2.72-.93 2.72H8.5l5.73-8.38Z" />
    </svg>
  );
}

function IconFolder({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z" />
    </svg>
  );
}

function IconPlus({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8v8M8 12h8" />
    </svg>
  );
}

function IconCheck({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" aria-hidden="true">
      <path d="M5 12.5 10 17.5 19 7" />
    </svg>
  );
}

export function OnboardingWizard({
  onClose,
  onFinished,
  force = false,
  asPage = false,
}: {
  onClose?: () => void;
  onFinished: (projectId: string) => void;
  force?: boolean;
  asPage?: boolean;
}) {
  const [step, setStep] = useState<Step>("welcome");
  const [path, setPath] = useState<PathId>("existing");
  const [projectId, setProjectId] = useState("");
  const [projectName, setProjectName] = useState("");
  const [authOptions, setAuthOptions] = useState<AuthOptions | null>(null);
  const [ghMethod, setGhMethod] = useState<"token" | "oauth">("token");
  const [azMethod, setAzMethod] = useState<"client_secret" | "oauth">("client_secret");
  const [ghUser, setGhUser] = useState("");
  const [ghToken, setGhToken] = useState("");
  const [ghIdentity, setGhIdentity] = useState("");
  const [repos, setRepos] = useState<Repo[]>([]);
  const [repoSearch, setRepoSearch] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [newRepoName, setNewRepoName] = useState("");
  const [newRepoPrivate, setNewRepoPrivate] = useState(true);
  const [newRepoOrg, setNewRepoOrg] = useState("");
  const [azure, setAzure] = useState({
    tenant_id: "",
    client_id: "",
    client_secret: "",
    subscription_id: "",
  });
  const [azureConnected, setAzureConnected] = useState(false);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void api<AuthOptions>("/api/providers/auth-options")
      .then((opts) => {
        setAuthOptions(opts);
        if (opts.github.oauth) setGhMethod("oauth");
        else setGhMethod("token");
        if (opts.azure.oauth) setAzMethod("oauth");
      })
      .catch(() => undefined);

    const params = new URLSearchParams(window.location.search);
    if (params.get("oauth") === "github") {
      const pid = params.get("project_id") || "";
      if (params.get("ok") === "1" && pid) {
        setProjectId(pid);
        window.localStorage.setItem("projectId", pid);
        setGhIdentity("GitHub (OAuth)");
        setPath("existing");
        setStep("repos");
        setMessage("GitHub connected via OAuth. Select repositories.");
      } else if (params.get("ok") === "0") {
        setStep("github");
        setMessage("GitHub OAuth failed. Use a personal access token, or check OAuth app settings.");
      }
    }
  }, []);

  const copy = useMemo(() => {
    if (step === "welcome") {
      return {
        title: "Welcome to InfraLens",
        desc: "Connect GitHub, map repositories, and optionally link Azure — then open gated delivery workflows.",
      };
    }
    if (step === "path") {
      return {
        title: "Set up your project",
        desc: "Name the workspace and choose whether you’ll map existing repos or create a new one.",
      };
    }
    if (step === "github") {
      return {
        title: "Connect GitHub",
        desc: "Authorize with SSO or a personal access token so InfraLens can list and link repositories.",
      };
    }
    if (step === "repos") {
      return {
        title: "Select repositories",
        desc: "Pick one or more repos to attach to this project. You can change this later in Settings.",
      };
    }
    if (step === "create-repo") {
      return {
        title: "Create a repository",
        desc: "InfraLens will create the repo on GitHub, then link it to your project.",
      };
    }
    if (step === "azure") {
      return {
        title: "Connect Azure",
        desc: "Optional — link a subscription for cloud-aware delivery. You can skip and add this later.",
      };
    }
    return {
      title: "You're set",
      desc: "Your project is ready. Jump into delivery: docs → architecture → Terraform.",
    };
  }, [step]);

  const activeStep = stepIndex(step, path);
  const progressLabels = useMemo(() => {
    return FLOW_STEPS.map((s) =>
      s.id === "repos" ? (path === "new" ? "Create" : "Repos") : s.label,
    );
  }, [path]);

  const goBack = () => {
    setMessage("");
    let prev = STEP_BACK[step];
    if (step === "azure") {
      prev = path === "new" ? "create-repo" : "repos";
    }
    if (prev) setStep(prev);
  };

  const ensureProject = async () => {
    if (projectId) return projectId;
    const name = projectName.trim() || "Onboarding project";
    const project = await api<{ id: string; name: string }>("/api/projects", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    setProjectId(project.id);
    setProjectName(project.name);
    window.localStorage.setItem("projectId", project.id);
    return project.id;
  };

  const connectGithubPat = async () => {
    setBusy(true);
    setMessage("");
    try {
      const pid = await ensureProject();
      const result = await api<{ identity?: { login?: string } }>("/api/providers/github/pat", {
        method: "POST",
        body: JSON.stringify({
          project_id: pid,
          username: ghUser,
          token: ghToken,
        }),
      });
      setGhIdentity(result.identity?.login || ghUser || "connected");
      setStep(path === "existing" ? "repos" : "create-repo");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "GitHub connect failed");
    } finally {
      setBusy(false);
    }
  };

  const startGithubOauth = async () => {
    setBusy(true);
    setMessage("");
    try {
      if (!authOptions?.github.oauth) {
        setMessage(
          authOptions?.github.oauth_note ||
            "GitHub OAuth is not configured. Add GITHUB_OAUTH_CLIENT_ID and GITHUB_OAUTH_CLIENT_SECRET to .env, or use a personal access token.",
        );
        setBusy(false);
        return;
      }
      const pid = await ensureProject();
      const result = await api<{ authorize_url: string }>(
        `/api/providers/github/oauth/start?project_id=${encodeURIComponent(pid)}&return_to=onboarding`,
      );
      window.location.href = result.authorize_url;
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "OAuth unavailable — use PAT");
      setBusy(false);
    }
  };

  const loadRepos = async () => {
    setBusy(true);
    setMessage("");
    try {
      const pid = await ensureProject();
      const list = await api<Repo[]>(`/api/github/repos?project_id=${encodeURIComponent(pid)}`);
      setRepos(list);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not list repos");
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (step === "repos" && projectId) void loadRepos();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, projectId]);

  const filteredRepos = useMemo(() => {
    const q = repoSearch.trim().toLowerCase();
    if (!q) return repos;
    return repos.filter((repo) => repo.full_name.toLowerCase().includes(q));
  }, [repos, repoSearch]);

  const createRepo = async () => {
    setBusy(true);
    setMessage("");
    try {
      const pid = await ensureProject();
      const created = await api<{ full_name: string }>("/api/github/repos", {
        method: "POST",
        body: JSON.stringify({
          project_id: pid,
          name: newRepoName,
          private: newRepoPrivate,
          org: newRepoOrg,
        }),
      });
      setSelected([created.full_name]);
      if (!projectName.trim()) setProjectName(created.full_name.split("/")[1] || created.full_name);
      setStep("azure");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not create repo");
    } finally {
      setBusy(false);
    }
  };

  const connectAzure = async () => {
    setBusy(true);
    setMessage("");
    try {
      const pid = await ensureProject();
      if (azMethod === "oauth") {
        if (!authOptions?.azure.oauth) {
          setMessage(authOptions?.azure.oauth_note || "Azure OAuth is not configured.");
          setBusy(false);
          return;
        }
        const result = await api<{ authorize_url: string }>(
          `/api/providers/azure/oauth/start?project_id=${encodeURIComponent(pid)}`,
        );
        window.location.href = result.authorize_url;
        return;
      }
      await api("/api/providers/azure/secrets", {
        method: "POST",
        body: JSON.stringify({ project_id: pid, ...azure }),
      });
      setAzureConnected(true);
      setMessage("Azure connected.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Azure connect failed");
    } finally {
      setBusy(false);
    }
  };

  const finish = async () => {
    setBusy(true);
    setMessage("");
    try {
      const pid = await ensureProject();
      const linked = selected.length ? selected : [];
      if (path === "existing" && !linked.length) {
        setMessage("Select at least one repository.");
        setBusy(false);
        return;
      }
      await api(`/api/projects/${pid}`, {
        method: "PATCH",
        body: JSON.stringify({ name: projectName.trim() || "InfraLens project" }),
      });
      if (linked.length) {
        await api(`/api/projects/${pid}/repos`, {
          method: "PUT",
          body: JSON.stringify({ repos: linked }),
        });
      }
      await api("/api/onboarding/complete", {
        method: "POST",
        body: JSON.stringify({
          path,
          project_id: pid,
          project_name: projectName.trim() || "InfraLens project",
          repos: linked,
          azure_connected: azureConnected,
          github_connected: true,
        }),
      });
      onFinished(pid);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not finish onboarding");
    } finally {
      setBusy(false);
    }
  };

  const close = () => {
    if (onClose && !busy && !force) onClose();
  };

  const canGoBack = Boolean(STEP_BACK[step] || step === "azure");

  const body = (
    <div className={`ob-body${asPage ? " ob-body-page" : ""}`} key={step}>
      {step === "welcome" && (
        <div className="ob-welcome-list">
            <div className="ob-welcome-card">
              <div className="ob-welcome-icon github">
                <IconGithub className="ob-icon-github" />
              </div>
              <div className="ob-welcome-num active">1</div>
              <div className="ob-welcome-text">
                <div className="ob-welcome-title">Connect GitHub</div>
                <div className="ob-welcome-desc">Authorize with OAuth or use a Personal Access Token.</div>
              </div>
              <div className="ob-welcome-badge required">Required</div>
              <svg className="ob-welcome-chevron" viewBox="0 0 24 24" fill="none" strokeLinecap="round" strokeLinejoin="round"><polyline points="9 18 15 12 9 6"/></svg>
            </div>
            
            <div className="ob-welcome-card">
              <div className="ob-welcome-icon folder">
                <IconFolder className="ob-icon-folder" />
              </div>
              <div className="ob-welcome-num inactive">2</div>
              <div className="ob-welcome-text">
                <div className="ob-welcome-title">Select Repository</div>
                <div className="ob-welcome-desc">Choose one or more repositories to monitor.</div>
              </div>
              <div className="ob-welcome-badge required">Required</div>
              <svg className="ob-welcome-chevron" viewBox="0 0 24 24" fill="none" strokeLinecap="round" strokeLinejoin="round"><polyline points="9 18 15 12 9 6"/></svg>
            </div>
            
            <div className="ob-welcome-card">
              <div className="ob-welcome-icon azure">
                <IconAzure className="ob-icon-azure" />
              </div>
              <div className="ob-welcome-num inactive">3</div>
              <div className="ob-welcome-text">
                <div className="ob-welcome-title">Connect Azure (Optional)</div>
                <div className="ob-welcome-desc">Link your Azure subscription (optional).</div>
              </div>
              <div className="ob-welcome-badge optional">Optional</div>
              <svg className="ob-welcome-chevron" viewBox="0 0 24 24" fill="none" strokeLinecap="round" strokeLinejoin="round"><polyline points="9 18 15 12 9 6"/></svg>
            </div>

            <div className="ob-welcome-actions">
              <button type="button" className="ob-welcome-btn" onClick={() => setStep("path")}>
                Get started
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>
              </button>
            </div>
        </div>
      )}

      {step === "path" && (
        <>
          <label className="ob-field">
            <span>Project name</span>
            <input
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              placeholder="platform-security"
              autoFocus
            />
          </label>
          <div className="ob-paths" role="radiogroup" aria-label="How to start">
            <button
              type="button"
              role="radio"
              aria-checked={path === "existing"}
              className={`ob-path${path === "existing" ? " active" : ""}`}
              onClick={() => setPath("existing")}
            >
              <span className="ob-path-icon">
                <IconFolder />
              </span>
              <span className="ob-path-copy">
                <strong>Existing GitHub repo</strong>
                <span>Connect and select repositories you already have.</span>
              </span>
              <span className="ob-path-check" aria-hidden="true">
                <IconCheck />
              </span>
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={path === "new"}
              className={`ob-path${path === "new" ? " active" : ""}`}
              onClick={() => setPath("new")}
            >
              <span className="ob-path-icon">
                <IconPlus />
              </span>
              <span className="ob-path-copy">
                <strong>Create new GitHub repo</strong>
                <span>InfraLens creates a repo, then links the project.</span>
              </span>
              <span className="ob-path-check" aria-hidden="true">
                <IconCheck />
              </span>
            </button>
          </div>
          <div className="ob-actions">
            {canGoBack ? (
              <button type="button" className="ob-btn ghost" disabled={busy} onClick={goBack}>
                Back
              </button>
            ) : null}
            <button type="button" className="ob-btn primary" onClick={() => setStep("github")}>
              Continue
            </button>
          </div>
        </>
      )}

      {step === "github" && (
        <>
          <div className="ob-toggle" role="tablist" aria-label="GitHub auth method">
            <button
              type="button"
              role="tab"
              aria-selected={ghMethod === "token"}
              className={ghMethod === "token" ? "active" : ""}
              onClick={() => {
                setGhMethod("token");
                setMessage("");
              }}
            >
              Personal access token
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={ghMethod === "oauth"}
              className={ghMethod === "oauth" ? "active" : ""}
              onClick={() => {
                setGhMethod("oauth");
                setMessage("");
              }}
            >
              GitHub SSO
            </button>
          </div>

          {ghMethod === "token" ? (
            <div className="ob-fields">
              <label className="ob-field">
                <span>GitHub username</span>
                <input
                  value={ghUser}
                  onChange={(e) => setGhUser(e.target.value)}
                  autoComplete="username"
                  autoFocus
                />
              </label>
              <label className="ob-field">
                <span>Personal access token</span>
                <input
                  type="password"
                  value={ghToken}
                  onChange={(e) => setGhToken(e.target.value)}
                  autoComplete="off"
                  placeholder="ghp_…"
                />
              </label>
            </div>
          ) : (
            <div className="ob-sso-panel">
              <IconGithub className="ob-sso-mark" />
              <p>
                {authOptions?.github.oauth
                  ? "You’ll be redirected to GitHub to authorize InfraLens."
                  : authOptions?.github.oauth_note ||
                    "OAuth isn’t configured yet. Use a personal access token, or add GitHub OAuth credentials to .env."}
              </p>
            </div>
          )}

          {ghIdentity ? <div className="ob-status ok">Connected as {ghIdentity}</div> : null}

          <div className="ob-actions">
            {canGoBack ? (
              <button type="button" className="ob-btn ghost" disabled={busy} onClick={goBack}>
                Back
              </button>
            ) : null}
            {ghMethod === "token" ? (
              <button
                type="button"
                className="ob-btn primary"
                disabled={busy || !ghToken}
                onClick={() => void connectGithubPat()}
              >
                {busy ? "Validating…" : "Connect & continue"}
              </button>
            ) : (
              <button
                type="button"
                className="ob-btn primary"
                disabled={busy}
                onClick={() => void startGithubOauth()}
              >
                {busy ? "Opening GitHub…" : "Continue with GitHub"}
              </button>
            )}
          </div>
        </>
      )}

      {step === "repos" && (
        <>
          <label className="ob-field">
            <span>Search repositories</span>
            <input
              type="search"
              value={repoSearch}
              onChange={(e) => setRepoSearch(e.target.value)}
              placeholder="Filter by name…"
              autoFocus
            />
          </label>
          <div className="ob-repo-picker">
            {!repos.length ? (
              <div className="ob-empty">
                {busy ? "Loading repositories…" : "No repositories found for this account."}
              </div>
            ) : !filteredRepos.length ? (
              <div className="ob-empty">No repositories match “{repoSearch.trim()}”.</div>
            ) : (
              filteredRepos.map((repo) => {
                const checked = selected.includes(repo.full_name);
                return (
                  <label key={repo.full_name} className={`ob-repo-row${checked ? " selected" : ""}`}>
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() =>
                        setSelected((cur) =>
                          checked
                            ? cur.filter((r) => r !== repo.full_name)
                            : [...cur, repo.full_name],
                        )
                      }
                    />
                    <span className="ob-repo-name">{repo.full_name}</span>
                    <em className={repo.private ? "private" : "public"}>
                      {repo.private ? "private" : "public"}
                    </em>
                  </label>
                );
              })
            )}
          </div>
          {selected.length > 0 ? (
            <div className="ob-status">{selected.length} selected</div>
          ) : null}
          <div className="ob-actions">
            {canGoBack ? (
              <button type="button" className="ob-btn ghost" disabled={busy} onClick={goBack}>
                Back
              </button>
            ) : null}
            <button type="button" className="ob-btn ghost" onClick={() => void loadRepos()}>
              Refresh
            </button>
            <button
              type="button"
              className="ob-btn primary"
              disabled={!selected.length}
              onClick={() => {
                if (!projectName.trim() && selected[0]) {
                  setProjectName(selected[0].split("/")[1] || selected[0]);
                }
                setStep("azure");
              }}
            >
              Continue
            </button>
          </div>
        </>
      )}

      {step === "create-repo" && (
        <>
          <div className="ob-fields">
            <label className="ob-field">
              <span>Repository name</span>
              <input
                value={newRepoName}
                onChange={(e) => setNewRepoName(e.target.value)}
                placeholder="my-infra-project"
                autoFocus
              />
            </label>
            <label className="ob-field">
              <span>Organisation (optional)</span>
              <input
                value={newRepoOrg}
                onChange={(e) => setNewRepoOrg(e.target.value)}
                placeholder="Leave blank for your user account"
              />
            </label>
            <label className="ob-check">
              <input
                type="checkbox"
                checked={newRepoPrivate}
                onChange={(e) => setNewRepoPrivate(e.target.checked)}
              />
              <span>Private repository</span>
            </label>
          </div>
          <div className="ob-actions">
            {canGoBack ? (
              <button type="button" className="ob-btn ghost" disabled={busy} onClick={goBack}>
                Back
              </button>
            ) : null}
            <button
              type="button"
              className="ob-btn primary"
              disabled={busy || !newRepoName.trim()}
              onClick={() => void createRepo()}
            >
              {busy ? "Creating…" : "Create repo"}
            </button>
          </div>
        </>
      )}

      {step === "azure" && (
        <>
          <div className="ob-toggle" role="tablist" aria-label="Azure auth method">
            <button
              type="button"
              role="tab"
              aria-selected={azMethod === "client_secret"}
              className={azMethod === "client_secret" ? "active" : ""}
              onClick={() => setAzMethod("client_secret")}
            >
              Service principal
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={azMethod === "oauth"}
              className={azMethod === "oauth" ? "active" : ""}
              onClick={() => setAzMethod("oauth")}
            >
              Azure OAuth
            </button>
          </div>

          {azMethod === "oauth" ? (
            <div className="ob-sso-panel">
              <IconAzure className="ob-sso-mark azure" />
              <p>
                {authOptions?.azure.oauth
                  ? "You’ll be redirected to Microsoft to authorize InfraLens."
                  : authOptions?.azure.oauth_note ||
                    "Azure OAuth isn’t configured. Use a service principal, or skip for now."}
              </p>
            </div>
          ) : (
            <div className="ob-fields ob-fields-grid">
              {([
                ["tenant_id", "Tenant ID"],
                ["client_id", "Client ID"],
                ["client_secret", "Client secret"],
                ["subscription_id", "Subscription ID"],
              ] as const).map(([field, label]) => (
                <label className="ob-field" key={field}>
                  <span>{label}</span>
                  <input
                    type={field.includes("secret") ? "password" : "text"}
                    value={azure[field]}
                    onChange={(e) => setAzure((cur) => ({ ...cur, [field]: e.target.value }))}
                    autoComplete="off"
                  />
                </label>
              ))}
            </div>
          )}

          <div className="ob-actions">
            {canGoBack ? (
              <button type="button" className="ob-btn ghost" disabled={busy} onClick={goBack}>
                Back
              </button>
            ) : null}
            <button type="button" className="ob-btn ghost" onClick={() => setStep("done")}>
              Skip for now
            </button>
            <button
              type="button"
              className="ob-btn primary"
              disabled={busy}
              onClick={() => void connectAzure().then(() => setStep("done"))}
            >
              {busy ? "Saving…" : "Connect Azure"}
            </button>
          </div>
        </>
      )}

      {step === "done" && (
        <>
          <div className="ob-done">
            <span className="ob-done-mark">
              <IconCheck />
            </span>
            <div>
              <strong>{projectName.trim() || "Your project"}</strong>
              <span>
                {selected.length
                  ? `${selected.length} repo${selected.length === 1 ? "" : "s"} linked`
                  : path === "new"
                    ? "New repository linked"
                    : "Ready to open"}
                {azureConnected ? " · Azure connected" : ""}
              </span>
            </div>
          </div>
          <div className="ob-actions">
            {canGoBack ? (
              <button type="button" className="ob-btn ghost" disabled={busy} onClick={goBack}>
                Back
              </button>
            ) : null}
            <button
              type="button"
              className="ob-btn primary"
              disabled={busy}
              onClick={() => void finish()}
            >
              {busy ? "Finishing…" : "Open project"}
              {!busy ? (
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
                  <path d="M5 12h14M12 5l7 7-7 7" />
                </svg>
              ) : null}
            </button>
          </div>
        </>
      )}

      {message ? (
        <div
          className={`ob-status ${
            /fail|could not|at least one|not configured|unavailable|invalid|error/i.test(message)
              ? "error"
              : "ok"
          }`}
          role="alert"
        >
          {message}
        </div>
      ) : null}
    </div>
  );

  const panel = (
    <section className={step === 'welcome' && asPage ? "ob-panel ob-panel-welcome" : "ob-panel"} aria-labelledby="onboarding-title">
      {step === "welcome" ? (
        <div className="ob-welcome-header">
          <div className="ob-welcome-emoji">
            👋
          </div>
          <div>
            <h1 className="ob-welcome-heading">Welcome to InfraLens!</h1>
            <p className="ob-welcome-subtitle">Let’s set up your workspace. Connect your tools and<br/>start running secure delivery workflows.</p>
          </div>
        </div>
      ) : (
        <div className="ob-panel-head">
          <p className="ob-eyebrow">Onboarding</p>
          <h1 id="onboarding-title">{copy.title}</h1>
          <p className="ob-desc">{copy.desc}</p>
        </div>
      )}
      {body}
    </section>
  );

  if (asPage) {
    return (
      <div className="login-screen ob-screen ob-page-container">
        <div className="ob-shell ob-page-shell">
          <header className="ob-top ob-page-top">
            <div className="login-brand ob-brand ob-page-brand">
              <div className="ob-page-logo-icon">IL</div>
              <div className="ob-page-brand-text">
                <span className="ob-page-brand-name">InfraLens</span>
                <span className="ob-page-brand-sub">Workspace setup</span>
              </div>
            </div>
            
            {/* <div className="ob-page-header-right">
              <span className="ob-page-local-admin">Local Admin</span>
              <span className="ob-page-super-admin">Super Admin</span>
              <button type="button" className="ob-page-signout-btn">Sign out</button>
            </div> */}
          </header>
          
          <div className="ob-page-main-wrapper">
            <div className="ob-page-stepper-wrapper">
               <div className="ob-page-stepper">
                 <div className="ob-page-stepper-bg-line"></div>
                 <div className="ob-page-stepper-active-line" style={{ width: `calc((100% - 34px) * ${Math.min(activeStep, 4)} / 4)` }}></div>
                 {[
                   { id: 'welcome', label: 'Welcome', num: 1 },
                   { id: 'github', label: 'GitHub', num: 2 },
                   { id: 'repos', label: 'Repositories', num: 3 },
                   { id: 'azure', label: 'Azure', num: 4 },
                   { id: 'done', label: 'Finish', num: 5 }
                 ].map((s, idx) => {
                    let state = 'todo';
                    if (idx < activeStep) state = 'done';
                    else if (idx === activeStep) state = 'current';
                    
                    const isActive = state === 'done' || state === 'current';
                    
                    return (
                      <div key={s.id} className="ob-page-step">
                        <div className={`ob-page-step-circle ${isActive ? 'ob-page-step-circle-active' : 'ob-page-step-circle-inactive'}`}>
                          {s.num}
                        </div>
                        <div className={`ob-page-step-label ${isActive ? 'ob-page-step-label-active' : 'ob-page-step-label-inactive'}`}>
                          {s.label}
                        </div>
                      </div>
                    );
                 })}
               </div>
            </div>
            
            <div className="ob-main ob-page-main">
              {panel}
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <Modal
      eyebrow="Onboarding"
      title={copy.title}
      description={copy.desc}
      onClose={onClose && !force ? close : () => undefined}
    >
      {body}
    </Modal>
  );
}
