const state = {
  chatId: null,
  chats: [],
  projects: [],
  projectId: localStorage.getItem("projectId") || "default",
  sending: false,
  mode: "agent",
  skill: "",
  actionScope: "read_only",
  accessLevel: "ask_approval",
  skills: [],
  slashOpen: false,
  slashIndex: 0,
  suggestion: null,
};

const els = {
  messages: document.getElementById("messages"),
  emptyState: document.getElementById("empty-state"),
  suggestions: document.getElementById("suggestions"),
  form: document.getElementById("composer"),
  input: document.getElementById("input"),
  sendBtn: document.getElementById("send-btn"),
  newChatBtn: document.getElementById("new-chat"),
  chatList: document.getElementById("chat-list"),
  projectSelect: document.getElementById("project-select"),
  newProjectBtn: document.getElementById("new-project"),
  statusDot: document.getElementById("status-dot"),
  statusText: document.getElementById("status-text"),
  modeToggle: document.getElementById("mode-toggle"),
  activeSkill: document.getElementById("active-skill"),
  slashMenu: document.getElementById("slash-menu"),
  hint: document.getElementById("composer-hint"),
  actionScope: document.getElementById("action-scope"),
  accessLevel: document.getElementById("access-level"),
  suggestBar: document.getElementById("suggest-bar"),
  suggestPill: document.getElementById("suggest-pill"),
};

const AUTO_OPTION = {
  name: "auto",
  auto: true,
  description: "Let the agent auto-detect and orchestrate the right skills.",
};

function prettyName(name) {
  return name
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function capitalize(s) {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

function renderInline(escaped) {
  let h = escaped;
  h = h.replace(/`([^`]+)`/g, "<code>$1</code>");
  h = h.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  h = h.replace(/\*([^*\n]+)\*/g, "<em>$1</em>");
  h = h.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  return h;
}

function severityClass(text) {
  const t = text.toLowerCase();
  if (t.includes("critical")) return "sev sev-critical";
  if (t.includes("high")) return "sev sev-high";
  if (t.includes("medium")) return "sev sev-medium";
  if (t.includes("low")) return "sev sev-low";
  return "";
}

function splitRow(line) {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|")) s = s.slice(0, -1);
  return s.split("|").map((c) => c.trim());
}

function renderTable(lines, start) {
  const header = splitRow(lines[start]);
  const sevIdx = header.findIndex((h) => /sever/i.test(h));
  let i = start + 2;
  const rows = [];
  while (i < lines.length && lines[i].includes("|") && lines[i].trim() !== "") {
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(lines[i])) break;
    rows.push(splitRow(lines[i]));
    i++;
  }
  const thead =
    "<tr>" + header.map((h) => `<th>${renderInline(escapeHtml(h))}</th>`).join("") + "</tr>";
  const tbody = rows
    .map((cells) => {
      const tds = cells
        .map((c, idx) => {
          const inner = renderInline(escapeHtml(c));
          if (idx === sevIdx) {
            const cls = severityClass(c);
            return cls ? `<td><span class="${cls}">${inner}</span></td>` : `<td>${inner}</td>`;
          }
          return `<td>${inner}</td>`;
        })
        .join("");
      return `<tr>${tds}</tr>`;
    })
    .join("");
  return {
    html: `<div class="table-wrap"><table><thead>${thead}</thead><tbody>${tbody}</tbody></table></div>`,
    consumed: i - start,
  };
}

function renderBlocks(text) {
  const lines = text.split("\n");
  let html = "";
  let i = 0;
  let listBuffer = [];
  let listType = null;

  const flushList = () => {
    if (listBuffer.length) {
      const items = listBuffer
        .map((li) => (li.num ? `<li value="${li.num}">${li.html}</li>` : `<li>${li.html}</li>`))
        .join("");
      html += `<${listType}>${items}</${listType}>`;
      listBuffer = [];
      listType = null;
    }
  };

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    const isTableSep =
      i + 1 < lines.length &&
      lines[i + 1].includes("-") &&
      /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i + 1]);
    if (trimmed.includes("|") && isTableSep) {
      flushList();
      const { html: tableHtml, consumed } = renderTable(lines, i);
      html += tableHtml;
      i += consumed;
      continue;
    }

    if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      flushList();
      html += "<hr>";
      i++;
      continue;
    }

    let m;
    if ((m = trimmed.match(/^(#{1,6})\s+(.*)$/))) {
      flushList();
      const level = m[1].length;
      const tag = level <= 2 ? "h3" : level === 3 ? "h4" : "h5";
      html += `<${tag}>${renderInline(escapeHtml(m[2]))}</${tag}>`;
      i++;
      continue;
    }

    if ((m = trimmed.match(/^[-*]\s+(.*)$/))) {
      if (listType !== "ul") {
        flushList();
        listType = "ul";
      }
      listBuffer.push({ html: renderInline(escapeHtml(m[1])) });
      i++;
      continue;
    }
    if ((m = trimmed.match(/^(\d+)\.\s+(.*)$/))) {
      if (listType !== "ol") {
        flushList();
        listType = "ol";
      }
      listBuffer.push({ html: renderInline(escapeHtml(m[2])), num: m[1] });
      i++;
      continue;
    }

    if (trimmed === "") {
      flushList();
      i++;
      continue;
    }

    flushList();
    html += `<p>${renderInline(escapeHtml(trimmed))}</p>`;
    i++;
  }
  flushList();
  return html;
}

function renderMarkdownish(text) {
  const parts = text.split(/```/);
  let html = "";
  parts.forEach((part, idx) => {
    if (idx % 2 === 1) {
      const code = part.replace(/^[a-zA-Z0-9]*\n/, "").replace(/\n$/, "");
      html += `<pre><code>${escapeHtml(code)}</code></pre>`;
    } else {
      html += renderBlocks(part);
    }
  });
  return html;
}

