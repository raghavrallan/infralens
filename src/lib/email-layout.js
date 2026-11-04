const FONT = '"DM Sans", "Segoe UI", Helvetica, Arial, sans-serif';

export function escapeHtml(value) {
  return String(value || "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

export function codeDigits(code) {
  const cells = String(code || "")
    .replace(/\D/g, "")
    .slice(0, 6)
    .split("")
    .map((digit, index) => `
      <td style="padding:${index === 0 ? "0" : "0 0 0 8px"};">
        <table role="presentation" cellspacing="0" cellpadding="0">
          <tr>
            <td align="center" width="48" height="58" style="width:48px;height:58px;background:#fff6f1;border:1px solid #f3d4c3;border-radius:14px;font-family:${FONT};font-size:26px;line-height:58px;font-weight:700;color:#c45e28;">${escapeHtml(digit)}</td>
          </tr>
        </table>
      </td>`)
    .join("");
  return `<table role="presentation" cellspacing="0" cellpadding="0" style="margin:22px 0 8px;"><tr>${cells}</tr></table>`;
}

export function detailTable(rows) {
  const body = rows
    .filter((row) => row.value)
    .map((row, index, list) => `
      <tr>
        <td style="padding:13px 16px;border-bottom:${index === list.length - 1 ? "0" : "1px solid #e7e5e4"};font-family:${FONT};font-size:12px;line-height:1.4;color:#717171;width:132px;">${escapeHtml(row.label)}</td>
        <td style="padding:13px 16px;border-bottom:${index === list.length - 1 ? "0" : "1px solid #e7e5e4"};font-family:${FONT};font-size:14px;line-height:1.4;font-weight:700;color:#232323;">${escapeHtml(row.value)}</td>
      </tr>`)
    .join("");
  return `<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:22px 0 8px;background:#f6f6f6;border-radius:16px;">${body}</table>`;
}

export function emailButton(href, label) {
  return `<table role="presentation" cellspacing="0" cellpadding="0" style="margin:22px 0 8px;">
    <tr>
      <td bgcolor="#e2773c" style="border-radius:16px;background:#e2773c;">
        <a href="${escapeHtml(href)}" style="display:inline-block;padding:14px 22px;font-family:${FONT};font-size:14px;line-height:1;font-weight:700;color:#ffffff !important;text-decoration:none;">${escapeHtml(label)}</a>
      </td>
    </tr>
  </table>`;
}

export function emailDocument({ preheader, eyebrow, title, intro, content, note }) {
  return `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>${escapeHtml(title)}</title>
  </head>
  <body style="margin:0;padding:0;background:#f7f6f4;">
    <div style="display:none;max-height:0;overflow:hidden;opacity:0;color:#f7f6f4;">${escapeHtml(preheader)}</div>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f7f6f4;">
      <tr>
        <td align="center" style="padding:40px 16px;">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;">
            <tr>
              <td style="height:4px;background:#e2773c;border-radius:4px 4px 0 0;font-size:0;line-height:0;">&nbsp;</td>
            </tr>
            <tr>
              <td style="background:#ffffff;border:1px solid #e7e5e4;border-top:0;border-radius:0 0 24px 24px;padding:32px 32px 28px;">
                <div style="font-family:${FONT};font-size:14px;line-height:1;font-weight:700;color:#e2773c;">Infralens</div>
                <div style="margin-top:22px;font-family:${FONT};font-size:12px;line-height:1.4;font-weight:700;letter-spacing:0.06em;text-transform:uppercase;color:#717171;">${escapeHtml(eyebrow)}</div>
                <h1 style="margin:8px 0 0;font-family:${FONT};font-size:28px;line-height:1.25;font-weight:700;color:#232323;">${escapeHtml(title)}</h1>
                <p style="margin:12px 0 0;font-family:${FONT};font-size:15px;line-height:1.6;color:#717171;">${intro}</p>
                ${content}
                <p style="margin:18px 0 0;font-family:${FONT};font-size:13px;line-height:1.6;color:#717171;">${note}</p>
              </td>
            </tr>
            <tr>
              <td style="padding:18px 8px 0;text-align:center;font-family:${FONT};font-size:12px;line-height:1.6;color:#717171;">
                Infralens · No Reply<br>This mailbox is not monitored.
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>`;
}
