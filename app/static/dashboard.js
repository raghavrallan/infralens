const state = {
  projectId: localStorage.getItem("projectId") || "default",
  projects: [],
  catalog: { skills: [], modules: [] },
  severity: "",
  status: "open",
  module: "",
  autoRefresh: true,
};

const els = {
  projectSelect: document.getElementById("project-select"),
  refreshBtn: document.getElementById("refresh-btn"),
  newWorkflowBtn: document.getElementById("new-workflow-btn"),
  tiles: document.getElementById("tiles"),
  findings: document.getElementById("findings"),
  approvals: document.getElementById("approvals"),
  approvalsCount: document.getElementById("approvals-count"),
  workflows: document.getElementById("workflows"),
  runs: document.getElementById("runs"),
  filters: document.getElementById("finding-filters"),
  statusFilters: document.getElementById("status-filters"),
  moduleFilter: document.getElementById("module-filter"),
  updatedNote: document.getElementById("updated-note"),
};

let lastUpdated = Date.now();

function markUpdated() {
  lastUpdated = Date.now();
  if (els.updatedNote) els.updatedNote.textContent = "Updated now";
}

function tickUpdatedLabel() {
  if (!els.updatedNote) return;
  const secs = Math.round((Date.now() - lastUpdated) / 1000);
  els.updatedNote.textContent =
    secs < 5 ? "Updated now" : `Updated ${timeAgo(new Date(lastUpdated).toISOString())}`;
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

function prettyName(name) {
  return (name || "")
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function timeAgo(iso) {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  const secs = Math.max(1, Math.round((Date.now() - then) / 1000));
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

function timeUntil(secs) {
  if (secs == null) return "";
  if (secs <= 0) return "expired";
  const hrs = Math.round(secs / 3600);
  if (hrs < 1) return `${Math.max(1, Math.round(secs / 60))}m left`;
  if (hrs < 48) return `${hrs}h left`;
  return `${Math.round(hrs / 24)}d left`;
}

let toastTimer = null;
function toast(message, kind) {
  let el = document.getElementById("toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "toast";
    el.className = "toast";
    document.body.appendChild(el);
  }
  el.className = `toast ${kind || ""}`;
  el.textContent = message;
  requestAnimationFrame(() => el.classList.add("show"));
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 3200);
}

async function api(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch (e) {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

/* ---------- Projects ---------- */

async function loadProjects() {
  state.projects = await api("/api/projects");
  els.projectSelect.innerHTML = state.projects
    .map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`)
    .join("");
  if (!state.projects.some((p) => p.id === state.projectId)) {
    state.projectId = state.projects[0] ? state.projects[0].id : "default";
  }
  els.projectSelect.value = state.projectId;
}

/* ---------- Tiles ---------- */

function tile(label, value, sub, breakdown, accent) {
  return `
    <div class="tile ${accent ? `tile-${accent}` : ""}">
      <div class="tile-label">${esc(label)}</div>
      <div class="tile-value">${esc(value)}</div>
      ${sub ? `<div class="tile-sub">${esc(sub)}</div>` : ""}
      ${breakdown || ""}
    </div>`;
}

async function loadSummary() {
  const s = await api(
    `/api/dashboard/summary?project_id=${encodeURIComponent(state.projectId)}`
  );
  const sev = s.findings_by_severity || {};
  const breakdown = `
    <div class="tile-breakdown">
      <span class="sev sev-critical">${sev.critical || 0} crit</span>
      <span class="sev sev-high">${sev.high || 0} high</span>
      <span class="sev sev-medium">${sev.medium || 0} med</span>
      <span class="sev sev-low">${sev.low || 0} low</span>
    </div>`;
  const runs = s.runs_by_status || {};
  const pending = s.pending_approvals != null ? s.pending_approvals : s.needs_approval || 0;
  els.tiles.innerHTML = [
    tile("Open findings", s.open_findings || 0, "Unresolved across workflows", breakdown),
    tile(
      "Awaiting approval",
      pending,
      "Gated: human or two-person",
      "",
      pending ? "warn" : ""
    ),
    tile(
      "Workflows",
      `${s.workflows_enabled || 0}/${s.workflows_total || 0}`,
      "Enabled / total"
    ),
    tile(
      "Runs",
      (runs.succeeded || 0) + (runs.failed || 0) + (runs.running || 0) + (runs.queued || 0),
      `${runs.running || 0} running · ${runs.failed || 0} failed`,
      "",
      runs.failed ? "warn" : ""
    ),
  ].join("");
}

/* ---------- Findings ---------- */

function findingCard(f) {
  const gateClass = `gate-${f.gate_decision}`;
  return `
    <div class="finding-card sev-${esc(f.severity)} ${
    f.status === "resolved" ? "resolved" : ""
  }">
      <div class="finding-top">
        <span class="sev sev-${esc(f.severity)}">${esc(f.severity)}</span>
        <span class="gate-badge ${gateClass}" title="${esc(
    f.gate_rationale
  )}">${esc(f.gate_label)}</span>
        ${f.module_label ? `<span class="mini-pill">${esc(f.module_label)}</span>` : ""}
        ${f.status !== "open" ? `<span class="mini-pill status-${esc(f.status)}">${esc(f.status)}</span>` : ""}
      </div>
      <div class="finding-title">${esc(f.title)}</div>
      <div class="finding-meta">
        <span>${esc(prettyName(f.skill))}</span>
        ${f.resource ? `<span title="${esc(f.resource)}">${esc(f.resource)}</span>` : ""}
        ${f.category ? `<span>${esc(f.category)}</span>` : ""}
        <span>blast: ${esc(f.blast_radius)}</span>
      </div>
      <div class="finding-body">
        ${f.evidence ? `<span class="label">Evidence</span>${esc(f.evidence)}` : ""}
        ${
          f.recommended_action
            ? `<span class="label">Recommended action</span>${esc(f.recommended_action)}`
            : ""
        }
      </div>
      <div class="finding-actions">
        <button class="tiny-btn" data-explain="${esc(f.id)}">Explain in chat</button>
        ${
          f.status === "open"
            ? `<button class="tiny-btn" data-ack="${esc(f.id)}">Acknowledge</button>`
            : ""
        }
        ${
          f.status !== "resolved"
            ? `<button class="tiny-btn solid" data-resolve="${esc(f.id)}">Resolve</button>`
            : `<button class="tiny-btn" data-reopen="${esc(f.id)}">Reopen</button>`
        }
      </div>
    </div>`;
}

let findingCache = [];

async function loadFindings() {
  const q = new URLSearchParams({ project_id: state.projectId });
  if (state.severity) q.set("severity", state.severity);
  if (state.status) q.set("status", state.status);
  if (state.module) q.set("module", state.module);
  const scrollTop = els.findings.scrollTop;
  findingCache = await api(`/api/findings?${q.toString()}`);
  if (!findingCache.length) {
    els.findings.innerHTML = `<div class="empty-note">No findings match this filter. Run a workflow to populate the dashboard.</div>`;
    return;
  }
  els.findings.innerHTML = findingCache.map(findingCard).join("");
  els.findings.scrollTop = scrollTop;
}

function findingPrompt(f) {
  return [
    `Explain this finding and how to fix it safely.`,
    ``,
    `Skill: ${prettyName(f.skill)}`,
    f.resource ? `Resource: ${f.resource}` : "",
    `Severity: ${f.severity} · Gate: ${f.gate_label}`,
    `Title: ${f.title}`,
    f.evidence ? `Evidence: ${f.evidence}` : "",
    f.recommended_action ? `Recommended action: ${f.recommended_action}` : "",
  ]
    .filter(Boolean)
    .join("\n");
}

function explainInChat(id) {
  const f = findingCache.find((x) => x.id === id);
  if (!f) return;
  localStorage.setItem("projectId", state.projectId);
  localStorage.setItem("pendingPrompt", findingPrompt(f));
  window.location.href = "/";
}

async function setFindingStatus(id, status) {
  try {
    await api(`/api/findings/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    await Promise.all([loadFindings(), loadSummary(), loadApprovals()]);
  } catch (e) {
    toast(e.message, "error");
  }
}

