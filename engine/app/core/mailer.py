"""SMTP mailer for invites and membership-approval emails."""
from __future__ import annotations

import json
import logging
import os
import smtplib
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from typing import Optional

OFFICE_CLIENT_ID = "d3590ed6-52b3-4102-aeff-aad2292ab01c"

logger = logging.getLogger(__name__)


def smtp_configured() -> bool:
    return bool(os.environ.get("SMTP_HOST", "").strip())


def public_app_url() -> str:
    return (
        os.environ.get("PUBLIC_APP_URL")
        or os.environ.get("FRONTEND_URL")
        or "http://127.0.0.1:3000"
    ).rstrip("/")


def _office365(host: str) -> bool:
    name = host.lower()
    return name == "smtp.office365.com" or name.endswith(".office365.com")


def _graph_error(raw: str) -> str:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return "Microsoft login failed"
    description = str(payload.get("error_description") or payload.get("error") or "")
    for part in description.split():
        if part.startswith("AADSTS"):
            return part.rstrip(":")
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("code") or "Graph send failed")
    return str(error or "Microsoft login failed")


def send_via_graph(*, to: str, subject: str, body_text: str, body_html: Optional[str], user: str, password: str, timeout: float) -> None:
    form = urllib.parse.urlencode({
        "client_id": os.environ.get("SMTP_OAUTH_CLIENT_ID", "").strip() or OFFICE_CLIENT_ID,
        "grant_type": "password",
        "username": user,
        "password": password,
        "scope": "https://graph.microsoft.com/Mail.Send",
    }).encode()
    token_request = urllib.request.Request(
        "https://login.microsoftonline.com/organizations/oauth2/v2.0/token",
        data=form,
        method="POST",
    )
    try:
        with urllib.request.urlopen(token_request, timeout=timeout) as response:
            token = json.loads(response.read().decode()).get("access_token")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(_graph_error(exc.read().decode())) from exc
    if not token:
        raise RuntimeError("Microsoft login failed")
    message = {
        "message": {
            "subject": subject,
            "body": {
                "contentType": "HTML" if body_html else "Text",
                "content": body_html or body_text,
            },
            "toRecipients": [{"emailAddress": {"address": to}}],
        },
        "saveToSentItems": False,
    }
    send_request = urllib.request.Request(
        "https://graph.microsoft.com/v1.0/me/sendMail",
        data=json.dumps(message).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(send_request, timeout=timeout) as response:
            if response.status not in (200, 202):
                raise RuntimeError(f"Graph {response.status}")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(_graph_error(exc.read().decode())) from exc


def send_email(
    *,
    to: str,
    subject: str,
    body_text: str,
    body_html: Optional[str] = None,
) -> bool:
    """Send email via SMTP. Returns True on success. Logs and returns False on failure."""
    host = os.environ.get("SMTP_HOST", "").strip()
    if not host:
        logger.warning("SMTP_HOST not set; skipping email to %s", to)
        return False
    port = int(os.environ.get("SMTP_PORT", "587") or "587")
    timeout = float(os.environ.get("SMTP_TIMEOUT", "20") or "20")
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASS", "")
    from_addr = (
        os.environ.get("SMTP_FROM", "").strip()
        or user
        or "noreply@infralens.local"
    )
    from_name = os.environ.get("SMTP_FROM_NAME", "No Reply").strip() or "No Reply"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_addr}>"
    msg["To"] = to
    msg.set_content(body_text)
    if body_html:
        msg.add_alternative(body_html, subtype="html")

    try:
        if _office365(host):
            if not user or not password:
                logger.warning("Office 365 mailbox login is not set; skipping email to %s", to)
                return False
            send_via_graph(
                to=to,
                subject=subject,
                body_text=body_text,
                body_html=body_html,
                user=user,
                password=password,
                timeout=timeout,
            )
            logger.info("Email sent to %s subject=%s", to, subject)
            return True
        with smtplib.SMTP(host, port, timeout=timeout) as smtp:
            try:
                smtp.ehlo()
                if smtp.has_extn("starttls"):
                    smtp.starttls()
                    smtp.ehlo()
            except Exception:
                pass
            if user and password:
                smtp.login(user, password)
            smtp.send_message(msg, from_addr=from_addr)
        logger.info("Email sent to %s subject=%s", to, subject)
        return True
    except TimeoutError:
        logger.warning(
            "SMTP timeout connecting to %s:%s — invite still created; share accept link manually",
            host,
            port,
        )
        return False
    except OSError as exc:
        logger.warning(
            "SMTP unreachable (%s:%s): %s — invite still created; share accept link manually",
            host,
            port,
            exc,
        )
        return False
    except Exception:
        logger.exception("Failed to send email to %s", to)
        return False


