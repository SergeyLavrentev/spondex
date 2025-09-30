from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Iterable

from .checks import Alert
from .config import Config


def build_email(config: Config, alerts: Iterable[Alert], body: str) -> EmailMessage:
    msg = EmailMessage()
    recipients = list(dict.fromkeys(config.notification.mail_to + config.additional_recipients))
    msg["From"] = config.notification.mail_from
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = f"{config.notification.mail_subject_prefix} Alerts" if config.notification.mail_subject_prefix else "Spondex Monitor Alerts"
    msg.set_content(body)
    return msg


def send_alert_email(config: Config, alerts: list[Alert], body: str) -> None:
    if not config.enable_email or not alerts:
        return
    msg = build_email(config, alerts, body)
    with smtplib.SMTP("localhost") as smtp:
        smtp.send_message(msg)


__all__ = ["send_alert_email", "build_email"]
