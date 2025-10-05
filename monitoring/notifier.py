from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable, List, Optional, Set, Tuple

from urllib.parse import urlencode

from .checks import Alert, CheckContext
from .config import Config


def _send_telegram_payload(
    config: Config,
    token: str,
    payload: dict[str, object],
    *,
    timeout: float,
) -> dict:
    url = _telegram_endpoint(config, token)
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore") if hasattr(exc, "read") else str(exc)
        raise RuntimeError(f"Telegram HTTP error {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Telegram network error: {exc.reason}") from exc

    if not data.get("ok", False):
        raise RuntimeError(f"Telegram API error: {data}")
    return data


def _send_telegram_message(
    config: Config,
    token: str,
    chat_id: str,
    text: str,
    *,
    timeout: float,
    disable_preview: bool = True,
) -> None:
    payload = {
        "chat_id": chat_id,
        "text": _truncate_for_telegram(text),
    }
    if disable_preview:
        payload["disable_web_page_preview"] = True
    _send_telegram_payload(config, token, payload, timeout=timeout)


def _format_container_names(config: Config) -> Optional[str]:
    if not config.app_checks:
        return None
    names = {check.display_name or check.container_name for check in config.app_checks}
    if not names:
        return None
    return ", ".join(sorted(names))


def _format_disk_usage_targets(config: Config) -> Optional[str]:
    if not config.disk_usage_checks:
        return None
    items = []
    for check in config.disk_usage_checks:
        label = check.name
        path = str(check.path)
        if path:
            label = f"{label} ({path})"
        items.append(label)
    return ", ".join(items) if items else None


def _format_log_targets(config: Config) -> Optional[str]:
    if not config.log_checks:
        return None
    items = [str(log.path) for log in config.log_checks]
    return ", ".join(items) if items else None


def _build_welcome_message(config: Config) -> str:
    bullet_lines = [
        "• загрузкой CPU (1, 5 и 15 минут), использованием памяти и событиями OOM",
        "• перезагрузками сервера и статусом docker.service",
    ]

    containers = _format_container_names(config)
    if containers:
        bullet_lines.append(f"• контейнерами приложения: {containers}")

    bullet_lines.append(
        f"• PostgreSQL ({config.db_check.container_name}) — контейнер, порт и проверочный SELECT 1"
    )

    disk_usage = _format_disk_usage_targets(config)
    if disk_usage:
        bullet_lines.append(f"• заполнением дисков: {disk_usage}")

    if config.disk_devices:
        devices = ", ".join(sorted({device.name for device in config.disk_devices}))
        bullet_lines.append(f"• IOPS на устройствах: {devices}")

    logs = _format_log_targets(config)
    if logs:
        bullet_lines.append(f"• ошибками в логах: {logs}")

    lines = [
        f"Привет! Это бот мониторинга {config.service_name}.",
        "Я слежу за продовой инфраструктурой и присылаю алерты, если что-то идёт не так.",
        "",
        "Слежу за:",
        *bullet_lines,
        "",
        "Чтобы проверить доставку вручную, на сервере можно выполнить python -m monitoring.monitor --test-notify.",
    ]
    return "\n".join(lines)


def _welcome_new_subscribers(
    config: Config,
    token: str,
    chat_ids: Set[str],
    *,
    timeout: float,
) -> None:
    if not chat_ids:
        return
    message = _build_welcome_message(config)
    for chat_id in sorted(chat_ids):
        _send_telegram_message(config, token, chat_id, message, timeout=timeout)


def _sync_subscriber_store(
    config: Config,
    token: str,
    *,
    allow_poll: bool,
) -> Tuple[List[str], Optional[int]]:
    tg_cfg = config.notification.telegram
    if not tg_cfg.subscriber_store:
        return [], None

    subscriber_path = Path(tg_cfg.subscriber_store)
    subscribers, last_update_id = _load_subscriber_state(subscriber_path)
    new_chat_ids: Set[str] = set()
    if allow_poll and tg_cfg.poll_updates:
        subscribers, last_update_id, new_chat_ids = _poll_telegram_updates(
            config,
            token,
            chat_ids=subscribers,
            last_update_id=last_update_id,
        )
        if new_chat_ids:
            _welcome_new_subscribers(config, token, new_chat_ids, timeout=tg_cfg.request_timeout)

    _write_subscriber_state(subscriber_path, subscribers, last_update_id)
    sorted_ids = sorted(subscribers)
    return sorted_ids, last_update_id


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


