from __future__ import annotations

import json
import os
import smtplib
import urllib.error
import urllib.request
from email.message import EmailMessage
from pathlib import Path
from typing import Iterable, List, Optional, Set, Tuple

from urllib.parse import urlencode

from .checks import Alert
from .config import Config


def _unique(sequence: Iterable[str]) -> List[str]:
    return list(dict.fromkeys(sequence))


def _load_subscriber_state(path: Path) -> Tuple[Set[str], Optional[int]]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return set(), None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Telegram subscriber store {path} is corrupted: {exc}") from exc
    chat_ids = {str(item) for item in data.get("chat_ids", [])}
    last_update_id = data.get("last_update_id")
    if last_update_id is not None:
        try:
            last_update_id = int(last_update_id)
        except (TypeError, ValueError):
            raise RuntimeError(f"Telegram subscriber store {path} has invalid last_update_id")
    return chat_ids, last_update_id


def _write_subscriber_state(path: Path, chat_ids: Set[str], last_update_id: Optional[int]) -> None:
    payload = {
        "chat_ids": sorted(chat_ids),
        "last_update_id": last_update_id,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _poll_telegram_updates(config: Config, token: str, *, chat_ids: Set[str], last_update_id: Optional[int]) -> Tuple[Set[str], Optional[int]]:
    base = config.notification.telegram.api_base.rstrip("/")
    query: dict[str, str] = {"timeout": "0"}
    if last_update_id is not None:
        query["offset"] = str(last_update_id + 1)
    url = f"{base}/bot{token}/getUpdates"
    if query:
        url = f"{url}?{urlencode(query)}"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=config.notification.telegram.request_timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore") if hasattr(exc, "read") else str(exc)
        raise RuntimeError(f"Telegram HTTP error {exc.code} while polling updates: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Telegram network error while polling updates: {exc.reason}") from exc

    if not data.get("ok", False):
        raise RuntimeError(f"Telegram API error on getUpdates: {data}")

    max_update_id = last_update_id
    for update in data.get("result", []):
        update_id = update.get("update_id")
        if isinstance(update_id, int):
            if max_update_id is None or update_id > max_update_id:
                max_update_id = update_id
        message = update.get("message") or update.get("edited_message")
        if not message:
            continue
        chat = message.get("chat")
        if not chat or chat.get("type") != "private":
            continue
        text = message.get("text", "")
        if text.strip() != "/start":
            continue
        chat_id = chat.get("id")
        if chat_id is not None:
            chat_ids.add(str(chat_id))

    return chat_ids, max_update_id


def build_email(config: Config, alerts: Iterable[Alert], body: str) -> EmailMessage:
    mail_cfg = config.notification.mail
    msg = EmailMessage()
    msg["From"] = mail_cfg.sender
    msg["To"] = ", ".join(mail_cfg.recipients)
    if mail_cfg.cc:
        msg["Cc"] = ", ".join(mail_cfg.cc)
    subject_prefix = mail_cfg.subject_prefix or "Spondex Monitor"
    subject_tail = "Alerts" if alerts else "Report"
    msg["Subject"] = f"{subject_prefix} {subject_tail}".strip()
    msg.set_content(body)
    return msg


def send_alert_email(config: Config, alerts: list[Alert], body: str, *, force: bool = False) -> bool:
    mail_cfg = config.notification.mail
    if not mail_cfg.enabled:
        return False
    if not (force or alerts):
        return False

    msg = build_email(config, alerts, body)
    recipients = _unique(mail_cfg.recipients + mail_cfg.cc)
    try:
        with smtplib.SMTP("localhost") as smtp:
            smtp.send_message(msg, to_addrs=recipients or None)
    except Exception as exc:  # pragma: no cover - network failure handling
        raise RuntimeError(f"Mail delivery failed: {exc}") from exc
    return True


def _telegram_endpoint(config: Config, token: str) -> str:
    base = config.notification.telegram.api_base.rstrip("/")
    return f"{base}/bot{token}/sendMessage"


def _truncate_for_telegram(message: str) -> str:
    if len(message) <= 4096:
        return message
    return message[:4093] + "..."


def send_alert_telegram(config: Config, alerts: list[Alert], body: str, *, force: bool = False) -> bool:
    tg_cfg = config.notification.telegram
    if not tg_cfg.enabled:
        return False
    if not (force or alerts):
        return False

    token = tg_cfg.token or os.environ.get(tg_cfg.bot_token_env)
    if not token:
        raise RuntimeError(
            f"Telegram bot token not provided (env {tg_cfg.bot_token_env} is empty and no inline token configured)"
        )

    subscriber_chat_ids: List[str] = []
    last_update_id: Optional[int] = None
    subscriber_path: Optional[Path] = None
    if tg_cfg.subscriber_store:
        subscriber_path = Path(tg_cfg.subscriber_store)
        subscribers, last_update_id = _load_subscriber_state(subscriber_path)
        if tg_cfg.poll_updates:
            subscribers, last_update_id = _poll_telegram_updates(
                config,
                token,
                chat_ids=subscribers,
                last_update_id=last_update_id,
            )
        subscriber_chat_ids = sorted(subscribers)
        if subscriber_path:
            _write_subscriber_state(subscriber_path, set(subscriber_chat_ids), last_update_id)

    chat_id_candidates = _unique(list(tg_cfg.chat_ids) + subscriber_chat_ids)
    if not chat_id_candidates:
        raise RuntimeError("Telegram chat_ids list is empty")

    url = _telegram_endpoint(config, token)
    payload_text = _truncate_for_telegram(body)
    payload_common = {
        "text": payload_text,
        "disable_web_page_preview": True,
    }

    for chat_id in chat_id_candidates:
        payload = dict(payload_common, chat_id=chat_id)
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=tg_cfg.request_timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "ignore") if hasattr(exc, "read") else str(exc)
            raise RuntimeError(f"Telegram HTTP error {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Telegram network error: {exc.reason}") from exc

        if not data.get("ok", False):
            raise RuntimeError(f"Telegram API error: {data}")

    return True


def send_notifications(config: Config, alerts: list[Alert], body: str, *, force: bool = False) -> List[str]:
    """Send alerts using enabled channels.

    Returns a list of error messages for channels that failed.
    """

    errors: List[str] = []

    try:
        send_alert_telegram(config, alerts, body, force=force)
    except RuntimeError as exc:
        errors.append(f"telegram: {exc}")

    try:
        send_alert_email(config, alerts, body, force=force)
    except RuntimeError as exc:
        errors.append(f"email: {exc}")

    return errors


__all__ = [
    "build_email",
    "send_alert_email",
    "send_alert_telegram",
    "send_notifications",
]