async function loadHealth() {
  try {
    const res = await fetch("/api/health");
    const data = await res.json();
    if (data.azure_configured) {
      els.statusDot.classList.add("ok");
      els.statusText.textContent = `${data.deployment} · ${data.skill_count} skills`;
    } else {
      els.statusDot.classList.add("off");
      els.statusText.innerHTML = `Not configured · <a href="/settings">connect</a>`;
    }
  } catch (e) {
    els.statusDot.classList.add("off");
    els.statusText.textContent = "Server unreachable";
  }
}

async function loadSkills() {
  const res = await fetch("/api/skills");
  state.skills = await res.json();

  const seeds = [];
  state.skills.forEach((skill) => {
    const seed = skill.triggers && skill.triggers.length ? skill.triggers[0] : skill.description;
    if (seed) seeds.push(capitalize(seed));
  });

  renderSuggestions(seeds.slice(0, 4));
}

function renderSuggestions(seeds) {
  els.suggestions.innerHTML = "";
  seeds.forEach((seed) => {
    const chip = document.createElement("button");
    chip.className = "suggestion";
    chip.textContent = seed;
    chip.addEventListener("click", () => {
      els.input.value = seed;
      autogrow();
      sendMessage();
    });
    els.suggestions.appendChild(chip);
  });
}

/* ---------- Projects ---------- */

async function loadProjects() {
  try {
    const res = await fetch("/api/projects");
    state.projects = await res.json();
  } catch (e) {
    state.projects = [{ id: "default", name: "Default project" }];
  }
  if (!state.projects.some((p) => p.id === state.projectId)) {
    state.projectId = state.projects.length ? state.projects[0].id : "default";
  }
  localStorage.setItem("projectId", state.projectId);
  renderProjectSelect();
}

function renderProjectSelect() {
  els.projectSelect.innerHTML = state.projects
    .map(
      (p) =>
        `<option value="${p.id}" ${p.id === state.projectId ? "selected" : ""}>${escapeHtml(
          p.name
        )}</option>`
    )
    .join("");
}

async function setProject(id) {
  if (id === state.projectId) return;
  state.projectId = id;
  localStorage.setItem("projectId", id);
  newChat();
  await loadChats();
}

