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
        // Prefer PAT when OAuth env is missing so the primary path works.
        if (opts.github.oauth) setGhMethod("oauth");
        else setGhMethod("token");
        if (opts.azure.oauth) setAzMethod("oauth");
      })
      .catch(() => undefined);

    // Resume after GitHub OAuth callback → /onboarding?oauth=github&ok=1&project_id=
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

  const title = useMemo(() => {
    if (step === "welcome") return "Welcome to InfraLens";
    if (step === "path") return "Choose how to start";
    if (step === "github") return "Connect GitHub";
    if (step === "repos") return "Select repositories";
    if (step === "create-repo") return "Create a GitHub repository";
    if (step === "azure") return "Connect Azure (optional)";
    return "You're set";
  }, [step]);

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
      const repos = selected.length ? selected : [];
      if (path === "existing" && !repos.length) {
        setMessage("Select at least one repository.");
        setBusy(false);
        return;
      }
      await api(`/api/projects/${pid}`, {
        method: "PATCH",
        body: JSON.stringify({ name: projectName.trim() || "InfraLens project" }),
      });
      if (repos.length) {
        await api(`/api/projects/${pid}/repos`, {
          method: "PUT",
          body: JSON.stringify({ repos }),
        });
      }
      await api("/api/onboarding/complete", {
        method: "POST",
        body: JSON.stringify({
          path,
          project_id: pid,
          project_name: projectName.trim() || "InfraLens project",
          repos,
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

  const BackBtn = () =>
    STEP_BACK[step] || step === "azure" ? (
      <button type="button" className="modal-btn ghost" disabled={busy} onClick={goBack}>
        Back
      </button>
    ) : null;

  const body = (
      <div className={`modal-body onboarding-wizard${asPage ? " onboarding-wizard-page" : ""}`}>
        {step === "welcome" && (
          <>
            <p>
              InfraLens maps your repos and cloud accounts into gated delivery workflows with
              role-aware approvals.
            </p>
            <div className="modal-actions">
              <button type="button" className="modal-btn primary" onClick={() => setStep("path")}>
                Continue
              </button>
            </div>
          </>
        )}

        {step === "path" && (
          <>
            <label className="modal-label">
              <span>Project name</span>
              <input
                value={projectName}
                onChange={(e) => setProjectName(e.target.value)}
                placeholder="platform-security"
              />
            </label>
            <div className="onboard-paths">
              <button
                type="button"
                className={`onboard-path${path === "existing" ? " active" : ""}`}
                onClick={() => setPath("existing")}
              >
                <strong>Existing GitHub repo</strong>
                <span>Connect and select repositories you already have.</span>
              </button>
              <button
                type="button"
                className={`onboard-path${path === "new" ? " active" : ""}`}
                onClick={() => setPath("new")}
              >
                <strong>Create new GitHub repo</strong>
                <span>InfraLens creates a repo on your account, then links the project.</span>
              </button>
            </div>
            <div className="modal-actions">
              <BackBtn />
              <button type="button" className="modal-btn primary" onClick={() => setStep("github")}>
                Continue
              </button>
            </div>
          </>
        )}

        {step === "github" && (
          <>
            <div className="auth-toggle">
              <button
                type="button"
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
                className={ghMethod === "oauth" ? "active" : ""}
                onClick={() => {
                  setGhMethod("oauth");
                  setMessage("");
                }}
              >
                GitHub SSO / OAuth
              </button>
            </div>
            {ghMethod === "token" ? (
              <>
                <label className="modal-label">
                  <span>GitHub username</span>
                  <input value={ghUser} onChange={(e) => setGhUser(e.target.value)} />
                </label>
                <label className="modal-label">
                  <span>Personal access token</span>
                  <input
                    type="password"
                    value={ghToken}
                    onChange={(e) => setGhToken(e.target.value)}
                  />
                </label>
                <div className="modal-actions">
                  <BackBtn />
                  <button
                    type="button"
                    className="modal-btn primary"
                    disabled={busy || !ghToken}
                    onClick={() => void connectGithubPat()}
                  >
                    {busy ? "Validating…" : "Connect & continue"}
                  </button>
                </div>
              </>
            ) : (
              <>
                {!authOptions?.github.oauth && (
                  <p className="empty-note">
                    {authOptions?.github.oauth_note ||
                      "OAuth app credentials are not in .env yet. You can still use a personal access token."}
                  </p>
                )}
                <div className="modal-actions">
                  <BackBtn />
                  <button
                    type="button"
                    className="modal-btn primary"
                    disabled={busy}
                    onClick={() => void startGithubOauth()}
                  >
                    {busy ? "Opening GitHub…" : "Continue with GitHub SSO"}
                  </button>
                </div>
              </>
            )}
            {ghIdentity && <div className="form-msg">Connected as {ghIdentity}</div>}
          </>
        )}

        {step === "repos" && (
          <>
            <label className="modal-label">
              <span>Search repositories</span>
              <input
                type="search"
                value={repoSearch}
                onChange={(e) => setRepoSearch(e.target.value)}
                placeholder="Filter by name…"
                autoFocus
              />
            </label>
            <div className="repo-picker">
              {!repos.length ? (
                <div className="empty-note">No repositories found for this token.</div>
              ) : !filteredRepos.length ? (
                <div className="empty-note">No repositories match “{repoSearch.trim()}”.</div>
              ) : (
                filteredRepos.map((repo) => {
                  const checked = selected.includes(repo.full_name);
                  return (
                    <label key={repo.full_name} className="repo-row">
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
                      <span>{repo.full_name}</span>
                      {repo.private ? <em>private</em> : <em>public</em>}
                    </label>
                  );
                })
              )}
            </div>
            {selected.length > 0 && (
              <div className="empty-note">{selected.length} selected</div>
            )}
            <div className="modal-actions">
              <BackBtn />
              <button type="button" className="modal-btn ghost" onClick={() => void loadRepos()}>
                Refresh
              </button>
              <button
                type="button"
                className="modal-btn primary"
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
            <label className="modal-label">
              <span>Repository name</span>
              <input value={newRepoName} onChange={(e) => setNewRepoName(e.target.value)} />
            </label>
            <label className="modal-label">
              <span>Organisation (optional)</span>
              <input value={newRepoOrg} onChange={(e) => setNewRepoOrg(e.target.value)} />
            </label>
            <label className="repo-row">
              <input
                type="checkbox"
                checked={newRepoPrivate}
                onChange={(e) => setNewRepoPrivate(e.target.checked)}
              />
              <span>Private repository</span>
            </label>
            <div className="modal-actions">
              <BackBtn />
              <button
                type="button"
                className="modal-btn primary"
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
            <div className="auth-toggle">
              <button
                type="button"
                className={azMethod === "client_secret" ? "active" : ""}
                onClick={() => setAzMethod("client_secret")}
              >
                Client secret (SP)
              </button>
              <button
                type="button"
                className={azMethod === "oauth" ? "active" : ""}
                onClick={() => setAzMethod("oauth")}
              >
                Azure OAuth
              </button>
            </div>
            {authOptions?.azure.oauth_note && azMethod === "oauth" && (
              <div className="form-msg">{authOptions.azure.oauth_note}</div>
            )}
            {azMethod === "client_secret" && (
              <>
                {(["tenant_id", "client_id", "client_secret", "subscription_id"] as const).map(
                  (field) => (
                    <label className="modal-label" key={field}>
                      <span>{field.replace(/_/g, " ")}</span>
                      <input
                        type={field.includes("secret") ? "password" : "text"}
                        value={azure[field]}
                        onChange={(e) => setAzure((cur) => ({ ...cur, [field]: e.target.value }))}
                      />
                    </label>
                  ),
                )}
              </>
            )}
            <div className="modal-actions">
              <BackBtn />
              <button type="button" className="modal-btn ghost" onClick={() => setStep("done")}>
                Skip for now
              </button>
              <button
                type="button"
                className="modal-btn primary"
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
            <p>Project is ready. You can start delivery (docs → architecture → Terraform) next.</p>
            <div className="modal-actions">
              <BackBtn />
              <button
                type="button"
                className="modal-btn primary"
                disabled={busy}
                onClick={() => void finish()}
              >
                {busy ? "Finishing…" : "Open project"}
              </button>
            </div>
          </>
        )}

        {message && <div className="form-msg error">{message}</div>}
      </div>
  );

  if (asPage) {
    return (
      <section className="onboarding-card" aria-labelledby="onboarding-title">
        <div className="modal-accent" />
        <div className="modal-head">
          <span className="modal-eyebrow">Onboarding</span>
          <h1 id="onboarding-title" className="modal-title">
            {title}
          </h1>
          <p className="modal-desc">
            Connect GitHub (OAuth or PAT), choose existing or new repo, optionally connect Azure.
          </p>
        </div>
        {body}
      </section>
    );
  }

  return (
    <Modal
      eyebrow="Onboarding"
      title={title}
      description="Connect GitHub (OAuth or PAT), choose existing or new repo, optionally connect Azure."
      onClose={onClose && !force ? close : () => undefined}
    >
      {body}
    </Modal>
  );
}
