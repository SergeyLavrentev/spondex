from __future__ import annotations

import math
import os
import re
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import List

from .config import Config
from .storage import Metric, StateStore
STATUS_OK = "OK"
STATUS_FAIL = "FAIL"


def _status(ok: bool) -> str:
    return STATUS_OK if ok else STATUS_FAIL


def _load_to_percent(value: float, cores: int) -> int:
    cores = max(cores, 1)
    percent = (value / cores) * 100.0
    return max(0, int(round(percent)))


@dataclass
class Alert:
    name: str
    message: str
    severity: str = "critical"


@dataclass
class CheckContext:
    config: Config
    store: StateStore
    now: datetime


class MonitoringError(Exception):
    pass


def _run_command(command: List[str], timeout: int = 15) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)


def check_load(ctx: CheckContext) -> tuple[List[Metric], List[Alert]]:
    load1, load5, load15 = os.getloadavg()
    load1_pct = _load_to_percent(load1, ctx.config.cpu_cores)
    load5_pct = _load_to_percent(load5, ctx.config.cpu_cores)
    load15_pct = _load_to_percent(load15, ctx.config.cpu_cores)
    metrics = [
        Metric.from_value("loadavg_1_percent", load1_pct, ctx.now),
        Metric.from_value("loadavg_5_percent", load5_pct, ctx.now),
        Metric.from_value("loadavg_15_percent", load15_pct, ctx.now),
    ]

    alerts: List[Alert] = []
    window_start = ctx.now - timedelta(minutes=ctx.config.load_window_minutes)
    samples = ctx.store.fetch_metric_window("loadavg_1_percent", window_start)
    history = [int(sample.value) for sample in samples]
    values = history + [load1_pct]
    if values:
        avg_hour = sum(values) / len(values)
        if avg_hour > 100:
            alerts.append(
                Alert(
                    name="load_average_high",
                    message=(
                        f"Average CPU load over last {ctx.config.load_window_minutes} minutes is {int(round(avg_hour))}%"
                        " (> 100%)."
                    ),
                )
            )
    return metrics, alerts


def check_memory(ctx: CheckContext) -> tuple[List[Metric], List[Alert]]:
    meminfo = {}
    with Path("/proc/meminfo").open("r", encoding="utf-8") as fp:
        for line in fp:
            key, value = line.split(":")
            meminfo[key.strip()] = int(value.strip().split()[0])
    total = meminfo.get("MemTotal", 1) * 1024
    available = meminfo.get("MemAvailable", 0) * 1024
    used_ratio = 1 - (available / total if total else 1)
    used_percent = int(round(used_ratio * 100))

    metrics = [Metric.from_value("memory_used_percent", used_percent, ctx.now)]
    alerts: List[Alert] = []
    if used_ratio >= ctx.config.memory_critical_threshold:
        alerts.append(
            Alert(
                name="memory_exhausted",
                message=(
                    f"Memory usage at {used_percent}% "
                    f"(threshold {int(ctx.config.memory_critical_threshold * 100)}%)"
                ),
            )
        )
    return metrics, alerts


def check_oom(ctx: CheckContext) -> tuple[List[Metric], List[Alert]]:
    last_seen = ctx.store.get_state("oom_last_timestamp")
    since = None
    if last_seen:
        try:
            since = datetime.fromisoformat(last_seen)
        except ValueError:
            since = None
    journal_args = ["journalctl", "-k", "-n", "200", "--no-pager"]
    if since:
        journal_args.extend(["--since", since.isoformat()])

    proc = _run_command(journal_args)
    alerts: List[Alert] = []
    pattern = re.compile(r"Out of memory|Kill process")
    found = [line for line in proc.stdout.splitlines() if pattern.search(line)]
    if found:
        alerts.append(Alert(name="oom_detected", message="\n".join(found[-5:])))
    ctx.store.set_state("oom_last_timestamp", ctx.now.isoformat())
    return [], alerts


def check_docker_daemon(ctx: CheckContext) -> tuple[List[Metric], List[Alert]]:
    proc = _run_command(["systemctl", "is-active", ctx.config.docker_service_name])
    alerts: List[Alert] = []
    if proc.returncode != 0 or proc.stdout.strip() != "active":
        alerts.append(Alert(name="docker_not_running", message=proc.stderr or proc.stdout or "docker inactive"))
    return [], alerts


def _check_container_running(name: str) -> bool:
    proc = _run_command(["docker", "inspect", "-f", "{{.State.Running}}", name])
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def check_app_containers(ctx: CheckContext) -> tuple[List[Metric], List[Alert]]:
    alerts: List[Alert] = []
    metrics: List[Metric] = []
    for check in ctx.config.app_checks:
        running = _check_container_running(check.container_name)
        metric_name = f"container_status_{check.container_name}"
        metric = Metric(metric_name, _status(running), ctx.now)
        metrics.append(metric)
        if not running:
            label = check.display_name or check.container_name
            alerts.append(Alert(name=f"container_{label}_down", message=f"Container {label} is not running"))
    return metrics, alerts


