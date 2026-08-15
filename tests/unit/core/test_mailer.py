"""SMTP mailer success, skip, timeout, and invite/membership helpers."""
from __future__ import annotations

import smtplib
from unittest.mock import MagicMock, patch

import pytest

from app.core import mailer


@pytest.mark.unit
def test_smtp_configured_and_public_url(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    assert mailer.smtp_configured() is False
    monkeypatch.setenv("SMTP_HOST", "smtp.example")
    assert mailer.smtp_configured() is True
    monkeypatch.delenv("PUBLIC_APP_URL", raising=False)
    monkeypatch.delenv("FRONTEND_URL", raising=False)
    assert mailer.public_app_url() == "http://127.0.0.1:3000"
    monkeypatch.setenv("PUBLIC_APP_URL", "https://app.example/")
    assert mailer.public_app_url() == "https://app.example"


@pytest.mark.unit
def test_send_email_skips_without_host(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    assert mailer.send_email(to="a@b.c", subject="s", body_text="hi") is False


@pytest.mark.unit
def test_send_email_success_with_html_and_starttls(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("SMTP_USER", "user")
    monkeypatch.setenv("SMTP_PASS", "pass")
    smtp = MagicMock()
    smtp.has_extn.return_value = True
    smtp.__enter__.return_value = smtp
    smtp.__exit__.return_value = False
    with patch("app.core.mailer.smtplib.SMTP", return_value=smtp):
        assert mailer.send_email(
            to="a@b.c", subject="Hello", body_text="text", body_html="<p>hi</p>"
        )
    smtp.starttls.assert_called()
    smtp.login.assert_called_once_with("user", "pass")
    smtp.send_message.assert_called()


@pytest.mark.unit
def test_send_email_login_failure_still_attempts_send(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    monkeypatch.setenv("SMTP_USER", "user")
    monkeypatch.setenv("SMTP_PASS", "pass")
    smtp = MagicMock()
    smtp.has_extn.return_value = False
    smtp.login.side_effect = smtplib.SMTPException("nope")
    smtp.__enter__.return_value = smtp
    smtp.__exit__.return_value = False
    with patch("app.core.mailer.smtplib.SMTP", return_value=smtp):
        assert mailer.send_email(to="a@b.c", subject="s", body_text="t")
    smtp.send_message.assert_called()


@pytest.mark.unit
def test_send_email_timeout_and_oserror(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    with patch("app.core.mailer.smtplib.SMTP", side_effect=TimeoutError):
        assert mailer.send_email(to="a@b.c", subject="s", body_text="t") is False
    with patch("app.core.mailer.smtplib.SMTP", side_effect=OSError("down")):
        assert mailer.send_email(to="a@b.c", subject="s", body_text="t") is False


@pytest.mark.unit
def test_invite_and_membership_emails_include_links(monkeypatch):
    monkeypatch.setenv("PUBLIC_APP_URL", "https://app.test")
    with patch("app.core.mailer.send_email", return_value=True) as send:
        assert mailer.send_invite_email(
            to="x@y.z", org_name="Acme", inviter_name="Pat", token="tok"
        )
        kwargs = send.call_args.kwargs
        assert "https://app.test/accept-invite?token=tok" in kwargs["body_text"]
        assert mailer.send_membership_request_email(
            to="lead@y.z",
            project_name="P",
            requester_name="Dev",
            action="add",
            target="new@y.z",
            approve_token="atk",
            request_id="rid",
        )
        kwargs = send.call_args.kwargs
        assert "approve-member?token=atk" in kwargs["body_text"]
        assert "rid" in kwargs["body_text"]