async function createProject() {
  const name = await Modal.prompt({
    eyebrow: "Workspace",
    title: "New project",
    description: "Isolate a client or product with its own credentials, repos and chats.",
    label: "Project name",
    placeholder: "e.g. Seye, TG…",
    confirmLabel: "Create project",
  });
  if (!name) return;
  try {
    const res = await fetch("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name.trim() }),
    });
    const project = await res.json();
    await loadProjects();
    await setProject(project.id);
  } catch (e) {
    /* ignore */
  }
}

/* ---------- Chat history sidebar ---------- */

async function loadChats() {
  try {
    const res = await fetch(`/api/chats?project_id=${encodeURIComponent(state.projectId)}`);
    state.chats = await res.json();
    renderChatList();
  } catch (e) {
    /* offline: leave empty */
  }
}

function renderChatList() {
  els.chatList.innerHTML = "";
  if (!state.chats.length) {
    const empty = document.createElement("div");
    empty.className = "chat-list-empty";
    empty.textContent = "No chats yet";
    els.chatList.appendChild(empty);
    return;
  }
  state.chats.forEach((chat) => {
    const item = document.createElement("div");
    item.className = "chat-item" + (chat.id === state.chatId ? " active" : "");
    item.dataset.id = chat.id;
    item.innerHTML = `
      <button class="chat-item-title" title="${escapeHtml(chat.title)}">${escapeHtml(chat.title)}</button>
      <button class="chat-item-del" title="Delete chat">✕</button>`;
    item.querySelector(".chat-item-title").addEventListener("click", () => selectChat(chat.id));
    item.querySelector(".chat-item-del").addEventListener("click", (e) => {
      e.stopPropagation();
      deleteChat(chat.id);
    });
    els.chatList.appendChild(item);
  });
}

async function selectChat(id) {
  if (state.sending) return;
  try {
    const res = await fetch(`/api/chats/${id}`);
    if (!res.ok) return;
    const chat = await res.json();
    state.chatId = chat.id;
    clearMessages();
    chat.messages.forEach((m) => {
      addMessage(m.role === "user" ? "user" : "bot", m.content, m.meta);
    });
    if (!chat.messages.length) els.emptyState.style.display = "";
    renderChatList();
  } catch (e) {
    /* ignore */
  }
}

function newChat() {
  state.chatId = null;
  clearMessages();
  els.emptyState.style.display = "";
  renderChatList();
  els.input.focus();
}

async function deleteChat(id) {
  const chat = state.chats.find((c) => c.id === id);
  const ok = await Modal.confirm({
    eyebrow: "Delete chat",
    title: "Delete this chat?",
    message: `“${chat ? chat.title : "This conversation"}” and its messages will be permanently removed.`,
    confirmLabel: "Delete",
    danger: true,
  });
  if (!ok) return;
  try {
    await fetch(`/api/chats/${id}`, { method: "DELETE" });
  } catch (e) {
    /* ignore */
  }
  if (id === state.chatId) newChat();
  await loadChats();
}

function clearMessages() {
  document.querySelectorAll(".msg").forEach((m) => m.remove());
  els.emptyState.style.display = "none";
}

/* ---------- Slash command menu ---------- */

function slashOptions() {
  return [AUTO_OPTION, ...state.skills];
}

function slashMatches() {
  const value = els.input.value;
  if (!value.startsWith("/")) return null;
  if (value.includes(" ")) return null;
  const query = value.slice(1).toLowerCase();
  return slashOptions().filter(
    (s) => s.name.includes(query) || prettyName(s.name).toLowerCase().includes(query)
  );
}

function updateSlashMenu() {
  const matches = slashMatches();
  if (!matches || matches.length === 0) {
    closeSlashMenu();
    return;
  }
  state.slashOpen = true;
  state.slashIndex = Math.min(state.slashIndex, matches.length - 1);
  els.slashMenu.hidden = false;
  els.slashMenu.innerHTML = matches
    .map((s, i) => {
      const label = s.auto ? "/auto · multi-agent" : `/${s.name}`;
      return `
      <div class="slash-item ${s.auto ? "auto-item" : ""} ${i === state.slashIndex ? "active" : ""}" data-skill="${s.name}">
        <span class="slash-name ${s.auto ? "auto" : ""}">${label}</span>
        <span class="slash-desc">${escapeHtml(s.description)}</span>
      </div>`;
    })
    .join("");
  els.slashMenu.querySelectorAll(".slash-item").forEach((item) => {
    item.addEventListener("click", () => chooseSlash(item.dataset.skill));
  });
}

