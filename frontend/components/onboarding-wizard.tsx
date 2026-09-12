"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { Modal } from "./modal";
import { ThemeToggle } from "./theme-toggle";

type PathId = "existing" | "new";
type Step =
  | "welcome"
  | "path"
  | "github"
  | "repos"
  | "create-repo"
  | "cloud"
  | "done";

type CloudProvider = "azure" | "aws";

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
  cloud: "repos",
  done: "cloud",
};

const FLOW_STEPS: { id: Step; label: string }[] = [
  { id: "welcome", label: "Welcome" },
  { id: "path", label: "Project" },
  { id: "github", label: "GitHub" },
  { id: "repos", label: "Repos" },
  { id: "cloud", label: "Cloud" },
  { id: "done", label: "Done" },
];

function stepIndex(step: Step, path: PathId): number {
  if (step === "welcome") return 0;
  if (step === "path") return 1;
  if (step === "github") return 2;
  if (step === "repos" || step === "create-repo") return 3;
  if (step === "cloud") return 4;
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

function IconAws({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M6.8 10.2c0 .4.05.7.14 1 .1.3.23.55.4.75l-.9.45c-.1-.18-.2-.4-.28-.66A4.1 4.1 0 0 1 6 10.2c0-.55.1-1 .28-1.4.19-.4.45-.74.78-1.02.33-.28.72-.5 1.16-.64.45-.15.93-.22 1.45-.22.55 0 1.04.08 1.47.24.43.15.8.38 1.1.67.3.3.53.66.69 1.08.16.42.24.9.24 1.42v.86H7.35c.05.62.26 1.1.62 1.44.36.34.85.5 1.47.5.4 0 .76-.05 1.08-.16.32-.1.62-.26.9-.46l.4.86a4.3 4.3 0 0 1-1.12.55c-.42.14-.9.2-1.42.2-.6 0-1.13-.1-1.6-.28a3.4 3.4 0 0 1-1.2-.8 3.5 3.5 0 0 1-.75-1.26 4.5 4.5 0 0 1-.25-1.54Zm4.1-.55c0-.35-.06-.65-.18-.9a1.7 1.7 0 0 0-.5-.65 2 2 0 0 0-.75-.38 3.2 3.2 0 0 0-.94-.12c-.7 0-1.25.18-1.66.54-.4.35-.65.84-.73 1.5h4.76ZM13.6 14.5V6.9h1.05v.7c.2-.25.45-.46.75-.62.3-.16.65-.24 1.05-.24.4 0 .76.08 1.08.24.32.16.6.4.82.7.23.3.4.68.53 1.12.12.44.18.95.18 1.52 0 .56-.06 1.06-.18 1.5-.13.44-.3.8-.54 1.1a2.4 2.4 0 0 1-.85.7c-.33.16-.7.24-1.1.24-.38 0-.72-.08-1-.24a2 2 0 0 1-.72-.66v2.46h-1.07Zm3.05-3.18c0-.38-.05-.72-.14-1.02a2 2 0 0 0-.4-.76 1.7 1.7 0 0 0-.64-.48 1.9 1.9 0 0 0-.82-.17c-.28 0-.54.05-.78.16-.24.1-.45.26-.62.46v3.5c.18.2.4.36.64.47.24.1.5.16.78.16.3 0 .56-.06.8-.17.23-.12.43-.28.6-.5.16-.22.28-.5.37-.82.08-.32.12-.68.12-.08Z" />
      <path d="M4.2 16.4c1.7 1.25 3.7 1.88 5.95 1.88 2.4 0 4.55-.7 6.45-2.1.18-.13.35.1.2.28-1.55 2.05-3.95 3.22-6.65 3.22-2.55 0-4.9-1.05-6.6-2.8-.14-.14.05-.33.25-.18.13.1.27.2.4.3Z" />
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
  const [aws, setAws] = useState({
    access_key_id: "",
    secret_access_key: "",
    region: "us-east-1",
  });
  const [cloudProvider, setCloudProvider] = useState<CloudProvider>("azure");
  const [azureConnected, setAzureConnected] = useState(false);
  const [awsConnected, setAwsConnected] = useState(false);
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
        desc: "Connect GitHub, map repositories, and optionally link Azure and/or AWS — then open gated delivery workflows.",
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
    if (step === "cloud") {
      return {
        title: "Connect cloud provider",
        desc: "Optional — link Azure and/or AWS for cloud-aware delivery. Skip if you only need GitHub for now.",
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
    if (step === "cloud") {
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
      setStep("cloud");
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

  const connectAws = async () => {
    setBusy(true);
    setMessage("");
    try {
      const pid = await ensureProject();
      if (!aws.access_key_id.trim() || !aws.secret_access_key.trim()) {
        setMessage("Access key ID and secret access key are required.");
        setBusy(false);
        return;
      }
      await api(`/api/projects/${pid}/connections/aws`, {
        method: "PUT",
        body: JSON.stringify({
          method: "access_key",
          fields: {
            access_key_id: aws.access_key_id.trim(),
            secret_access_key: aws.secret_access_key,
            region: aws.region.trim() || "us-east-1",
          },
        }),
      });
      setAwsConnected(true);
      setMessage("AWS connected.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "AWS connect failed");
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
          aws_connected: awsConnected,
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

  const canGoBack = Boolean(STEP_BACK[step] || step === "cloud");

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
                <div className="ob-welcome-title">Connect cloud (Optional)</div>
                <div className="ob-welcome-desc">Link Azure and/or AWS for cloud-aware delivery.</div>
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
                setStep("cloud");
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

      {step === "cloud" && (
        <>
          <div className="ob-toggle" role="tablist" aria-label="Cloud provider">
            <button
              type="button"
              role="tab"
              aria-selected={cloudProvider === "azure"}
              className={cloudProvider === "azure" ? "active" : ""}
              onClick={() => {
                setCloudProvider("azure");
                setMessage("");
              }}
            >
              Azure{azureConnected ? " ✓" : ""}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={cloudProvider === "aws"}
              className={cloudProvider === "aws" ? "active" : ""}
              onClick={() => {
                setCloudProvider("aws");
                setMessage("");
              }}
            >
              AWS{awsConnected ? " ✓" : ""}
            </button>
          </div>

          {cloudProvider === "azure" ? (
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
            </>
          ) : (
            <>
              <div className="ob-sso-panel">
                <IconAws className="ob-sso-mark" />
                <p>Enter an IAM access key. You can also connect Azure on the other tab — either or both is fine.</p>
              </div>
              <div className="ob-fields ob-fields-grid">
                {([
                  ["access_key_id", "Access key ID", "text"],
                  ["secret_access_key", "Secret access key", "password"],
                  ["region", "Region", "text"],
                ] as const).map(([field, label, inputType]) => (
                  <label className="ob-field" key={field}>
                    <span>{label}</span>
                    <input
                      type={inputType}
                      value={aws[field]}
                      onChange={(e) => setAws((cur) => ({ ...cur, [field]: e.target.value }))}
                      autoComplete="off"
                      placeholder={field === "region" ? "us-east-1" : undefined}
                    />
                  </label>
                ))}
              </div>
            </>
          )}

          {(azureConnected || awsConnected) ? (
            <div className="ob-status ok">
              {[
                azureConnected ? "Azure connected" : null,
                awsConnected ? "AWS connected" : null,
              ]
                .filter(Boolean)
                .join(" · ")}
            </div>
          ) : null}

          <div className="ob-actions">
            {canGoBack ? (
              <button type="button" className="ob-btn ghost" disabled={busy} onClick={goBack}>
                Back
              </button>
            ) : null}
            <button type="button" className="ob-btn ghost" onClick={() => setStep("done")}>
              {azureConnected || awsConnected ? "Continue" : "Skip for now"}
            </button>
            <button
              type="button"
              className="ob-btn primary"
              disabled={busy}
              onClick={() =>
                void (cloudProvider === "azure" ? connectAzure() : connectAws())
              }
            >
              {busy
                ? "Saving…"
                : cloudProvider === "azure"
                  ? "Connect Azure"
                  : "Connect AWS"}
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
                {awsConnected ? " · AWS connected" : ""}
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
            <ThemeToggle variant="header" />
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
                   { id: 'cloud', label: 'Cloud', num: 4 },
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