/* ---------- Approvals ---------- */

function approvalCard(a) {
  const f = a.finding || {};
  const expiry = a.expired ? "expired" : timeUntil(a.expires_in_seconds);
  return `
    <div class="approval-card ${a.expired ? "expired" : ""}">
      <div class="approval-top">
        <span class="gate-badge gate-${esc(a.gate)}">${esc(a.gate_label)}</span>
        ${f.severity ? `<span class="sev sev-${esc(f.severity)}">${esc(f.severity)}</span>` : ""}
        <span class="approval-expiry ${a.expired ? "danger" : ""}">${esc(expiry)}</span>
      </div>
      <div class="approval-title">${esc(f.title || "Finding")}</div>
      <div class="finding-meta">
        ${f.skill ? `<span>${esc(prettyName(f.skill))}</span>` : ""}
        ${f.resource ? `<span title="${esc(f.resource)}">${esc(f.resource)}</span>` : ""}
        <span>blast: ${esc(f.blast_radius || "—")}</span>
      </div>
      ${
        f.recommended_action
          ? `<div class="approval-action"><span class="label">Proposed</span>${esc(
              f.recommended_action
            )}</div>`
          : ""
      }
      <div class="approval-note">${esc(a.gate_label)} required — approving records intent only; nothing is executed.</div>
      <div class="finding-actions">
        <button class="tiny-btn" data-approval-explain="${esc(a.id)}">Explain in chat</button>
        <button class="tiny-btn danger" data-reject="${esc(a.id)}">Reject</button>
        <button class="tiny-btn solid" data-approve="${esc(a.id)}">Approve</button>
      </div>
    </div>`;
}

