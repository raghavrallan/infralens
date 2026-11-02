"""SMTP mailer for invites and membership-approval emails."""
from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage
from typing import Optional

logger = logging.getLogger(__name__)


def smtp_configured() -> bool:
    return bool(os.environ.get("SMTP_HOST", "").strip())


def public_app_url() -> str:
    return (
        os.environ.get("PUBLIC_APP_URL")
        or os.environ.get("FRONTEND_URL")
        or "http://127.0.0.1:3000"
    ).rstrip("/")


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
    port = int(os.environ.get("SMTP_PORT", "2525") or "2525")
    # Keep timeout short so invite APIs stay responsive when relay is unreachable.
    timeout = float(os.environ.get("SMTP_TIMEOUT", "8") or "8")
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASS", "")
    from_addr = (
        os.environ.get("SMTP_FROM", "").strip()
        or user
        or "noreply@infralens.local"
    )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to
    msg.set_content(body_text)
    if body_html:
        msg.add_alternative(body_html, subtype="html")

    try:
        with smtplib.SMTP(host, port, timeout=timeout) as smtp:
            try:
                smtp.ehlo()
                if smtp.has_extn("starttls"):
                    smtp.starttls()
                    smtp.ehlo()
            except Exception:
                pass
            if user and password:
                try:
                    smtp.login(user, password)
                except smtplib.SMTPException:
                    logger.warning("SMTP login failed; attempting unauthenticated send")
            smtp.send_message(msg)
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


def send_invite_email(*, to: str, org_name: str, inviter_name: str, token: str) -> bool:
    link = f"{public_app_url()}/accept-invite?token={token}"
    subject = f"You're invited to {org_name} on InfraLens"
    text = (
        f"{inviter_name} invited you to join {org_name} on InfraLens.\n\n"
        f"Accept your invite:\n{link}\n\n"
        f"This link expires in 7 days.\n"
    )
    html = (
        f"<p><strong>{inviter_name}</strong> invited you to join "
        f"<strong>{org_name}</strong> on InfraLens.</p>"
        f'<p><a href="{link}">Accept invite</a></p>'
        f"<p>This link expires in 7 days.</p>"
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
    html = (
        f"<p><strong>{requester_name}</strong> requested to <strong>{action}</strong> "
        f"member <code>{target}</code> on project <strong>{project_name}</strong>.</p>"
        f'<p><a href="{portal}">Open Org Admin console</a> · '
        f'<a href="{email_link}">Approve via email</a></p>'
    )
    return send_email(to=to, subject=subject, body_text=text, body_html=html)