function closeSlashMenu() {
  state.slashOpen = false;
  state.slashIndex = 0;
  els.slashMenu.hidden = true;
  els.slashMenu.innerHTML = "";
}

function chooseSlash(name) {
  state.skill = name === "auto" ? "" : name;
  els.input.value = "";
  closeSlashMenu();
  updateActiveSkill();
  updateHint();
  updateSuggestion();
  els.input.focus();
}

/* ---------- Auto skill suggestion while typing ---------- */

function scoreSkill(skill, text) {
  let score = 0;
  const haystack = text.toLowerCase();
  const terms = [
    skill.name.replace(/_/g, " "),
    ...(skill.triggers || []),
    skill.category || "",
  ];
  terms.forEach((term) => {
    term
      .toLowerCase()
      .split(/[\s,]+/)
      .filter((w) => w.length > 3)
      .forEach((word) => {
        if (haystack.includes(word)) score += 1;
      });
  });
  return score;
}

function updateSuggestion() {
  const text = els.input.value.trim();
  if (state.skill || state.slashOpen || text.startsWith("/") || text.length < 8) {
    hideSuggestion();
    return;
  }
  let best = null;
  let bestScore = 0;
  state.skills.forEach((skill) => {
    const s = scoreSkill(skill, text);
    if (s > bestScore) {
      bestScore = s;
      best = skill;
    }
  });
  if (!best || bestScore < 1) {
    hideSuggestion();
    return;
  }
  state.suggestion = best;
  els.suggestBar.hidden = false;
  els.suggestPill.textContent = prettyName(best.name);
}

function hideSuggestion() {
  state.suggestion = null;
  els.suggestBar.hidden = true;
}

function acceptSuggestion() {
  if (!state.suggestion) return;
  state.skill = state.suggestion.name;
  hideSuggestion();
  updateActiveSkill();
  updateHint();
  els.input.focus();
}

/* ---------- Mode + skill + controls state ---------- */

function updateActiveSkill() {
  if (state.skill) {
    els.activeSkill.classList.add("forced");
    els.activeSkill.innerHTML = `
      <span class="active-skill-label">${escapeHtml(prettyName(state.skill))}</span>
      <button class="clear-skill" title="Back to Auto (or type /auto)">✕</button>`;
    els.activeSkill
      .querySelector(".clear-skill")
      .addEventListener("click", () => chooseSlash("auto"));
  } else {
    els.activeSkill.classList.remove("forced");
    els.activeSkill.innerHTML = `<span class="active-skill-label">Auto · multi-agent</span>`;
  }
}

function updateHint() {
  const modeText = state.mode === "plan" ? "Plan mode (read-only)" : "Agent mode";
  const scopeText = state.actionScope === "write" ? "write" : "read-only";
  const skillText = state.skill
    ? `forced: ${prettyName(state.skill)} · /auto to switch back`
    : "auto multi-agent · type / to pick a skill";
  els.hint.textContent = `${modeText} · ${scopeText} · ${skillText}`;
}

els.modeToggle.querySelectorAll(".mode-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    state.mode = btn.dataset.mode;
    els.modeToggle.querySelectorAll(".mode-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    updateHint();
  });
});

els.actionScope.addEventListener("change", () => {
  state.actionScope = els.actionScope.value;
  updateHint();
});
els.accessLevel.addEventListener("change", () => {
  state.accessLevel = els.accessLevel.value;
});

/* ---------- Rendering messages ---------- */