def check_database_container(ctx: CheckContext) -> tuple[List[Metric], List[Alert]]:
    running = _check_container_running(ctx.config.db_check.container_name)
    metrics = [Metric("db_container_status", _status(running), ctx.now)]
    alerts: List[Alert] = []
    if not running:
        alerts.append(Alert("db_container_down", f"Database container {ctx.config.db_check.container_name} is not running"))
    return metrics, alerts


def check_database_port(ctx: CheckContext) -> tuple[List[Metric], List[Alert]]:
    alerts: List[Alert] = []
    try:
        with socket.create_connection((ctx.config.db_check.host, ctx.config.db_check.port), timeout=3):
            success = True
    except OSError as exc:
        success = False
        alerts.append(Alert("db_port_unavailable", f"Cannot connect to DB port: {exc}"))
    metrics = [Metric("db_port_status", _status(success), ctx.now)]
    return metrics, alerts


def check_database_query(ctx: CheckContext) -> tuple[List[Metric], List[Alert]]:
    alerts: List[Alert] = []
    password = None
    if ctx.config.db_check.password_env_var:
        password = os.environ.get(ctx.config.db_check.password_env_var)
    command = [
        "docker",
        "exec",
        ctx.config.db_check.container_name,
        "psql",
        "-U",
        ctx.config.db_check.user,
        "-d",
        ctx.config.db_check.database,
        "-tAc",
        "SELECT 1",
    ]
    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password
    start = time.monotonic()
    proc = subprocess.run(command, capture_output=True, text=True, timeout=15, env=env, check=False)
    elapsed = time.monotonic() - start
    latency_ms = int(round(elapsed * 1000))
    metrics = [
        Metric.from_value("db_query_latency_ms", latency_ms, ctx.now),
        Metric("db_query_status", _status(proc.returncode == 0 and proc.stdout.strip() == "1"), ctx.now),
    ]
    if proc.returncode != 0 or proc.stdout.strip() != "1":
        alerts.append(Alert("db_query_failed", f"SELECT 1 failed: rc={proc.returncode}, stdout={proc.stdout.strip()}, stderr={proc.stderr.strip()}"))
    return metrics, alerts


def check_logs(ctx: CheckContext) -> tuple[List[Metric], List[Alert]]:
    alerts: List[Alert] = []
    for log_cfg in ctx.config.log_checks:
        key = f"log_offset:{log_cfg.path}"
        state = ctx.store.get_json_state(key, {"position": 0, "inode": None})
        try:
            stat = log_cfg.path.stat()
        except FileNotFoundError:
            continue
        inode = stat.st_ino
        position = state.get("position", 0)
        if state.get("inode") != inode or position > stat.st_size:
            position = 0
        with log_cfg.path.open("r", encoding="utf-8", errors="ignore") as fp:
            fp.seek(position)
            new_lines = fp.read()
            position = fp.tell()
        ctx.store.set_json_state(key, {"position": position, "inode": inode})
        matches = [line for line in new_lines.splitlines() if log_cfg.pattern in line]
        if matches:
            sample = "\n".join(matches[-5:])
            alerts.append(Alert("log_error", f"Pattern '{log_cfg.pattern}' found in {log_cfg.path}:\n{sample}"))
    return [], alerts


def check_reboot(ctx: CheckContext) -> tuple[List[Metric], List[Alert]]:
    with Path("/proc/uptime").open("r", encoding="utf-8") as fp:
        uptime_seconds = float(fp.readline().split()[0])
    boot_time = ctx.now - timedelta(seconds=uptime_seconds)
    if boot_time.tzinfo is None:
        boot_time = boot_time.replace(tzinfo=UTC)
    last_boot_raw = ctx.store.get_state("last_boot_timestamp")
    alerts: List[Alert] = []
    if last_boot_raw:
        try:
            last_boot = datetime.fromisoformat(last_boot_raw)
            if last_boot.tzinfo is None:
                last_boot = last_boot.replace(tzinfo=UTC)
            if boot_time > last_boot + timedelta(seconds=5):
                alerts.append(Alert("server_reboot", f"Server reboot detected at {boot_time.isoformat()}"))
        except ValueError:
            pass
    ctx.store.set_state("last_boot_timestamp", boot_time.astimezone(UTC).isoformat())
    return [Metric.from_value("uptime_seconds", int(round(uptime_seconds)), ctx.now)], alerts