def _poll_telegram_updates(
    config: Config,
    token: str,
    *,
    chat_ids: Set[str],
    last_update_id: Optional[int],
) -> Tuple[Set[str], Optional[int], Set[str]]:
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
    new_chat_ids: Set[str] = set()
    for update in data.get("result", []):
        update_id = update.get("update_id")
        if isinstance(update_id, int):
            if max_update_id is None or update_id > max_update_id:
                max_update_id = update_id
        message = update.get("message") or update.get("edited_message")
        if not message:
            continue
        chat = message.get("chat")
        if not chat:
            continue
        text = message.get("text", "").strip()
        chat_id = chat.get("id")
        if chat_id is None:
            continue
        chat_id_str = str(chat_id)
        
        if text == "/start" and chat.get("type") == "private":
            if chat_id_str not in chat_ids:
                new_chat_ids.add(chat_id_str)
            chat_ids.add(chat_id_str)
        elif text == "/status" and chat_id_str in chat_ids:
            # Handle /status command for subscribed users
            _handle_status_command(config, token, chat_id_str)
        elif text == "/help" and chat_id_str in chat_ids:
            # Handle /help command for subscribed users
            _handle_help_command(config, token, chat_id_str)

    return chat_ids, max_update_id, new_chat_ids


def _handle_status_command(config: Config, token: str, chat_id: str) -> None:
    """Handle /status command by sending current metrics to the user."""
    try:
        from .checks import run_checks
        from .monitor import format_report
        from .storage import StateStore
        from datetime import datetime
        
        # Get current metrics
        now = datetime.now().astimezone()
        store = StateStore(config.state_path)
        ctx = CheckContext(config=config, store=store, now=now)
        
        metrics, alerts = run_checks(ctx)
        
        # Format report
        report = format_report(now, alerts, metrics)
        
        # Send to user
        _send_telegram_message(config, token, chat_id, report, timeout=config.notification.telegram.request_timeout)
        
    except Exception as e:
        # Send error message if something goes wrong
        error_msg = f"Error getting status: {str(e)}"
        try:
            _send_telegram_message(config, token, chat_id, error_msg, timeout=config.notification.telegram.request_timeout)
        except Exception:
            pass  # Ignore errors when sending error messages


def _handle_help_command(config: Config, token: str, chat_id: str) -> None:
    """Handle /help command by sending help information to the user."""
    help_text = """🤖 

Команды:
/start - Подписаться на уведомления об алертах
/status - Получить текущий статус системы и метрики
/help - Показать эту справку

📊 Мониторинг метрик:
• CPU загрузка (1, 5, 15 минут)
• Использование памяти и события OOM
• Перезагрузки сервера
• Статус docker.service
• Контейнеры приложения (spondex_app, spondex_postgres)
• Использование диска
• Логи приложений
• Синхронизация Yandex Music (последняя синхронизация, статус API)
• Плейлисты и избранные треки/альбомы/исполнители

🚨 Алерт уровни:
• CRITICAL - Критические проблемы требующие немедленного внимания
• WARNING - Предупреждения о потенциальных проблемах
• INFO - Информационные сообщения (включая разрешение алертов)

💡 Логика работы:
• Алерт отправляется только при первом появлении
• При разрешении алерта приходит уведомление
• /status показывает текущее состояние всех метрик
• Мониторинг запускается каждые 5 минут"""

    try:
        _send_telegram_message(config, token, chat_id, help_text, timeout=config.notification.telegram.request_timeout)
    except Exception as e:
        # Send error message if something goes wrong
        error_msg = f"Error sending help: {str(e)}"
        try:
            _send_telegram_message(config, token, chat_id, error_msg, timeout=config.notification.telegram.request_timeout)
        except Exception:
            pass  # Ignore errors when sending error messages


def _telegram_endpoint(config: Config, token: str) -> str:
    base = config.notification.telegram.api_base.rstrip("/")
    return f"{base}/bot{token}/sendMessage"
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

    subscriber_chat_ids, _ = _sync_subscriber_store(config, token, allow_poll=True)

    chat_id_candidates = _unique(list(tg_cfg.chat_ids) + subscriber_chat_ids)
    if not chat_id_candidates:
        # No subscribers - not an error, just nothing to send
        return False

    for chat_id in chat_id_candidates:
        _send_telegram_message(
            config,
            token,
            chat_id,
            body,
            timeout=tg_cfg.request_timeout,
        )

    return True


def poll_telegram_subscribers(config: Config) -> bool:
    tg_cfg = config.notification.telegram
    if not tg_cfg.enabled or not tg_cfg.poll_updates or not tg_cfg.subscriber_store:
        return False

    token = tg_cfg.token or os.environ.get(tg_cfg.bot_token_env)
    if not token:
        raise RuntimeError(
            f"Telegram bot token not provided (env {tg_cfg.bot_token_env} is empty and no inline token configured)"
        )

    _sync_subscriber_store(config, token, allow_poll=True)
    return True


def send_notifications(config: Config, alerts: list[Alert], body: str, *, force: bool = False) -> List[str]:
    """Send alerts using enabled channels.

    Returns a list of error messages for channels that failed.
    """

    errors: List[str] = []

    try:
        if not send_alert_telegram(config, alerts, body, force=force):
            # No subscribers configured - not an error
            pass
    except RuntimeError as exc:
        errors.append(f"telegram: {exc}")

    return errors


__all__ = [
    "send_alert_telegram",
    "poll_telegram_subscribers",
    "send_notifications",
]
