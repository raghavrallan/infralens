const settings = {
  projects: [],
  projectId: localStorage.getItem("projectId") || "default",
  repos: {
    available: [],
    selected: new Set(),
    org: "all",
    search: "",
  },
};

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s == null ? "" : s;
  return div.innerHTML;
}

function fmtDate(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString();
  } catch (e) {
    return iso;
  }
}

/* ---------- Projects ---------- */

async function loadProjects() {
  try {
    const res = await fetch("/api/projects");
    settings.projects = await res.json();
  } catch (e) {
    settings.projects = [{ id: "default", name: "Default project" }];
  }
  if (!settings.projects.some((p) => p.id === settings.projectId)) {
    settings.projectId = settings.projects.length ? settings.projects[0].id : "default";
  }
  localStorage.setItem("projectId", settings.projectId);
  const select = document.getElementById("project-select");
  select.innerHTML = settings.projects
    .map(
      (p) =>
        `<option value="${p.id}" ${p.id === settings.projectId ? "selected" : ""}>${escapeHtml(
          p.name
        )}</option>`
    )
    .join("");
  updateDeleteButton();
}

function updateDeleteButton() {
  const btn = document.getElementById("delete-project-btn");
  btn.disabled = settings.projectId === "default";
  btn.title = settings.projectId === "default" ? "The default project cannot be deleted" : "";
}

async function switchProject(id) {
  settings.projectId = id;
  localStorage.setItem("projectId", id);
  updateDeleteButton();
  await loadConnections();
  await loadRepos();
}