function metaHtml(meta) {
  if (!meta) return "";
  if (meta.mode === "plan") {
    return `<div class="turn-badge plan">Plan</div>`;
  }
  if (meta.skills_used && meta.skills_used.length) {
    const chips = meta.skills_used
      .map((s) => `<span class="agent-chip">${escapeHtml(prettyName(s))}</span>`)
      .join("");
    const label = `${meta.skills_used.length} agent${meta.skills_used.length > 1 ? "s" : ""}`;
    return `<div class="turn-badge">${label}</div><div class="agent-chips">${chips}</div>`;
  }
  return "";
}

function buildActions(role, getContent) {
  const actions = document.createElement("div");
  actions.className = "msg-actions";
  const copyBtn = document.createElement("button");
  copyBtn.className = "msg-action";
  copyBtn.textContent = "Copy";
  copyBtn.addEventListener("click", () => copyText(copyBtn, getContent()));
  actions.appendChild(copyBtn);
  if (role === "user") {
    const editBtn = document.createElement("button");
    editBtn.className = "msg-action";
    editBtn.textContent = "Edit";
    editBtn.addEventListener("click", () => {
      els.input.value = getContent();
      autogrow();
      updateSuggestion();
      els.input.focus();
    });
    actions.appendChild(editBtn);
  }
  return actions;
}

function isNearBottom() {
  const el = els.messages;
  return el.scrollHeight - el.scrollTop - el.clientHeight < 120;
}

function scrollToBottom() {
  els.messages.scrollTop = els.messages.scrollHeight;
}

function addMessage(role, content, meta) {
  els.emptyState.style.display = "none";
  const msg = document.createElement("div");
  msg.className = `msg ${role === "user" ? "user" : "bot"}`;

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = role === "user" ? "You" : "DS";

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.innerHTML =
    metaHtml(meta) +
    `<div class="bubble-content">${
      role === "user" ? escapeHtml(content) : renderMarkdownish(content)
    }</div>`;
  bubble.appendChild(buildActions(role, () => content));
  if (role !== "user") enhanceBlocks(bubble.querySelector(".bubble-content"));

  msg.appendChild(avatar);
  msg.appendChild(bubble);
  els.messages.appendChild(msg);
  scrollToBottom();
  return msg;
}

async function copyText(btn, text) {
  try {
    await navigator.clipboard.writeText(text);
    const original = btn.textContent;
    btn.textContent = "Copied";
    setTimeout(() => (btn.textContent = original), 1200);
  } catch (e) {
    /* clipboard unavailable */
  }
}

const COPY_ICON =
  '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>';
const CHECK_ICON =
  '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>';

function enhanceBlocks(container) {
  if (!container) return;
  container.querySelectorAll(".table-wrap, pre").forEach((block) => {
    if (block.querySelector(":scope > .block-copy")) return;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "block-copy";
    btn.title = "Copy";
    btn.innerHTML = COPY_ICON;
    btn.addEventListener("click", async () => {
      const target = block.matches("pre")
        ? block.querySelector("code") || block
        : block.querySelector("table") || block;
      try {
        await navigator.clipboard.writeText((target.innerText || "").trim());
        btn.innerHTML = CHECK_ICON;
        btn.classList.add("copied");
        setTimeout(() => {
          btn.innerHTML = COPY_ICON;
          btn.classList.remove("copied");
        }, 1200);
      } catch (e) {
        /* clipboard unavailable */
      }
    });
    block.appendChild(btn);
  });
}

function createStreamingMessage() {
  els.emptyState.style.display = "none";
  const msg = document.createElement("div");
  msg.className = "msg bot";

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = "DS";

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  const meta = document.createElement("div");
  meta.className = "bubble-meta";
  const status = document.createElement("div");
  status.className = "stream-status";
  status.innerHTML =
    '<span class="stream-dots"><i></i><i></i><i></i></span><span class="stream-label">Working…</span>';
  const content = document.createElement("div");
  content.className = "bubble-content streaming";
  bubble.appendChild(meta);
  bubble.appendChild(status);
  bubble.appendChild(content);

  msg.appendChild(avatar);
  msg.appendChild(bubble);
  els.messages.appendChild(msg);
  scrollToBottom();

  return {
    setStatus(text) {
      status.style.display = "flex";
      status.querySelector(".stream-label").textContent = text;
    },
    setContent(text) {
      const near = isNearBottom();
      content.innerHTML = renderMarkdownish(text);
      if (near) scrollToBottom();
    },
    finalize(text, evt) {
      status.remove();
      content.classList.remove("streaming");
      content.innerHTML = renderMarkdownish(text);
      enhanceBlocks(content);
      meta.innerHTML = metaHtml(evt);
      bubble.appendChild(buildActions("bot", () => text));
      if (isNearBottom()) scrollToBottom();
    },
    error(text) {
      status.remove();
      content.classList.remove("streaming");
      content.innerHTML = renderMarkdownish(text);
    },
  };
}

