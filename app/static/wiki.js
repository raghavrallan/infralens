let skills = [];

function prettyName(name) {
  return name
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

function renderMarkdown(text) {
  const lines = (text || "").split("\n");
  let html = "";
  let inList = false;
  let inCode = false;

  const closeList = () => {
    if (inList) {
      html += "</ul>";
      inList = false;
    }
  };

  for (const raw of lines) {
    const line = raw;
    if (line.trim().startsWith("```")) {
      if (inCode) {
        html += "</code></pre>";
        inCode = false;
      } else {
        closeList();
        html += "<pre><code>";
        inCode = true;
      }
      continue;
    }
    if (inCode) {
      html += escapeHtml(line) + "\n";
      continue;
    }

    let processed = escapeHtml(line);
    processed = processed.replace(/`([^`]+)`/g, "<code>$1</code>");
    processed = processed.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    processed = processed.replace(/\*([^*]+)\*/g, "<em>$1</em>");

    if (/^##\s+/.test(line)) {
      closeList();
      html += `<h2>${processed.replace(/^##\s+/, "")}</h2>`;
    } else if (/^###\s+/.test(line)) {
      closeList();
      html += `<h3>${processed.replace(/^###\s+/, "")}</h3>`;
    } else if (/^\s*-\s+/.test(line)) {
      if (!inList) {
        html += "<ul>";
        inList = true;
      }
      html += `<li>${processed.replace(/^\s*-\s+/, "")}</li>`;
    } else if (line.trim() === "") {
      closeList();
    } else {
      closeList();
      html += `<p>${processed}</p>`;
    }
  }
  closeList();
  if (inCode) html += "</code></pre>";
  return html;
}

function renderIndex(activeName) {
  const index = document.getElementById("wiki-index");
  index.innerHTML = "<h3>Skills</h3>";
  skills.forEach((s) => {
    const link = document.createElement("a");
    link.href = `/wiki?skill=${encodeURIComponent(s.name)}`;
    link.className = "wiki-index-item" + (s.name === activeName ? " active" : "");
    link.innerHTML = `<span>${escapeHtml(prettyName(s.name))}</span><small>${escapeHtml(s.category)}</small>`;
    link.addEventListener("click", (e) => {
      e.preventDefault();
      history.pushState({}, "", link.href);
      showSkill(s.name);
    });
    index.appendChild(link);
  });
}

async function showSkill(name) {
  const article = document.getElementById("wiki-article");
  renderIndex(name);
  try {
    const res = await fetch(`/api/skills/${encodeURIComponent(name)}`);
    if (!res.ok) {
      article.innerHTML = `<p class="muted">Skill not found.</p>`;
      return;
    }
    const skill = await res.json();
    const triggers = (skill.triggers || [])
      .map((t) => `<li><code>${escapeHtml(t)}</code></li>`)
      .join("");
    article.innerHTML = `
      <div class="wiki-head">
        <span class="wiki-cat">${escapeHtml(skill.category)}</span>
        <a class="wiki-try" href="/">Try in chat →</a>
      </div>
      ${renderMarkdown(skill.wiki || "## " + prettyName(skill.name) + "\n\n" + skill.description)}
      <h3>Example prompts</h3>
      <ul>${triggers}</ul>
    `;
    window.scrollTo(0, 0);
  } catch (e) {
    article.innerHTML = `<p class="muted">Failed to load skill.</p>`;
  }
}

function renderOverview() {
  const article = document.getElementById("wiki-article");
  renderIndex(null);
  const cards = skills
    .map(
      (s) => `
      <a class="wiki-card" href="/wiki?skill=${encodeURIComponent(s.name)}">
        <div class="wiki-card-name">${escapeHtml(prettyName(s.name))}</div>
        <div class="wiki-card-cat">${escapeHtml(s.category)}</div>
        <div class="wiki-card-desc">${escapeHtml(s.description)}</div>
      </a>`
    )
    .join("");
  article.innerHTML = `
    <h2>Skill wiki</h2>
    <p class="muted">
      Reference documentation for every skill in the suite — what each one does,
      when to use it, what to feed it and what you get back.
    </p>
    <div class="wiki-grid">${cards}</div>
  `;
  document.querySelectorAll(".wiki-card").forEach((card) => {
    card.addEventListener("click", (e) => {
      e.preventDefault();
      const name = new URL(card.href).searchParams.get("skill");
      history.pushState({}, "", card.href);
      showSkill(name);
    });
  });
}

function route() {
  const name = new URLSearchParams(location.search).get("skill");
  if (name) {
    showSkill(name);
  } else {
    renderOverview();
  }
}

window.addEventListener("popstate", route);

async function init() {
  const res = await fetch("/api/skills");
  skills = await res.json();
  route();
}

init();
