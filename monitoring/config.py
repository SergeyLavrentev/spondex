from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional

import yaml


DEFAULT_CONFIG_PATHS: List[Path] = [
    Path("/etc/spondex-monitor/config.yaml"),
    Path("/opt/spondex/monitoring/config.yaml"),
    Path(__file__).resolve().parent / "config.yaml",
]


@dataclass
class DiskDevice:
    name: str
    max_iops: int
    include_reads: bool = True
    include_writes: bool = True


@dataclass
class DockerCheck:
    container_name: str
    display_name: Optional[str] = None


@dataclass
class DatabaseCheck:
    container_name: str
    host: str = "127.0.0.1"
    port: int = 5432
    user: str = "postgres"
    database: str = "postgres"
    password_env_var: Optional[str] = None


@dataclass
class DiskUsageCheck:
    name: str
    path: Path
    warn_percent: int = 85
    critical_percent: int = 95
    min_free_gb: int = 2


@dataclass
class LogCheck:
    path: Path
    pattern: str = "Traceback"


@dataclass
class MailNotification:
    enabled: bool = False
    recipients: List[str] = field(default_factory=lambda: ["root@localhost"])
    sender: str = "spondex-monitor@localhost"
    subject_prefix: str = "[Spondex Monitor]"
    cc: List[str] = field(default_factory=list)


@dataclass
class TelegramNotification:
    enabled: bool = True
    chat_ids: List[str] = field(default_factory=list)
    bot_token_env: str = "TG_BOT_TOKEN"
    token: Optional[str] = None
    api_base: str = "https://api.telegram.org"
    request_timeout: float = 10.0
    subscriber_store: Optional[Path] = None
    poll_updates: bool = False


@dataclass
class NotificationConfig:
    mail: MailNotification = field(default_factory=MailNotification)
    telegram: TelegramNotification = field(default_factory=TelegramNotification)


@dataclass
class Config:
    state_path: Path = field(default_factory=lambda: Path("/var/lib/spondex-monitor/state.db"))
    retention_days: int = 365
    cpu_cores: int = os.cpu_count() or 1
    load_window_minutes: int = 60
    memory_critical_threshold: float = 0.95  # 95% used
    docker_service_name: str = "docker"
    service_name: str = "Spondex"
    app_checks: List[DockerCheck] = field(default_factory=lambda: [DockerCheck("spondex-app-1", "app")])
    db_check: DatabaseCheck = field(default_factory=lambda: DatabaseCheck(container_name="spondex-postgres-1"))
    log_checks: List[LogCheck] = field(default_factory=list)
    disk_devices: List[DiskDevice] = field(default_factory=list)
    disk_usage_checks: List[DiskUsageCheck] = field(default_factory=lambda: [DiskUsageCheck(name="root", path=Path("/"))])
    notification: NotificationConfig = field(default_factory=NotificationConfig)
    compose_file: Optional[Path] = field(default_factory=lambda: Path("/opt/spondex/docker-compose.prod.yml"))


def _coerce_disk_devices(raw: Iterable[dict]) -> List[DiskDevice]:
    devices: List[DiskDevice] = []
    for item in raw:
        devices.append(
            DiskDevice(
                name=item["name"],
                max_iops=int(item.get("max_iops", 1000)),
                include_reads=bool(item.get("include_reads", True)),
                include_writes=bool(item.get("include_writes", True)),
            )
        )
    return devices


def _coerce_log_checks(raw: Iterable[dict]) -> List[LogCheck]:
    checks: List[LogCheck] = []
    for item in raw:
        checks.append(
            LogCheck(
                path=Path(item["path"]),
                pattern=str(item.get("pattern", "Traceback")),
            )
        )
    return checks


def _coerce_docker_checks(raw: Iterable[dict]) -> List[DockerCheck]:
    checks: List[DockerCheck] = []
    for item in raw:
        checks.append(
            DockerCheck(
                container_name=item["container"],
                display_name=item.get("name"),
            )
        )
    return checks