async function sendMessage() {
  const text = els.input.value.trim();
  if (!text || state.sending) return;

  state.sending = true;
  els.sendBtn.disabled = true;
  closeSlashMenu();
  hideSuggestion();

  addMessage("user", text);
  els.input.value = "";
  autogrow();

  const bot = createStreamingMessage();
  bot.setStatus(state.mode === "plan" ? "Planning…" : "Working…");
  let acc = "";

  const handle = (evt) => {
    if (evt.type === "chat") {
      if (evt.chat_id) state.chatId = evt.chat_id;
    } else if (evt.type === "status") {
      bot.setStatus(evt.text + "…");
    } else if (evt.type === "delta") {
      acc += evt.text;
      bot.setContent(acc);
    } else if (evt.type === "final") {
      if (evt.chat_id) state.chatId = evt.chat_id;
      acc = evt.reply || acc;
      bot.finalize(acc, evt);
      loadChats();
    }
  };

  try {
    const res = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: state.chatId,
        project_id: state.projectId,
        message: text,
        mode: state.mode,
        skill: state.skill || null,
        action_scope: state.actionScope,
        access_level: state.accessLevel,
      }),
    });
    if (!res.ok || !res.body) throw new Error("stream failed");

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split("\n\n");
      buffer = chunks.pop();
      for (const chunk of chunks) {
        const line = chunk.trim();
        if (!line.startsWith("data:")) continue;
        try {
          handle(JSON.parse(line.slice(5).trim()));
        } catch (e) {
          /* ignore malformed frame */
        }
      }
    }
  } catch (e) {
    bot.error(acc || "Something went wrong reaching the server.");
  } finally {
    state.sending = false;
    els.sendBtn.disabled = false;
    els.input.focus();
  }
}

function autogrow() {
  els.input.style.height = "auto";
  els.input.style.height = Math.min(els.input.scrollHeight, 200) + "px";
}

/* ---------- Events ---------- */

els.form.addEventListener("submit", (e) => {
  e.preventDefault();
  sendMessage();
});

els.input.addEventListener("input", () => {
  autogrow();
  updateSlashMenu();
  updateSuggestion();
});

els.input.addEventListener("keydown", (e) => {
  if (state.slashOpen) {
    const matches = slashMatches() || [];
    if (e.key === "ArrowDown") {
      e.preventDefault();
      state.slashIndex = (state.slashIndex + 1) % matches.length;
      updateSlashMenu();
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      state.slashIndex = (state.slashIndex - 1 + matches.length) % matches.length;
      updateSlashMenu();
      return;
    }
    if (e.key === "Enter" || e.key === "Tab") {
      e.preventDefault();
      if (matches[state.slashIndex]) chooseSlash(matches[state.slashIndex].name);
      return;
    }
    if (e.key === "Escape") {
      closeSlashMenu();
      return;
    }
  }
  if (e.key === "Tab" && state.suggestion && !state.slashOpen) {
    e.preventDefault();
    acceptSuggestion();
    return;
  }
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

els.newChatBtn.addEventListener("click", newChat);
els.suggestPill.addEventListener("click", acceptSuggestion);
els.projectSelect.addEventListener("change", () => setProject(els.projectSelect.value));
els.newProjectBtn.addEventListener("click", createProject);

async function boot() {
  await loadProjects();
  await loadChats();
}

loadHealth();
loadSkills();
boot();
updateActiveSkill();
updateHint();
