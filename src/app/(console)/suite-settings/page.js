"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { PageHead, Panel, Pill } from "@/components/ui";
import { dangerBtn, fieldClass, ghostBtn, primaryBtn, SuiteDown, SuiteGate, SuiteProjectBar, useSuiteProject } from "@/components/suite/SuiteScreen";
import { suiteJson } from "@/lib/suite";

const PROVIDERS = {
  aws: {
    label: "AWS",
    method: "access_key",
    fields: [
      ["access_key_id", "Access key ID", "text"],
      ["secret_access_key", "Secret access key", "password"],
      ["session_token", "Session token", "password"],
      ["region", "Region", "text"],
      ["role_arn", "Role ARN", "text"],
      ["external_id", "External ID", "text"],
    ],
  },
  github: {
    label: "GitHub",
    method: "token",
    fields: [
      ["username", "Username", "text"],
      ["token", "Personal access token", "password"],
    ],
  },
};

function ProviderForm({ provider, projectId, status, onChanged }) {
  const spec = PROVIDERS[provider];
  const [fields, setFields] = useState({});
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function save(event) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      await suiteJson(`/api/projects/${projectId}/connections/${provider}`, {
        method: "PUT",
        body: { method: spec.method, fields },
      });
      setFields({});
      setMessage("Connected.");
      onChanged();
    } catch (err) {
      setMessage(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    setBusy(true);
    setMessage("");
    try {
      await suiteJson(`/api/projects/${projectId}/connections/${provider}`, { method: "DELETE" });
      setMessage("Disconnected.");
      onChanged();
    } catch (err) {
      setMessage(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function oauth() {
    setBusy(true);
    setMessage("");
    try {
      const result = await suiteJson(`/api/providers/${provider}/oauth/start?project_id=${encodeURIComponent(projectId)}`);
      if (result.authorize_url) window.location.href = result.authorize_url;
    } catch (err) {
      setMessage(err.message);
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} className="rounded-2xl border border-line p-3">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">{spec.label}</h3>
        <Pill tone={status?.connected ? "ok" : "muted"}>{status?.connected ? "connected" : "not connected"}</Pill>
      </div>
      {status?.identity && <p className="mb-2 text-xs text-muted">{[status.method, status.identity, status.hint].filter(Boolean).join(" · ")}</p>}
      <div className="grid gap-3 md:grid-cols-2">
        {spec.fields.map(([name, label, type]) => (
          <label key={name} className="text-xs font-semibold text-muted">
            {label}
            <input
              type={type}
              className={fieldClass}
              value={fields[name] || ""}
              autoComplete="off"
              onChange={(event) => setFields((current) => ({ ...current, [name]: event.target.value }))}
            />
          </label>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="submit" className={primaryBtn} disabled={busy || !projectId}>Connect</button>
        {provider === "github" && (
          <button type="button" className={ghostBtn} disabled={busy || !projectId} onClick={() => void oauth()}>
            GitHub OAuth
          </button>
        )}
        {status?.connected && (
          <button type="button" className={dangerBtn} disabled={busy} onClick={() => void disconnect()}>
            Disconnect
          </button>
        )}
      </div>
      {message && <p className="mt-2 text-sm text-muted">{message}</p>}
    </form>
  );
}

export function SuiteSettingsBody() {
  const project = useSuiteProject();
  const [azure, setAzure] = useState({ endpoint: "", api_key: "", deployment: "gpt-4o", api_version: "2024-10-21" });
  const [azureNote, setAzureNote] = useState("");
  const [editable, setEditable] = useState(false);
  const [connections, setConnections] = useState([]);
  const [error, setError] = useState("");

  const loadConnections = useCallback(async (id) => {
    if (!id) return;
    const list = await suiteJson(`/api/projects/${id}/connections`);
    setConnections(Array.isArray(list) ? list : []);
  }, []);

  useEffect(() => {
    suiteJson("/api/config/azure-openai")
      .then((data) => {
        setAzure((current) => ({
          ...current,
          endpoint: data.endpoint || "",
          deployment: data.deployment || current.deployment,
          api_version: data.api_version || current.api_version,
          api_key: "",
        }));
        setEditable(Boolean(data.editable));
        setAzureNote(data.note || (data.configured ? "A platform key is already stored." : ""));
      })
      .catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    if (!project.projectId) return undefined;
    let cancel = false;
    const timer = window.setTimeout(() => {
      loadConnections(project.projectId).catch((err) => {
        if (!cancel) setError(err.message);
      });
    }, 0);
    return () => {
      cancel = true;
      window.clearTimeout(timer);
    };
  }, [loadConnections, project.projectId]);

  async function saveAzure(event) {
    event.preventDefault();
    setError("");
    try {
      const saved = await suiteJson("/api/config/azure-openai", {
        method: "PUT",
        body: {
          endpoint: azure.endpoint,
          api_key: azure.api_key,
          deployment: azure.deployment,
          api_version: azure.api_version,
        },
      });
      setAzure((current) => ({ ...current, api_key: "", endpoint: saved.endpoint || current.endpoint }));
      setAzureNote("Saved.");
    } catch (err) {
      setError(err.message);
    }
  }

  if (project.down) return <SuiteDown />;
  const connection = (name) => connections.find((item) => item.provider === name);

  return (
    <div className="space-y-4">
      <PageHead
        eyebrow="Agentic"
        title="Suite settings"
        description="Platform Azure OpenAI for chat and skills, plus AWS and GitHub on the skills project. The organization app registration on Organization still reads the Azure estate."
        action={
          <SuiteProjectBar loading={project.loading} loadError={project.error}
            projects={project.projects}
            projectId={project.projectId}
            onChange={project.selectProject}
            onCreated={(created) => {
              project.setProjects((current) => [...current, created]);
              project.selectProject(created.id);
            }}
          />
        }
      />
      {error && <p className="text-sm text-danger">{error}</p>}
      {project.error && <p className="text-sm text-danger">{project.error}</p>}
      <Panel title="Azure OpenAI">
        <p className="mb-3 text-sm text-muted">{azureNote || "Super Admin can edit the platform model. The key is not sent back to the browser."}</p>
        <form className="grid gap-3 md:grid-cols-2" onSubmit={saveAzure}>
          <label className="text-xs font-semibold text-muted md:col-span-2">Endpoint<input className={fieldClass} value={azure.endpoint} onChange={(event) => setAzure({ ...azure, endpoint: event.target.value })} disabled={!editable} /></label>
          <label className="text-xs font-semibold text-muted">API key<input type="password" autoComplete="new-password" className={fieldClass} value={azure.api_key} onChange={(event) => setAzure({ ...azure, api_key: event.target.value })} disabled={!editable} /></label>
          <label className="text-xs font-semibold text-muted">Deployment<input className={fieldClass} value={azure.deployment} onChange={(event) => setAzure({ ...azure, deployment: event.target.value })} disabled={!editable} /></label>
          <label className="text-xs font-semibold text-muted">API version<input className={fieldClass} value={azure.api_version} onChange={(event) => setAzure({ ...azure, api_version: event.target.value })} disabled={!editable} /></label>
          <button type="submit" className={primaryBtn} disabled={!editable}>Save Azure OpenAI</button>
        </form>
      </Panel>
      <Panel title="Cloud connections">
        <div className="grid gap-3 lg:grid-cols-2">
          <ProviderForm provider="aws" projectId={project.projectId} status={connection("aws")} onChanged={() => void loadConnections(project.projectId)} />
          <ProviderForm provider="github" projectId={project.projectId} status={connection("github")} onChanged={() => void loadConnections(project.projectId)} />
        </div>
      </Panel>
    </div>
  );
}

export default function SuiteSettingsPage() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/settings");
  }, [router]);
  return null;
}