function wireProjectControls() {
  const select = document.getElementById("project-select");
  const msg = document.getElementById("project-msg");

  select.addEventListener("change", () => switchProject(select.value));

  document.getElementById("new-project-btn").addEventListener("click", async () => {
    const name = await Modal.prompt({
      eyebrow: "Workspace",
      title: "New project",
      description: "Give a client or product its own credentials, repos and chats.",
      label: "Project name",
      placeholder: "e.g. Seye, TG…",
      confirmLabel: "Create project",
    });
    if (!name) return;
    const res = await fetch("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name.trim() }),
    });
    const project = await res.json();
    await loadProjects();
    document.getElementById("project-select").value = project.id;
    await switchProject(project.id);
    msg.textContent = `Created project “${project.name}”.`;
    msg.className = "form-msg muted";
  });

  document.getElementById("rename-project-btn").addEventListener("click", async () => {
    const current = settings.projects.find((p) => p.id === settings.projectId);
    const name = await Modal.prompt({
      eyebrow: "Workspace",
      title: "Rename project",
      label: "Project name",
      value: current ? current.name : "",
      confirmLabel: "Save name",
    });
    if (!name) return;
    await fetch(`/api/projects/${settings.projectId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name.trim() }),
    });
    await loadProjects();
  });

  document.getElementById("delete-project-btn").addEventListener("click", async () => {
    if (settings.projectId === "default") return;
    const current = settings.projects.find((p) => p.id === settings.projectId);
    const ok = await Modal.confirm({
      eyebrow: "Danger zone",
      title: `Delete “${current ? current.name : "project"}”?`,
      message:
        "This permanently removes the project, its connections and all its chats. This cannot be undone.",
      confirmLabel: "Delete project",
      danger: true,
    });
    if (!ok) return;
    await fetch(`/api/projects/${settings.projectId}`, { method: "DELETE" });
    settings.projectId = "default";
    localStorage.setItem("projectId", "default");
    await loadProjects();
    await switchProject("default");
  });
}

/* ---------- Azure OpenAI (global) ---------- */

async function loadOpenAiStatus() {
  const pill = document.getElementById("openai-pill");
  const form = document.getElementById("openai-form");
  try {
    const res = await fetch("/api/config/azure-openai");
    const data = await res.json();
    if (data.configured) {
      pill.textContent = "connected";
      pill.className = "pill ok";
    } else {
      pill.textContent = "not configured";
      pill.className = "pill off";
    }
    form.endpoint.value = data.endpoint || "";
    form.deployment.value = data.deployment || "";
    form.api_version.value = data.api_version || "";
    if (data.has_key) {
      form.api_key.placeholder = "•••••••• (stored — leave blank to keep)";
    }
  } catch (e) {
    pill.textContent = "unavailable";
    pill.className = "pill off";
  }
}

function wireOpenAiForm() {
  const form = document.getElementById("openai-form");
  const msg = document.getElementById("openai-msg");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    msg.textContent = "Saving…";
    msg.className = "form-msg";
    try {
      const res = await fetch("/api/config/azure-openai", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          endpoint: form.endpoint.value.trim(),
          api_key: form.api_key.value,
          deployment: form.deployment.value.trim() || "gpt-4o",
          api_version: form.api_version.value.trim() || "2024-10-21",
        }),
      });
      const data = await res.json();
      form.api_key.value = "";
      msg.textContent = data.configured
        ? "Saved. Azure OpenAI is configured."
        : "Saved, but endpoint or key is still missing.";
      await loadOpenAiStatus();
    } catch (err) {
      msg.textContent = "Failed to save configuration.";
      msg.className = "form-msg error";
    }
  });
}

/* ---------- Provider connections (per project) ---------- */

function applyStatus(card, status) {
  const pill = card.querySelector('[data-role="pill"]');
  const disconnectBtn = card.querySelector('[data-role="disconnect"]');
  const msg = card.querySelector('[data-role="msg"]');
  msg.textContent = "";

  if (status && status.connected) {
    const bits = [status.method];
    if (status.identity) bits.push(status.identity);
    if (status.hint) bits.push(status.hint);
    pill.textContent = `connected · ${bits.filter(Boolean).join(" · ")}`;
    pill.className = "pill ok";
    disconnectBtn.hidden = false;
    if (status.connected_at) {
      msg.textContent = `Connected ${fmtDate(status.connected_at)}`;
      msg.className = "form-msg muted";
    }
  } else {
    pill.textContent = "not connected";
    pill.className = "pill off";
    disconnectBtn.hidden = true;
  }
}

function activeMethod(card) {
  const tab = card.querySelector(".method-tab.active");
  return tab ? tab.dataset.method : null;
}

function showGroup(card, method) {
  card.querySelectorAll(".fields").forEach((group) => {
    group.hidden = group.dataset.group !== method;
  });
  card.querySelectorAll(".method-tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.method === method);
  });
}

function collectFields(card, method) {
  const group = card.querySelector(`.fields[data-group="${method}"]`);
  const fields = {};
  if (!group) return fields;
  group.querySelectorAll("input").forEach((input) => {
    if (input.value.trim()) fields[input.name] = input.value.trim();
  });
  return fields;
}

function wireProvider(card) {
  const provider = card.dataset.provider;
  const form = card.querySelector('[data-role="form"]');
  const msg = card.querySelector('[data-role="msg"]');
  const disconnectBtn = card.querySelector('[data-role="disconnect"]');

  card.querySelectorAll(".method-tab").forEach((tab) => {
    tab.addEventListener("click", () => showGroup(card, tab.dataset.method));
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const method = activeMethod(card);
    const fields = collectFields(card, method);
    if (Object.keys(fields).length === 0) {
      msg.textContent = "Please fill in at least one field.";
      msg.className = "form-msg error";
      return;
    }
    msg.textContent = "Saving…";
    msg.className = "form-msg muted";
    try {
      const res = await fetch(
        `/api/projects/${settings.projectId}/connections/${provider}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ method, fields }),
        }
      );
      const status = await res.json();
      applyStatus(card, status);
      form.querySelectorAll('input[type="password"]').forEach((i) => (i.value = ""));
      if (provider === "github") loadRepos();
    } catch (err) {
      msg.textContent = "Failed to save connection.";
      msg.className = "form-msg error";
    }
  });

  disconnectBtn.addEventListener("click", async () => {
    try {
      const res = await fetch(
        `/api/projects/${settings.projectId}/connections/${provider}`,
        { method: "DELETE" }
      );
      const status = await res.json();
      applyStatus(card, status);
      if (provider === "github") loadRepos();
    } catch (err) {
      msg.textContent = "Failed to disconnect.";
      msg.className = "form-msg error";
    }
  });
}

async function loadConnections() {
  try {
    const res = await fetch(`/api/projects/${settings.projectId}/connections`);
    const statuses = await res.json();
    const byProvider = {};
    statuses.forEach((s) => (byProvider[s.provider] = s));
    document.querySelectorAll(".provider").forEach((card) => {
      applyStatus(card, byProvider[card.dataset.provider]);
    });
  } catch (e) {
    /* ignore */
  }
}

/* ---------- Repository mapping (per project) ---------- */

function orgOf(fullName) {
  const i = fullName.indexOf("/");
  return i > 0 ? fullName.slice(0, i) : fullName;
}

function filteredRepos() {
  const { available, org, search } = settings.repos;
  const q = search.trim().toLowerCase();
  return available.filter((name) => {
    if (org !== "all" && orgOf(name) !== org) return false;
    if (q && !name.toLowerCase().includes(q)) return false;
    return true;
  });
}

function updateReposPill() {
  const pill = document.getElementById("repos-pill");
  const { available, selected } = settings.repos;
  pill.textContent = `${selected.size} of ${available.length} mapped`;
  pill.className = selected.size ? "pill ok" : "pill off";
}

