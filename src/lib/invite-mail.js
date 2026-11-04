import { detailTable, emailButton, emailDocument, escapeHtml } from "./email-layout.js";
import { sendEmail } from "./mail.js";

export const INVITE_MINUTES = 15;

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
  const hello = recipientName ? `Hello ${escapeHtml(recipientName)}. ` : "";
  const html = emailDocument({
    preheader: `${inviterName} invited you to ${where}. Set your password within ${INVITE_MINUTES} minutes.`,
    eyebrow: "Invitation",
    title: "Set your password",
    intro: `${hello}${escapeHtml(inviterName)} invited you to Infralens. Choose your own password. Infralens does not create one for you.`,
    content: `${detailTable([
      { label: "Organization", value: orgName },
      { label: "Project", value: projectName },
      { label: "Role", value: roleName },
    ])}${emailButton(acceptUrl, "Set your password")}
    <p style="margin:14px 0 0;font-family:'DM Sans','Segoe UI',Helvetica,Arial,sans-serif;font-size:12px;line-height:1.5;color:#717171;word-break:break-all;">${escapeHtml(acceptUrl)}</p>`,
    note: `This link expires in ${INVITE_MINUTES} minutes and works once. If you were not expecting it, you can ignore this email.`,
  });
  return { subject, text, html };
}

export async function sendInviteEmail(input) {
  const message = inviteEmail(input);
  const sent = await sendEmail({ to: input.to, ...message });
  return sent.ok;
}
