import net from "node:net";
import tls from "node:tls";

const OFFICE_CLIENT_ID = "d3590ed6-52b3-4102-aeff-aad2292ab01c";

export function mailSettings() {
  const user = String(process.env.SMTP_USER || "").trim();
  const fromAddress = String(process.env.SMTP_FROM || user).trim();
  return {
    host: String(process.env.SMTP_HOST || "").trim(),
    port: Number(process.env.SMTP_PORT || 587),
    user,
    password: String(process.env.SMTP_PASS || ""),
    fromAddress,
    fromName: String(process.env.SMTP_FROM_NAME || "No Reply").trim() || "No Reply",
    timeoutMs: Number(process.env.SMTP_TIMEOUT || 20) * 1000,
  };
}

export function mailConfigured() {
  const settings = mailSettings();
  return Boolean(settings.host && settings.user && settings.password && settings.fromAddress);
}

function fromHeader(settings) {
  const name = settings.fromName.replace(/"/g, "");
  return `"${name}" <${settings.fromAddress}>`;
}

function readReply(socket) {
  return new Promise((resolve, reject) => {
    let buffer = "";
    const onData = (chunk) => {
      buffer += chunk.toString("utf8");
      const lines = buffer.split(/\r?\n/).filter(Boolean);
      const last = lines[lines.length - 1] || "";
      if (!/^\d{3} /.test(last)) return;
      cleanup();
      const code = Number(last.slice(0, 3));
      if (code >= 400) reject(new Error(last));
      else resolve(buffer);
    };
    const onError = (err) => {
      cleanup();
      reject(err);
    };
    const cleanup = () => {
      socket.off("data", onData);
      socket.off("error", onError);
    };
    socket.on("data", onData);
    socket.on("error", onError);
  });
}

function sendCommand(socket, line) {
  const pending = readReply(socket);
  socket.write(`${line}\r\n`);
  return pending;
}

function connectSocket({ host, port, secure, timeoutMs }) {
  return new Promise((resolve, reject) => {
    const socket = secure
      ? tls.connect({ host, port, servername: host, family: 4, autoSelectFamily: false })
      : net.connect({ host, port, family: 4, autoSelectFamily: false });
    const timer = setTimeout(() => {
      socket.destroy();
      reject(new Error("SMTP timed out"));
    }, timeoutMs);
    const fail = (err) => {
      clearTimeout(timer);
      reject(err);
    };
    socket.once("error", fail);
    socket.once(secure ? "secureConnect" : "connect", () => {
      clearTimeout(timer);
      socket.off("error", fail);
      socket.setTimeout(timeoutMs);
      resolve(socket);
    });
  });
}

function upgradeTls(socket, host, timeoutMs) {
  return new Promise((resolve, reject) => {
    socket.removeAllListeners("data");
    socket.removeAllListeners("error");
    const secure = tls.connect({ socket, servername: host });
    const timer = setTimeout(() => {
      secure.destroy();
      reject(new Error("SMTP timed out"));
    }, timeoutMs);
    secure.once("error", (err) => {
      clearTimeout(timer);
      reject(err);
    });
    secure.once("secureConnect", () => {
      clearTimeout(timer);
      secure.setTimeout(timeoutMs);
      resolve(secure);
    });
  });
}

function messageBody({ from, to, subject, text, html }) {
  const boundary = `infralens-${Date.now()}`;
  const encodedSubject = `=?UTF-8?B?${Buffer.from(subject).toString("base64")}?=`;
  const body = [
    `From: ${from}`,
    `To: ${to}`,
    `Subject: ${encodedSubject}`,
    "MIME-Version: 1.0",
    `Content-Type: multipart/alternative; boundary="${boundary}"`,
    "",
    `--${boundary}`,
    "Content-Type: text/plain; charset=utf-8",
    "Content-Transfer-Encoding: 8bit",
    "",
    text,
    `--${boundary}`,
    "Content-Type: text/html; charset=utf-8",
    "Content-Transfer-Encoding: 8bit",
    "",
    html,
    `--${boundary}--`,
    "",
  ].join("\r\n");
  return body.replace(/^\./gm, "..");
}

function office365(host) {
  const name = host.toLowerCase();
  return name === "smtp.office365.com" || name.endsWith(".office365.com");
}

async function graphToken(settings) {
  const body = new URLSearchParams({
    client_id: process.env.SMTP_OAUTH_CLIENT_ID || OFFICE_CLIENT_ID,
    grant_type: "password",
    username: settings.user,
    password: settings.password,
    scope: "https://graph.microsoft.com/Mail.Send",
  });
  const response = await fetch("https://login.microsoftonline.com/organizations/oauth2/v2.0/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
    signal: AbortSignal.timeout(settings.timeoutMs),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || !payload.access_token) {
    const description = String(payload.error_description || payload.error || "Microsoft login failed");
    const marker = description.split(/\s+/).find((part) => part.startsWith("AADSTS")) || payload.error || "Microsoft login failed";
    throw new Error(String(marker).replace(/:$/, ""));
  }
  return payload.access_token;
}

async function sendViaGraph(settings, { to, subject, text, html }) {
  const token = await graphToken(settings);
  const response = await fetch("https://graph.microsoft.com/v1.0/me/sendMail", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      message: {
        subject,
        body: { contentType: html ? "HTML" : "Text", content: html || text },
        toRecipients: [{ emailAddress: { address: to } }],
      },
      saveToSentItems: false,
    }),
    signal: AbortSignal.timeout(settings.timeoutMs),
  });
  if (response.status === 202 || response.ok) return;
  const payload = await response.json().catch(() => ({}));
  throw new Error(payload.error?.code || `Graph ${response.status}`);
}

export async function sendEmail({ to, subject, text, html }) {
  const settings = mailSettings();
  if (!mailConfigured()) return { ok: false, error: "Email is not configured." };
  const recipient = String(to || "").trim();
  if (!recipient.includes("@")) return { ok: false, error: "That email address is not valid." };
  let socket;
  try {
    if (office365(settings.host)) {
      await sendViaGraph(settings, { to: recipient, subject, text, html });
      return { ok: true };
    }
    socket = await connectSocket(settings);
    await readReply(socket);
    await sendCommand(socket, "EHLO infralens");
    let active = socket;
    if (settings.port !== 465) {
      await sendCommand(socket, "STARTTLS");
      active = await upgradeTls(socket, settings.host, settings.timeoutMs);
      await sendCommand(active, "EHLO infralens");
    }
    await sendCommand(active, "AUTH LOGIN");
    await sendCommand(active, Buffer.from(settings.user).toString("base64"));
    await sendCommand(active, Buffer.from(settings.password).toString("base64"));
    await sendCommand(active, `MAIL FROM:<${settings.fromAddress}>`);
    await sendCommand(active, `RCPT TO:<${recipient}>`);
    await sendCommand(active, "DATA");
    await sendCommand(active, `${messageBody({
      from: fromHeader(settings),
      to: recipient,
      subject,
      text,
      html,
    })}\r\n.`);
    await sendCommand(active, "QUIT");
    active.end();
    return { ok: true };
  } catch (err) {
    if (socket) socket.destroy();
    const codes = [err?.code, ...(err?.errors || []).map((item) => item.code)].filter(Boolean);
    const detail = String(err?.message || codes.join(" ") || "Email could not be sent.");
    console.error("SMTP send failed:", detail);
    const unreachable = codes.includes("ETIMEDOUT") || codes.includes("ECONNREFUSED") || codes.includes("ENETUNREACH");
    return { ok: false, error: unreachable ? "Could not reach the mail server." : "Email could not be sent." };
  }
}