function renderOrgFilter() {
  const select = document.getElementById("repos-org");
  const orgs = Array.from(new Set(settings.repos.available.map(orgOf))).sort();
  select.innerHTML =
    `<option value="all">All organisations (${settings.repos.available.length})</option>` +
    orgs
      .map((o) => {
        const count = settings.repos.available.filter((n) => orgOf(n) === o).length;
        return `<option value="${escapeHtml(o)}" ${
          o === settings.repos.org ? "selected" : ""
        }>${escapeHtml(o)} (${count})</option>`;
      })
      .join("");
}

function renderRepoList() {
  const list = document.getElementById("repos-list");
  const rows = filteredRepos();
  if (!rows.length) {
    list.innerHTML = `<p class="muted small">No repositories match this filter.</p>`;
    return;
  }
  list.innerHTML = rows
    .map(
      (name) => `
      <label class="repo-item">
        <input type="checkbox" value="${escapeHtml(name)}" ${
        settings.repos.selected.has(name) ? "checked" : ""
      } />
        <span>${escapeHtml(name)}</span>
      </label>`
    )
    .join("");
  list.querySelectorAll("input[type=checkbox]").forEach((input) => {
    input.addEventListener("change", () => {
      if (input.checked) settings.repos.selected.add(input.value);
      else settings.repos.selected.delete(input.value);
      updateReposPill();
    });
  });
}

async function loadRepos() {
  const pill = document.getElementById("repos-pill");
  const list = document.getElementById("repos-list");
  const toolbar = document.getElementById("repos-toolbar");
  const msg = document.getElementById("repos-msg");
  msg.textContent = "";
  toolbar.hidden = true;
  list.innerHTML = `<p class="muted small">Loading…</p>`;
  try {
    const res = await fetch(`/api/projects/${settings.projectId}/repos`);
    const data = await res.json();

    if (!data.github_connected) {
      pill.textContent = "github not connected";
      pill.className = "pill off";
      list.innerHTML = `<p class="muted small">Connect GitHub above to list repositories.</p>`;
      return;
    }
    if (data.error) {
      pill.textContent = "error";
      pill.className = "pill off";
      list.innerHTML = `<p class="form-msg error">${escapeHtml(data.error)}</p>`;
      return;
    }

    settings.repos.available = data.available || [];
    settings.repos.selected = new Set(data.mapped || []);
    settings.repos.org = "all";
    settings.repos.search = "";
    document.getElementById("repos-search").value = "";

    if (!settings.repos.available.length) {
      pill.textContent = "0 of 0 mapped";
      pill.className = "pill off";
      list.innerHTML = `<p class="muted small">No repositories visible to this token.</p>`;
      return;
    }
    toolbar.hidden = false;
    renderOrgFilter();
    renderRepoList();
    updateReposPill();
  } catch (e) {
    pill.textContent = "unavailable";
    pill.className = "pill off";
    list.innerHTML = `<p class="form-msg error">Failed to load repositories.</p>`;
  }
}

function wireReposCard() {
  document.getElementById("refresh-repos-btn").addEventListener("click", loadRepos);

  document.getElementById("repos-org").addEventListener("change", (e) => {
    settings.repos.org = e.target.value;
    renderRepoList();
  });

  document.getElementById("repos-search").addEventListener("input", (e) => {
    settings.repos.search = e.target.value;
    renderRepoList();
  });

  document.getElementById("repos-select-all").addEventListener("click", () => {
    filteredRepos().forEach((name) => settings.repos.selected.add(name));
    renderRepoList();
    updateReposPill();
  });

  document.getElementById("repos-clear").addEventListener("click", () => {
    filteredRepos().forEach((name) => settings.repos.selected.delete(name));
    renderRepoList();
    updateReposPill();
  });

  document.getElementById("save-repos-btn").addEventListener("click", async () => {
    const msg = document.getElementById("repos-msg");
    const repos = Array.from(settings.repos.selected);
    msg.textContent = "Saving…";
    msg.className = "form-msg muted";
    try {
      await fetch(`/api/projects/${settings.projectId}/repos`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repos }),
      });
      msg.textContent = repos.length
        ? `Mapped ${repos.length} repositor${repos.length === 1 ? "y" : "ies"} to this project.`
        : "Cleared mapping — this project can see every repo the token allows.";
      msg.className = "form-msg muted";
    } catch (e) {
      msg.textContent = "Failed to save repositories.";
      msg.className = "form-msg error";
    }
  });
}

/* ---------- Boot ---------- */

document.querySelectorAll(".provider").forEach(wireProvider);
wireOpenAiForm();
wireProjectControls();
wireReposCard();

async function boot() {
  await loadProjects();
  await loadConnections();
  await loadRepos();
}

loadOpenAiStatus();
boot();