def _coerce_disk_usage(raw: Iterable[dict]) -> List[DiskUsageCheck]:
    checks: List[DiskUsageCheck] = []
    for item in raw:
        checks.append(
            DiskUsageCheck(
                name=item["name"],
                path=Path(item.get("path", "/")),
                warn_percent=int(item.get("warn_percent", 85)),
                critical_percent=int(item.get("critical_percent", 95)),
                min_free_gb=int(item.get("min_free_gb", 2)),
            )
        )
    return checks


def load_config(path: Optional[Path] = None) -> Config:
    """Load configuration from YAML or defaults when not provided."""

    data = None
    paths = [path] if path else DEFAULT_CONFIG_PATHS
    for candidate in paths:
        if candidate and candidate.exists():
            with candidate.open("r", encoding="utf-8") as fp:
                data = yaml.safe_load(fp) or {}
            break

    if data is None:
        return Config()

    notif = data.get("notification", {})

    # Backwards compatibility: allow flat notification schema
    if "mail" in notif or "telegram" in notif:
        mail_section = notif.get("mail", {})
        telegram_section = notif.get("telegram", {})
    else:
        mail_section = {
            "enabled": bool(data.get("enable_email", False)),
            "recipients": notif.get("mail_to", ["root@localhost"]),
            "sender": notif.get("mail_from", "spondex-monitor@localhost"),
            "subject_prefix": notif.get("subject_prefix", "[Spondex Monitor]"),
            "cc": data.get("additional_recipients", []),
        }
        telegram_section = {}

    notification = NotificationConfig(
        mail=MailNotification(
            enabled=bool(mail_section.get("enabled", False)),
            recipients=list(mail_section.get("recipients", ["root@localhost"])),
            sender=mail_section.get("sender", "spondex-monitor@localhost"),
            subject_prefix=mail_section.get("subject_prefix", "[Spondex Monitor]"),
            cc=list(mail_section.get("cc", [])),
        ),
        telegram=TelegramNotification(
            enabled=bool(telegram_section.get("enabled", True)),
            chat_ids=[str(item) for item in telegram_section.get("chat_ids", [])],
            bot_token_env=telegram_section.get("bot_token_env", "TG_BOT_TOKEN"),
            token=telegram_section.get("token"),
            api_base=telegram_section.get("api_base", "https://api.telegram.org"),
            request_timeout=float(telegram_section.get("request_timeout", 10.0)),
            subscriber_store=Path(telegram_section["subscriber_store"]) if telegram_section.get("subscriber_store") else None,
            poll_updates=bool(telegram_section.get("poll_updates", False)),
        ),
    )

    cfg = Config(
        state_path=Path(data.get("state_path", "/var/lib/spondex-monitor/state.db")),
        retention_days=int(data.get("retention_days", 365)),
        cpu_cores=int(data.get("cpu_cores")) if data.get("cpu_cores") else os.cpu_count() or 1,
        load_window_minutes=int(data.get("load_window_minutes", 60)),
        memory_critical_threshold=float(data.get("memory_threshold", 0.95)),
        docker_service_name=data.get("docker_service", "docker"),
        service_name=data.get("service_name", "Spondex"),
        app_checks=_coerce_docker_checks(data.get("app_checks", [])) or [DockerCheck("spondex-app-1", "app")],
        db_check=DatabaseCheck(**data.get("db_check", {"container_name": "spondex-postgres-1"})),
        log_checks=_coerce_log_checks(data.get("log_checks", [])),
        disk_devices=_coerce_disk_devices(data.get("disk_devices", [])),
        disk_usage_checks=
            _coerce_disk_usage(data.get("disk_usage_paths", []))
            or [DiskUsageCheck(name="root", path=Path("/"))],
        notification=notification,
        compose_file=Path(data["compose_file"]) if data.get("compose_file") else Path("/opt/spondex/docker-compose.prod.yml"),
    )

    if cfg.notification.telegram.poll_updates and cfg.notification.telegram.subscriber_store is None:
        cfg.notification.telegram.subscriber_store = cfg.state_path.with_name("telegram_subscribers.json")

    return cfg


__all__ = ["Config", "load_config", "DiskDevice", "DockerCheck", "DatabaseCheck", "DiskUsageCheck", "LogCheck", "NotificationConfig"]
