import net from "node:net";
import tls from "node:tls";

export const INVITE_MINUTES = 15;

function escapeHtml(value) {
  return String(value || "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

export function inviteEmail({ orgName, inviterName, recipientName, roleName, projectName, acceptUrl }) {
  const who = recipientName ? ` ${recipientName}` : "";
  const where = projectName ? `${orgName} · ${projectName}` : orgName;
  const subject = `Set your Infralens password for ${orgName}`;
  const text = [
    `Hello${who},`,
    "",
    `${inviterName} invited you to ${where} as ${roleName}.`,
    "Infralens does not set a password for you. Open the link below and choose your own.",
    "",
    acceptUrl,
    "",
    `This link expires in ${INVITE_MINUTES} minutes and works once.`,
    "If you were not expecting this, ignore the email.",
  ].join("\n");
  const html = `<!DOCTYPE html>
<html>
  <body style="margin:0;background:#f4f6f8;font-family:Segoe UI,Helvetica,Arial,sans-serif;color:#172033;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f4f6f8;padding:32px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:520px;background:#ffffff;border:1px solid #e6e8ee;border-radius:16px;">
            <tr>
              <td style="padding:28px 28px 8px;">
                <div style="font-size:13px;font-weight:700;letter-spacing:0.08em;color:#1f6feb;">INFRALENS</div>
                <h1 style="margin:12px 0 0;font-size:24px;line-height:1.3;">Set your password</h1>
                <p style="margin:12px 0 0;font-size:15px;line-height:1.5;color:#3d4757;">
                  ${escapeHtml(inviterName)} invited${escapeHtml(who)} to <strong>${escapeHtml(where)}</strong> as <strong>${escapeHtml(roleName)}</strong>.
                </p>
                <p style="margin:12px 0 0;font-size:15px;line-height:1.5;color:#3d4757;">
                  Infralens does not choose a password for you. Use the button to set your own.
                </p>
              </td>
            </tr>
            <tr>
              <td style="padding:20px 28px;">
                <a href="${escapeHtml(acceptUrl)}" style="display:inline-block;background:#1f6feb;color:#ffffff;text-decoration:none;font-weight:700;font-size:15px;padding:12px 18px;border-radius:12px;">Set password</a>
              </td>
            </tr>
            <tr>
              <td style="padding:0 28px 28px;">
                <p style="margin:0;font-size:13px;line-height:1.5;color:#6b7280;">This link expires in ${INVITE_MINUTES} minutes and works once. If you were not expecting it, you can ignore this email.</p>
                <p style="margin:12px 0 0;font-size:12px;line-height:1.5;color:#8b93a1;word-break:break-all;">${escapeHtml(acceptUrl)}</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>`;
  return { subject, text, html };
}

function readReply(socket) {
  return new Promise((resolve, reject) => {
    let buffer = "";
    const onData = (chunk) => {
      buffer += chunk.toString("utf8");
      const lines = buffer.split(/\r?\n/).filter(Boolean);
      const last = lines[lines.length - 1] || "";
      if (!/^\d{3} /.test(last)) return;
      socket.off("data", onData);
      socket.off("error", onError);
      const code = Number(last.slice(0, 3));
      if (code >= 400) reject(new Error(last));
      else resolve(buffer);
    };
    const onError = (err) => {
      socket.off("data", onData);
      reject(err);
    };
    socket.on("data", onData);
    socket.on("error", onError);
  });
}

async function sendLine(socket, line) {
  const pending = readReply(socket);
  socket.write(`${line}\r\n`);
  return pending;
}

export async function sendInviteEmail({ to, orgName, inviterName, recipientName, roleName, projectName, acceptUrl }) {
  const host = String(process.env.SMTP_HOST || "").trim();
  if (!host) return false;
  const port = Number(process.env.SMTP_PORT || 587);
  const user = String(process.env.SMTP_USER || "").trim();
  const password = String(process.env.SMTP_PASS || "");
  const from = String(process.env.SMTP_FROM || user || "noreply@infralens.local").trim();
  const { subject, text, html } = inviteEmail({ orgName, inviterName, recipientName, roleName, projectName, acceptUrl });
  const secure = port === 465;
  const socket = await new Promise((resolve, reject) => {
    const next = secure
      ? tls.connect({ host, port, servername: host }, () => resolve(next))
      : net.connect({ host, port }, () => resolve(next));
    next.once("error", reject);
    setTimeout(() => reject(new Error("SMTP timed out")), Number(process.env.SMTP_TIMEOUT || 8) * 1000);
  });
  try {
    await readReply(socket);
    await sendLine(socket, "EHLO infralens");
    let active = socket;
    if (!secure) {
      await sendLine(socket, "STARTTLS");
      active = await new Promise((resolve, reject) => {
        const upgraded = tls.connect({ socket, servername: host }, () => resolve(upgraded));
        upgraded.once("error", reject);
      });
      await sendLine(active, "EHLO infralens");
    }
    if (user && password) {
      await sendLine(active, "AUTH LOGIN");
      await sendLine(active, Buffer.from(user).toString("base64"));
      await sendLine(active, Buffer.from(password).toString("base64"));
    }
    await sendLine(active, `MAIL FROM:<${from}>`);
    await sendLine(active, `RCPT TO:<${to}>`);
    await sendLine(active, "DATA");
    const boundary = `infralens-${Date.now()}`;
    const body = [
      `From: ${from}`,
      `To: ${to}`,
      `Subject: ${subject}`,
      "MIME-Version: 1.0",
      `Content-Type: multipart/alternative; boundary="${boundary}"`,
      "",
      `--${boundary}`,
      "Content-Type: text/plain; charset=utf-8",
      "",
      text,
      `--${boundary}`,
      "Content-Type: text/html; charset=utf-8",
      "",
      html,
      `--${boundary}--`,
      ".",
    ].join("\r\n");
    await sendLine(active, body);
    await sendLine(active, "QUIT");
    active.end();
    return true;
  } catch {
    socket.destroy();
    return false;
  }
}
