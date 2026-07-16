/* Themed modal system — replaces native prompt()/confirm() with monochrome,
   brutalist-refined dialogs that match the suite. Exposes window.Modal. */
(function () {
  function esc(s) {
    const d = document.createElement("div");
    d.textContent = s == null ? "" : s;
    return d.innerHTML;
  }

  let activeClose = null;

  function teardown(overlay, onKey) {
    document.removeEventListener("keydown", onKey, true);
    overlay.classList.remove("open");
    activeClose = null;
    setTimeout(() => overlay.remove(), 180);
  }

  function base({ eyebrow, title, description, bodyHtml, confirmLabel, cancelLabel, danger }) {
    return new Promise((resolve) => {
      if (activeClose) activeClose();

      const overlay = document.createElement("div");
      overlay.className = "modal-overlay";
      overlay.innerHTML = `
        <div class="modal" role="dialog" aria-modal="true" aria-label="${esc(title)}">
          <div class="modal-accent"></div>
          <div class="modal-head">
            ${eyebrow ? `<span class="modal-eyebrow">${esc(eyebrow)}</span>` : ""}
            <h3 class="modal-title">${esc(title)}</h3>
            ${description ? `<p class="modal-desc">${esc(description)}</p>` : ""}
          </div>
          <form class="modal-body">
            ${bodyHtml || ""}
            <div class="modal-actions">
              <button type="button" class="modal-btn ghost" data-act="cancel">${esc(
                cancelLabel || "Cancel"
              )}</button>
              <button type="submit" class="modal-btn ${danger ? "danger" : "primary"}" data-act="ok">${esc(
        confirmLabel || "Confirm"
      )}</button>
            </div>
          </form>
        </div>`;

      document.body.appendChild(overlay);
      requestAnimationFrame(() => overlay.classList.add("open"));

      const form = overlay.querySelector(".modal-body");
      const firstInput = overlay.querySelector("input, textarea");
      if (firstInput) setTimeout(() => firstInput.focus(), 60);
      else setTimeout(() => overlay.querySelector('[data-act="ok"]').focus(), 60);

      const close = (value) => {
        teardown(overlay, onKey);
        resolve(value);
      };
      activeClose = () => close(null);

      const onKey = (e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          close(null);
        }
      };
      document.addEventListener("keydown", onKey, true);

      overlay.addEventListener("mousedown", (e) => {
        if (e.target === overlay) close(null);
      });
      overlay.querySelector('[data-act="cancel"]').addEventListener("click", () => close(null));
      form.addEventListener("submit", (e) => {
        e.preventDefault();
        const inputs = {};
        overlay.querySelectorAll("[data-field]").forEach((el) => {
          inputs[el.dataset.field] = el.value.trim();
        });
        close(Object.keys(inputs).length ? inputs : true);
      });
    });
  }

  async function prompt({ eyebrow, title, description, label, placeholder, value, confirmLabel }) {
    const bodyHtml = `
      <label class="modal-label">
        ${label ? `<span>${esc(label)}</span>` : ""}
        <input data-field="value" type="text" value="${esc(value || "")}" placeholder="${esc(
      placeholder || ""
    )}" />
      </label>`;
    const result = await base({
      eyebrow,
      title,
      description,
      bodyHtml,
      confirmLabel: confirmLabel || "Save",
    });
    if (!result || !result.value) return null;
    return result.value;
  }

  function confirm({ eyebrow, title, description, message, confirmLabel, danger }) {
    return base({
      eyebrow,
      title,
      description: description || message,
      confirmLabel: confirmLabel || "Confirm",
      danger,
    }).then((r) => r === true || (r && typeof r === "object"));
  }

  window.Modal = { prompt, confirm };
})();
