"""Email delivery through Gmail's SMTP server using a 16-character App Password."""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

import config


class MailerError(RuntimeError):
    pass


def build_message(to_name: str, to_email: str, subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((config.SENDER_NAME, config.GMAIL_ADDRESS))
    msg["To"] = formataddr((to_name, to_email))
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="email-agent.local")
    msg["X-Mailer"] = "Experiment9-AI-Email-Agent"
    msg.set_content(body.rstrip() + config.FOOTER)
    return msg


def send_email(to_name: str, to_email: str, subject: str, body: str) -> str:
    """Send one email and return its Message-ID (raises MailerError on failure)."""
    msg = build_message(to_name, to_email, subject, body)
    if config.DRY_RUN:
        return msg["Message-ID"] + " (dry run - not delivered)"
    if not (config.GMAIL_ADDRESS and len(config.GMAIL_APP_PASSWORD) == 16):
        raise MailerError("Gmail credentials missing — run `python setup_credentials.py`.")
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, context=context, timeout=30) as smtp:
            smtp.login(config.GMAIL_ADDRESS, config.GMAIL_APP_PASSWORD)
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        raise MailerError(f"SMTP send failed: {exc}") from exc
    return msg["Message-ID"]
