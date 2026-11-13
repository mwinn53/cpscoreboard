"""Outgoing email: SES in production, SMTP (Mailpit) in the dev container, console otherwise."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Protocol

from .config import Settings

log = logging.getLogger(__name__)


class Mailer(Protocol):
    description: str

    def send(self, to: str, subject: str, text: str) -> None:
        """Send synchronously; raise on failure. Callers run this in a thread."""


class ConsoleMailer:
    """Logs the message instead of sending it (local runs without Mailpit)."""
    description = "console (emails are logged, not sent)"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def send(self, to: str, subject: str, text: str) -> None:
        self.sent.append((to, subject, text))
        log.warning("EMAIL (not sent) to=%s subject=%r\n%s", to, subject, text)


class SmtpMailer:
    def __init__(self, host: str, port: int, sender: str):
        self.host, self.port, self.sender = host, port, sender
        self.description = f"smtp {host}:{port}"

    def send(self, to: str, subject: str, text: str) -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.sender, to, subject
        msg.set_content(text)
        with smtplib.SMTP(self.host, self.port, timeout=15) as smtp:
            smtp.send_message(msg)


class SesMailer:
    def __init__(self, region: str, sender: str):
        import boto3  # only needed in production

        self.client = boto3.client("sesv2", region_name=region)
        self.sender = sender
        self.description = f"ses ({region})"

    def send(self, to: str, subject: str, text: str) -> None:
        self.client.send_email(
            FromEmailAddress=self.sender,
            Destination={"ToAddresses": [to]},
            Content={"Simple": {"Subject": {"Data": subject, "Charset": "UTF-8"},
                                "Body": {"Text": {"Data": text, "Charset": "UTF-8"}}}},
        )


def build_mailer(settings: Settings) -> Mailer:
    sender = f"{settings.mail_from_name} <{settings.mail_from}>"
    backend = settings.mail_backend
    if backend == "auto":
        backend = "smtp" if settings.smtp_host else ("ses" if settings.app_env == "prod" else "console")
    if backend == "ses":
        return SesMailer(settings.aws_region, sender)
    if backend == "smtp":
        return SmtpMailer(settings.smtp_host or "localhost", settings.smtp_port, sender)
    return ConsoleMailer()