let approvalCache = [];

async function loadApprovals() {
  approvalCache = await api(
    `/api/approvals?project_id=${encodeURIComponent(state.projectId)}&status=pending`
  );
  const live = approvalCache.filter((a) => !a.expired);
  els.approvalsCount.textContent = `${live.length} pending`;
  els.approvalsCount.className = `pill ${live.length ? "warn" : "off"}`;
  if (!approvalCache.length) {
    els.approvals.innerHTML = `<div class="empty-note">No approvals waiting. Change-producing findings land here, time-boxed. Nothing auto-executes on timeout.</div>`;
    return;
  }
  els.approvals.innerHTML = approvalCache.map(approvalCard).join("");
}

async function decideApproval(id, decision) {
  const a = approvalCache.find((x) => x.id === id);
  const verb = decision === "approved" ? "Approve" : "Reject";
  const ok = await window.Modal.confirm({
    eyebrow: `${verb} finding`,
    title: `${verb} this gated finding?`,
    message:
      decision === "approved"
        ? "This records intent to apply the fix and marks the finding acknowledged. Nothing is executed automatically."
        : "This closes the finding as resolved (won't fix). It is recorded as precedent.",
    confirmLabel: verb,
    danger: decision === "rejected",
  });
  if (!ok) return;
  try {
    await api(`/api/approvals/${id}/decide`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision }),
    });
    toast(`Finding ${decision}.`, "ok");
    await Promise.all([loadApprovals(), loadFindings(), loadSummary()]);
  } catch (e) {
    toast(e.message, "error");
  }
}

function explainApprovalInChat(id) {
  const a = approvalCache.find((x) => x.id === id);
  if (!a || !a.finding) return;
  localStorage.setItem("projectId", state.projectId);
  localStorage.setItem("pendingPrompt", findingPrompt(a.finding));
  window.location.href = "/";
}

/* ---------- Workflows ---------- */

function workflowCard(w) {
  const skills = (w.skills || [])
    .map((s) => `<span class="mini-pill">${esc(prettyName(s))}</span>`)
    .join("");
  const lr = w.last_run;
  const lastRun = lr
    ? `<span class="run-status ${esc(lr.status)}">${esc(lr.status)}</span> ${esc(
        timeAgo(lr.created_at)
      )}${lr.finding_count ? ` · ${lr.finding_count} findings` : ""}`
    : "never run";
  return `
    <div class="workflow-card ${w.enabled ? "" : "disabled"}">
      <div class="workflow-name">
        <span>${esc(w.name)}</span>
        <span class="run-status ${w.enabled ? "succeeded" : "queued"}">${
    w.enabled ? "on" : "off"
  }</span>
      </div>
      <div class="workflow-sub">
        ${esc(w.module_label || "Workflow")} · ${esc(w.environment)} ${
    w.schedule_cron ? `· cron ${esc(w.schedule_cron)}` : "· manual"
  }
      </div>
      <div class="workflow-skills">${skills}</div>
      <div class="workflow-last">Last: ${lastRun}</div>
      <div class="workflow-actions">
        <button class="tiny-btn solid" data-run="${esc(w.id)}">Run now</button>
        <button class="tiny-btn" data-edit="${esc(w.id)}">Edit</button>
        <button class="tiny-btn" data-toggle="${esc(w.id)}" data-enabled="${w.enabled}">${
    w.enabled ? "Disable" : "Enable"
  }</button>
        <button class="tiny-btn danger" data-del="${esc(w.id)}">Delete</button>
      </div>
    </div>`;
}