def _read_diskstats() -> dict[str, dict[str, int]]:
    stats: dict[str, dict[str, int]] = {}
    with Path("/proc/diskstats").open("r", encoding="utf-8") as fp:
        for line in fp:
            parts = line.split()
            if len(parts) < 14:
                continue
            name = parts[2]
            stats[name] = {
                "read_ios": int(parts[3]),
                "write_ios": int(parts[7]),
            }
    return stats


def check_disk_iops(ctx: CheckContext) -> tuple[List[Metric], List[Alert]]:
    if not ctx.config.disk_devices:
        return [], []

    stats = _read_diskstats()
    state = ctx.store.get_json_state("diskstats", {})
    alerts: List[Alert] = []
    metrics: List[Metric] = []

    prev_timestamp = state.get("timestamp")
    prev_values = state.get("stats", {})
    now_ts = time.time()
    ctx.store.set_json_state("diskstats", {"timestamp": now_ts, "stats": stats})

    if prev_timestamp is None:
        return metrics, alerts

    elapsed = now_ts - prev_timestamp
    if elapsed <= 0:
        return metrics, alerts

    for device in ctx.config.disk_devices:
        if device.name not in stats or device.name not in prev_values:
            continue
        prev = prev_values[device.name]
        curr = stats[device.name]
        read_delta = max(curr["read_ios"] - prev["read_ios"], 0)
        write_delta = max(curr["write_ios"] - prev["write_ios"], 0)
        total_ios = 0
        if device.include_reads:
            total_ios += read_delta
        if device.include_writes:
            total_ios += write_delta
        # Normalise to operations per minute so thresholds are easier to reason about
        iops = (total_ios / elapsed) * 60
        iops_int = int(math.ceil(iops))
        metrics.append(Metric.from_value(f"disk_iops_{device.name}", iops_int, ctx.now))
        if iops_int > device.max_iops:
            alerts.append(Alert("disk_iops_high", f"Device {device.name} IOPS {iops_int} > threshold {device.max_iops}"))
    return metrics, alerts


def check_disk_usage(ctx: CheckContext) -> tuple[List[Metric], List[Alert]]:
    alerts: List[Alert] = []
    metrics: List[Metric] = []
    for usage_check in ctx.config.disk_usage_checks:
        path = usage_check.path
        try:
            usage = shutil.disk_usage(path)
        except FileNotFoundError:
            metrics.append(Metric(f"disk_usage_status_{usage_check.name}", STATUS_FAIL, ctx.now))
            alerts.append(Alert("disk_path_missing", f"Disk path {path} not found"))
            continue

        total = usage.total
        used = usage.used
        free = usage.free

        used_percent = int(round((used / total) * 100)) if total else 0
        free_gb_float = free / (1024 ** 3)
        free_gb = int(math.floor(free_gb_float))

        metrics.extend(
            [
                Metric.from_value(f"disk_used_percent_{usage_check.name}", used_percent, ctx.now),
                Metric.from_value(f"disk_free_gb_{usage_check.name}", free_gb, ctx.now),
            ]
        )

        status_ok = used_percent < usage_check.critical_percent and free_gb >= usage_check.min_free_gb
        metrics.append(Metric(f"disk_usage_status_{usage_check.name}", _status(status_ok), ctx.now))

        if not status_ok:
            alerts.append(
                Alert(
                    "disk_space_exhausted",
                    (
                        f"Disk {usage_check.name} at {path} usage {used_percent}% "
                        f"with {free_gb_float:.1f} GiB free (< {usage_check.min_free_gb} GiB)."
                    ),
                )
            )
        elif used_percent >= usage_check.warn_percent:
            alerts.append(
                Alert(
                    "disk_space_low",
                    (
                        f"Disk {usage_check.name} at {path} usage {used_percent}% "
                        f"with {free_gb_float:.1f} GiB free (warn threshold {usage_check.warn_percent}%)."
                    ),
                    severity="warning",
                )
            )
    return metrics, alerts


ALL_CHECKS = [
    check_load,
    check_memory,
    check_oom,
    check_docker_daemon,
    check_app_containers,
    check_database_container,
    check_database_port,
    check_database_query,
    check_reboot,
    check_disk_iops,
    check_disk_usage,
    check_logs,
]


def run_checks(ctx: CheckContext) -> tuple[List[Metric], List[Alert]]:
    all_metrics: List[Metric] = []
    all_alerts: List[Alert] = []
    for check in ALL_CHECKS:
        metrics, alerts = check(ctx)
        if metrics:
            all_metrics.extend(metrics)
        if alerts:
            all_alerts.extend(alerts)
    return all_metrics, all_alerts


__all__ = ["Alert", "CheckContext", "run_checks"]