def _escape(value: str) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _email_document(*, preheader: str, eyebrow: str, title: str, intro: str, content: str, note: str) -> str:
    font = "'DM Sans', 'Segoe UI', Helvetica, Arial, sans-serif"
    return f"""<!DOCTYPE html>
<html lang="en">
  <body style="margin:0;padding:0;background:#f7f6f4;">
    <div style="display:none;max-height:0;overflow:hidden;">{_escape(preheader)}</div>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f7f6f4;">
      <tr>
        <td align="center" style="padding:40px 16px;">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;">
            <tr><td style="height:4px;background:#e2773c;border-radius:4px 4px 0 0;font-size:0;line-height:0;">&nbsp;</td></tr>
            <tr>
              <td style="background:#ffffff;border:1px solid #e7e5e4;border-top:0;border-radius:0 0 24px 24px;padding:32px 32px 28px;">
                <div style="font-family:{font};font-size:14px;font-weight:700;color:#e2773c;">Infralens</div>
                <div style="margin-top:22px;font-family:{font};font-size:12px;font-weight:700;letter-spacing:0.06em;text-transform:uppercase;color:#717171;">{_escape(eyebrow)}</div>
                <h1 style="margin:8px 0 0;font-family:{font};font-size:28px;line-height:1.25;font-weight:700;color:#232323;">{_escape(title)}</h1>
                <p style="margin:12px 0 0;font-family:{font};font-size:15px;line-height:1.6;color:#717171;">{intro}</p>
                {content}
                <p style="margin:18px 0 0;font-family:{font};font-size:13px;line-height:1.6;color:#717171;">{note}</p>
              </td>
            </tr>
            <tr>
              <td style="padding:18px 8px 0;text-align:center;font-family:{font};font-size:12px;line-height:1.6;color:#717171;">Infralens · No Reply<br>This mailbox is not monitored.</td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""


def _email_button(href: str, label: str) -> str:
    font = "'DM Sans', 'Segoe UI', Helvetica, Arial, sans-serif"
    return (
        '<table role="presentation" cellspacing="0" cellpadding="0" style="margin:22px 0 8px;"><tr>'
        '<td bgcolor="#e2773c" style="border-radius:16px;background:#e2773c;">'
        f'<a href="{_escape(href)}" style="display:inline-block;padding:14px 22px;font-family:{font};'
        f'font-size:14px;line-height:1;font-weight:700;color:#ffffff !important;text-decoration:none;">{_escape(label)}</a>'
        "</td></tr></table>"
    )


def send_invite_email(*, to: str, org_name: str, inviter_name: str, token: str) -> bool:
    link = f"{public_app_url()}/accept-invite?token={token}"
    subject = f"You're invited to {org_name} on InfraLens"
    text = (
        f"{inviter_name} invited you to join {org_name} on InfraLens.\n\n"
        f"Accept your invite:\n{link}\n\n"
        f"This link expires in 7 days.\n"
    )
    html = _email_document(
        preheader=f"{inviter_name} invited you to join {org_name}.",
        eyebrow="Invitation",
        title="Join your organization",
        intro=f"<strong>{_escape(inviter_name)}</strong> invited you to <strong>{_escape(org_name)}</strong> on Infralens.",
        content=_email_button(link, "Accept invite"),
        note="This link expires in 7 days.",
    )
    return send_email(to=to, subject=subject, body_text=text, body_html=html)


def send_membership_request_email(
    *,
    to: str,
    project_name: str,
    requester_name: str,
    action: str,
    target: str,
    approve_token: str,
    request_id: str,
) -> bool:
    portal = f"{public_app_url()}/organizations?tab=requests"
    email_link = f"{public_app_url()}/approve-member?token={approve_token}&id={request_id}"
    subject = f"Approve project member change: {project_name}"
    text = (
        f"{requester_name} requested to {action} member '{target}' on project {project_name}.\n\n"
        f"Approve via portal: {portal}\n"
        f"Or approve via email link: {email_link}\n"
    )
    html = _email_document(
        preheader=f"{requester_name} requested to {action} {target} on {project_name}.",
        eyebrow="Approval",
        title="Review a member change",
        intro=(
            f"<strong>{_escape(requester_name)}</strong> requested to <strong>{_escape(action)}</strong> "
            f"<strong>{_escape(target)}</strong> on <strong>{_escape(project_name)}</strong>."
        ),
        content=(
            _email_button(portal, "Review in Infralens")
            + f'<p style="margin:8px 0 0;font-family:\'DM Sans\',\'Segoe UI\',Helvetica,Arial,sans-serif;font-size:13px;line-height:1.5;">'
            f'<a href="{_escape(email_link)}" style="color:#e2773c;font-weight:700;text-decoration:none;">Approve from this email</a></p>'
        ),
        note="Approve only if you recognise this request.",
    )
    return send_email(to=to, subject=subject, body_text=text, body_html=html)