let workflowCache = [];

async function loadWorkflows() {
  workflowCache = await api(
    `/api/workflows?project_id=${encodeURIComponent(state.projectId)}`
  );
  if (!workflowCache.length) {
    els.workflows.innerHTML = `<div class="empty-note">No workflows yet. Create one to start automated diagnostics.</div>`;
    return;
  }
  els.workflows.innerHTML = workflowCache.map(workflowCard).join("");
}

async function runWorkflow(id) {
  try {
    await api(`/api/workflows/${id}/run`, { method: "POST" });
    toast("Run queued.", "ok");
    await Promise.all([loadRuns(), loadSummary()]);
    pollRuns();
  } catch (e) {
    toast(e.message, "error");
  }
}

async function toggleWorkflow(id, enabled) {
  try {
    await api(`/api/workflows/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: !enabled }),
    });
    await Promise.all([loadWorkflows(), loadSummary()]);
  } catch (e) {
    toast(e.message, "error");
  }
}

async function deleteWorkflow(id) {
  const ok = await window.Modal.confirm({
    eyebrow: "Delete workflow",
    title: "Delete this workflow?",
    message: "Its runs and findings will be removed. This cannot be undone.",
    confirmLabel: "Delete",
    danger: true,
  });
  if (!ok) return;
  try {
    await api(`/api/workflows/${id}`, { method: "DELETE" });
    await Promise.all([loadWorkflows(), loadRuns(), loadFindings(), loadSummary()]);
  } catch (e) {
    toast(e.message, "error");
  }
}

/* ---------- Runs + drill-down ---------- */

function runItem(r) {
  return `
    <button class="run-item" data-run-open="${esc(r.id)}">
      <div>
        <div>${esc(r.workflow_name || "Workflow")}</div>
        <div class="run-meta">${esc(r.trigger)} · ${timeAgo(r.created_at)}${
    r.finding_count ? ` · ${r.finding_count} findings` : ""
  }${r.error ? ` · ${esc(r.error.slice(0, 60))}` : ""}</div>
      </div>
      <span class="run-status ${esc(r.status)}">${esc(r.status)}</span>
    </button>`;
}

async function loadRuns() {
  const list = await api(
    `/api/runs?project_id=${encodeURIComponent(state.projectId)}&limit=12`
  );
  if (!list.length) {
    els.runs.innerHTML = `<div class="empty-note">No runs yet.</div>`;
    return list;
  }
  els.runs.innerHTML = list.map(runItem).join("");
  return list;
}

async function openRunModal(runId) {
  let run;
  try {
    run = await api(`/api/runs/${runId}`);
  } catch (e) {
    toast(e.message, "error");
    return;
  }
  const findings = run.findings || [];
  const body = findings.length
    ? findings.map(findingCard).join("")
    : `<div class="empty-note">This run produced no findings${
        run.error ? ` — it failed: ${esc(run.error)}` : "."
      }</div>`;
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal modal-wide" role="dialog" aria-modal="true">
      <div class="modal-accent"></div>
      <div class="modal-head">
        <span class="modal-eyebrow">${esc(run.trigger)} run · ${esc(run.status)}</span>
        <h3 class="modal-title">${esc(run.workflow_name || "Workflow run")}</h3>
        <p class="modal-desc">${esc(timeAgo(run.created_at))} · ${
    findings.length
  } finding(s)</p>
      </div>
      <div class="modal-body">
        <div class="run-findings">${body}</div>
        <div class="modal-actions">
          <button type="button" class="modal-btn primary" data-act="close">Close</button>
        </div>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  requestAnimationFrame(() => overlay.classList.add("open"));
  const close = () => {
    overlay.classList.remove("open");
    setTimeout(() => overlay.remove(), 180);
  };
  overlay.addEventListener("mousedown", (e) => {
    if (e.target === overlay) close();
  });
  overlay.querySelector('[data-act="close"]').addEventListener("click", close);
}

let pollTimer = null;

function pollRuns() {
  if (pollTimer) clearTimeout(pollTimer);
  let ticks = 0;
  const tick = async () => {
    ticks += 1;
    const list = await loadRuns();
    const active = (list || []).some(
      (r) => r.status === "queued" || r.status === "running"
    );
    if (active && ticks < 40) {
      pollTimer = setTimeout(tick, 3000);
    } else {
      await Promise.all([loadFindings(), loadSummary(), loadApprovals()]);
    }
  };
  pollTimer = setTimeout(tick, 3000);
}

/* ---------- Workflow create/edit modal ---------- */

function openWorkflowModal(existing) {
  const editing = !!existing;
  const chosen = new Set(editing ? existing.skills || [] : []);
  const skillOptions = state.catalog.skills
    .map(
      (s) => `
      <label class="modal-skill">
        <input type="checkbox" value="${esc(s.name)}" ${
        chosen.has(s.name) ? "checked" : ""
      } />
        ${esc(prettyName(s.name))}
      </label>`
    )
    .join("");
  const moduleOptions = state.catalog.modules
    .map(
      (m) =>
        `<option value="${esc(m.key)}" ${
          editing && existing.module === m.key ? "selected" : ""
        }>${esc(m.label)}</option>`
    )
    .join("");
  const envOpt = (v, label) =>
    `<option value="${v}" ${
      (editing ? existing.environment : "prod") === v ? "selected" : ""
    }>${label}</option>`;

  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true">
      <div class="modal-accent"></div>
      <div class="modal-head">
        <span class="modal-eyebrow">${editing ? "Edit workflow" : "New workflow"}</span>
        <h3 class="modal-title">${editing ? "Update this workflow" : "Automate diagnose skills"}</h3>
        <p class="modal-desc">Only read-only skills can run unattended. Pick the skills, an optional schedule, and the environment used to gate findings.</p>
      </div>
      <form class="modal-body">
        <label class="modal-label"><span>Name</span>
          <input data-field="name" type="text" placeholder="Nightly Posture Sweep" value="${
            editing ? esc(existing.name) : ""
          }" /></label>
        <label class="modal-label" style="margin-top:14px"><span>Objective</span>
          <input data-field="objective" type="text" placeholder="Review posture and drift for the connected cloud" value="${
            editing ? esc(existing.objective) : ""
          }" /></label>
        <label class="modal-label" style="margin-top:14px"><span>Module</span>
          <select data-field="module" class="modal-select">${moduleOptions}</select></label>
        <label class="modal-label" style="margin-top:14px"><span>Environment (gating)</span>
          <select data-field="environment" class="modal-select">
            ${envOpt("prod", "Production")}
            ${envOpt("staging", "Staging")}
            ${envOpt("dev", "Dev")}
          </select></label>
        <label class="modal-label" style="margin-top:14px"><span>Schedule (cron, optional)</span>
          <input data-field="schedule_cron" type="text" placeholder="0 2 * * *" value="${
            editing ? esc(existing.schedule_cron) : ""
          }" /></label>
        <div class="modal-label" style="margin-top:14px"><span>Skills</span>
          <div class="modal-skill-grid" data-skills>${skillOptions}</div></div>
        <div class="modal-actions">
          <button type="button" class="modal-btn ghost" data-act="cancel">Cancel</button>
          <button type="submit" class="modal-btn primary">${editing ? "Save" : "Create"}</button>
        </div>
      </form>
    </div>`;

  document.body.appendChild(overlay);
  requestAnimationFrame(() => overlay.classList.add("open"));

  const close = () => {
    overlay.classList.remove("open");
    setTimeout(() => overlay.remove(), 180);
  };
  overlay.addEventListener("mousedown", (e) => {
    if (e.target === overlay) close();
  });
  overlay.querySelector('[data-act="cancel"]').addEventListener("click", close);
  overlay.querySelector(".modal-body").addEventListener("submit", async (e) => {
    e.preventDefault();
    const skills = [...overlay.querySelectorAll("[data-skills] input:checked")].map(
      (i) => i.value
    );
    if (!skills.length) {
      toast("Pick at least one skill.", "error");
      return;
    }
    const val = (f) => overlay.querySelector(`[data-field="${f}"]`).value.trim();
    const payload = {
      name: val("name") || "New workflow",
      objective: val("objective"),
      module: val("module"),
      environment: val("environment"),
      schedule_cron: val("schedule_cron"),
      skills,
    };
    try {
      if (editing) {
        await api(`/api/workflows/${existing.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        toast("Workflow updated.", "ok");
      } else {
        await api(
          `/api/workflows?project_id=${encodeURIComponent(state.projectId)}`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          }
        );
        toast("Workflow created.", "ok");
      }
      close();
      await Promise.all([loadWorkflows(), loadSummary()]);
    } catch (err) {
      toast(err.message, "error");
    }
  });
}

/* ---------- Wiring ---------- */

function populateModuleFilter() {
  const opts = ['<option value="">All modules</option>'].concat(
    (state.catalog.modules || []).map(
      (m) => `<option value="${esc(m.key)}">${esc(m.label)}</option>`
    )
  );
  els.moduleFilter.innerHTML = opts.join("");
}

async function loadAll() {
  await Promise.all([
    loadSummary(),
    loadFindings(),
    loadApprovals(),
    loadWorkflows(),
    loadRuns(),
  ]);
  markUpdated();
}

els.projectSelect.addEventListener("change", async () => {
  state.projectId = els.projectSelect.value;
  localStorage.setItem("projectId", state.projectId);
  await loadAll();
});

els.refreshBtn.addEventListener("click", loadAll);
els.newWorkflowBtn.addEventListener("click", () => openWorkflowModal(null));

els.filters.addEventListener("click", (e) => {
  const btn = e.target.closest(".chip");
  if (!btn) return;
  state.severity = btn.dataset.sev || "";
  els.filters.querySelectorAll(".chip").forEach((c) => c.classList.remove("active"));
  btn.classList.add("active");
  loadFindings();
});

els.statusFilters.addEventListener("click", (e) => {
  const btn = e.target.closest(".chip");
  if (!btn) return;
  state.status = btn.dataset.status || "";
  els.statusFilters
    .querySelectorAll(".chip")
    .forEach((c) => c.classList.remove("active"));
  btn.classList.add("active");
  loadFindings();
});

els.moduleFilter.addEventListener("change", () => {
  state.module = els.moduleFilter.value;
  loadFindings();
});

els.findings.addEventListener("click", (e) => {
  const t = e.target.closest("button");
  if (!t) return;
  if (t.dataset.explain) explainInChat(t.dataset.explain);
  else if (t.dataset.ack) setFindingStatus(t.dataset.ack, "acknowledged");
  else if (t.dataset.resolve) setFindingStatus(t.dataset.resolve, "resolved");
  else if (t.dataset.reopen) setFindingStatus(t.dataset.reopen, "open");
});

els.approvals.addEventListener("click", (e) => {
  const t = e.target.closest("button");
  if (!t) return;
  if (t.dataset.approve) decideApproval(t.dataset.approve, "approved");
  else if (t.dataset.reject) decideApproval(t.dataset.reject, "rejected");
  else if (t.dataset.approvalExplain) explainApprovalInChat(t.dataset.approvalExplain);
});

els.workflows.addEventListener("click", (e) => {
  const t = e.target.closest("button");
  if (!t) return;
  if (t.dataset.run) runWorkflow(t.dataset.run);
  else if (t.dataset.edit) {
    const w = workflowCache.find((x) => x.id === t.dataset.edit);
    if (w) openWorkflowModal(w);
  } else if (t.dataset.toggle)
    toggleWorkflow(t.dataset.toggle, t.dataset.enabled === "true");
  else if (t.dataset.del) deleteWorkflow(t.dataset.del);
});

els.runs.addEventListener("click", (e) => {
  const item = e.target.closest("[data-run-open]");
  if (item) openRunModal(item.dataset.runOpen);
});

let autoTimer = null;
let labelTimer = null;

async function autoRefresh() {
  // Don't yank content while the user is mid-action.
  if (document.hidden) return;
  if (document.querySelector(".modal-overlay")) return;
  try {
    await Promise.all([
      loadSummary(),
      loadApprovals(),
      loadWorkflows(),
      loadRuns(),
      loadFindings(),
    ]);
    markUpdated();
  } catch (e) {
    /* transient; keep the last good view */
  }
}

function startAutoRefresh() {
  if (autoTimer) clearInterval(autoTimer);
  if (labelTimer) clearInterval(labelTimer);
  autoTimer = setInterval(autoRefresh, 15000);
  labelTimer = setInterval(tickUpdatedLabel, 5000);
}

async function boot() {
  try {
    state.catalog = await api("/api/intelligence/catalog");
  } catch (e) {
    state.catalog = { skills: [], modules: [] };
  }
  populateModuleFilter();
  await loadProjects();
  await loadAll();
  startAutoRefresh();
}

boot();
