import { detailTable, emailDocument } from "./email-layout.js";
import { sendEmail } from "./mail.js";

function clientIp(request) {
  const marked = request.headers.get("x-infralens-client") || "";
  const forwarded = request.headers.get("x-forwarded-for") || "";
  const real = request.headers.get("x-real-ip") || "";
  return String(marked || forwarded.split(",")[0] || real).trim();
}

function publicIp(ip) {
  if (!ip || ip === "::1" || ip === "0.0.0.0") return false;
  if (ip.startsWith("127.") || ip.startsWith("10.") || ip.startsWith("192.168.") || ip.startsWith("169.254.")) return false;
  if (ip.startsWith("172.")) {
    const second = Number(ip.split(".")[1]);
    if (second >= 16 && second <= 31) return false;
  }
  const lower = ip.toLowerCase();
  if (lower.startsWith("fc") || lower.startsWith("fd") || lower.startsWith("fe80")) return false;
  return true;
}

function deviceLabel(userAgent) {
  const ua = String(userAgent || "");
  const browser = /Edg\//.test(ua) ? "Edge"
    : /Chrome\//.test(ua) ? "Chrome"
      : /Firefox\//.test(ua) ? "Firefox"
        : /Safari\//.test(ua) ? "Safari"
          : "";
  const os = /Windows/.test(ua) ? "Windows"
    : /Mac OS/.test(ua) ? "macOS"
      : /Android/.test(ua) ? "Android"
        : /iPhone|iPad/.test(ua) ? "iOS"
          : /Linux/.test(ua) ? "Linux"
            : "";
  return [browser, os].filter(Boolean).join(" on ") || "Unknown device";
}

async function lookup(ip) {
  const url = ip ? `https://ipwho.is/${encodeURIComponent(ip)}` : "https://ipwho.is/";
  const response = await fetch(url, { signal: AbortSignal.timeout(2500) });
  const body = await response.json().catch(() => ({}));
  if (!body.success) return "";
  return [body.city, body.region, body.country].filter(Boolean).join(", ");
}

async function placeFor(ip) {
  try {
    if (publicIp(ip)) return (await lookup(ip)) || "Location unavailable";
    const local = await lookup("");
    return local ? `${local} (this network)` : "Private network";
  } catch {
    return publicIp(ip) ? "Location unavailable" : "Private network";
  }
}

function noticeEmail({ when, place, device }) {
  const subject = "Your Infralens account was signed in";
  const text = [
    "Your Infralens account was just signed in.",
    "If this was you, you can ignore this email.",
    "",
    `When: ${when}`,
    `Where: ${place}`,
    `Device: ${device}`,
    "",
    "If you did not sign in, tell your organization admin.",
  ].join("\n");
  const html = emailDocument({
    preheader: `Signed in from ${place}. If this was you, ignore this email.`,
    eyebrow: "Security",
    title: "Your account was signed in",
    intro: "If this was you, you can ignore this email.",
    content: detailTable([
      { label: "When", value: when },
      { label: "Where", value: place },
      { label: "Device", value: device },
    ]),
    note: "If you did not sign in, tell your organization admin.",
  });
  return { subject, text, html };
}

export async function sendLoginNotice(request, email) {
  const recipient = String(email || "").trim();
  if (!recipient.includes("@")) return;
  const when = `${new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }).format(new Date())} UTC`;
  const place = await placeFor(clientIp(request));
  const device = deviceLabel(request.headers.get("user-agent"));
  const message = noticeEmail({ when, place, device });
  const sent = await sendEmail({ to: email, ...message });
  if (!sent.ok) console.error("Login notice failed:", sent.error);
}
