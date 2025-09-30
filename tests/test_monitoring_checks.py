from __future__ import annotations

from collections import namedtuple
from datetime import UTC, datetime, timedelta
from pathlib import Path
import monitoring.checks as checks
from monitoring.checks import (
    CheckContext,
    check_disk_iops,
    check_disk_usage,
    check_load,
    check_logs,
)
from monitoring.config import Config, DiskDevice, DiskUsageCheck, LogCheck
from monitoring.storage import Metric, StateStore


def test_check_load_alert(tmp_path, monkeypatch):
    now = datetime.now(UTC)
    store = StateStore(tmp_path / "state.db")
    store.save_metrics([Metric.from_value("loadavg_1_percent", 300, now - timedelta(minutes=30))])

    config = Config(cpu_cores=1, load_window_minutes=60)

    monkeypatch.setattr(checks.os, "getloadavg", lambda: (4.0, 3.0, 2.0))

    metrics, alerts = check_load(CheckContext(config, store, now))
    assert any(alert.name == "load_average_high" for alert in alerts)
    assert any(metric.name == "loadavg_1_percent" for metric in metrics)


def test_check_logs_detects_new_errors(tmp_path):
    log_file = tmp_path / "app.log"
    log_file.write_text("INFO ok\n", encoding="utf-8")

    config = Config(log_checks=[LogCheck(path=log_file, pattern="Traceback")])
    store = StateStore(tmp_path / "state.db")
    now = datetime.now(UTC)

    # First run no errors
    _, alerts = check_logs(CheckContext(config, store, now))
    assert alerts == []

    # Append traceback
    log_file.write_text("INFO ok\nTraceback: boom\n", encoding="utf-8")
    _, alerts = check_logs(CheckContext(config, store, now + timedelta(minutes=5)))
    assert alerts and alerts[0].name == "log_error"


def test_disk_iops_threshold(tmp_path, monkeypatch):
    config = Config(disk_devices=[DiskDevice(name="sda", max_iops=50)])
    store = StateStore(tmp_path / "state.db")
    now = datetime.now(UTC)

    first_stats = {"sda": {"read_ios": 100, "write_ios": 100}}
    second_stats = {"sda": {"read_ios": 400, "write_ios": 400}}

    monkeypatch.setattr(checks, "_read_diskstats", lambda: first_stats)
    check_disk_iops(CheckContext(config, store, now))

    monkeypatch.setattr(checks.time, "time", lambda: 100.0)
    store.set_json_state("diskstats", {"timestamp": 0.0, "stats": first_stats})
    monkeypatch.setattr(checks, "_read_diskstats", lambda: second_stats)
    metrics, alerts = check_disk_iops(CheckContext(config, store, now + timedelta(seconds=100)))
    assert metrics
    assert alerts


def test_disk_usage_warn(tmp_path, monkeypatch):
    config = Config(
        disk_usage_checks=[
            DiskUsageCheck(name="root", path=Path("/"), warn_percent=80, critical_percent=95, min_free_gb=5)
        ]
    )
    store = StateStore(tmp_path / "state.db")
    now = datetime.now(UTC)

    Usage = namedtuple("Usage", "total used free")
    mock_usage = Usage(total=100 * 1024**3, used=90 * 1024**3, free=10 * 1024**3)
    monkeypatch.setattr(checks.shutil, "disk_usage", lambda path: mock_usage)

    metrics, alerts = check_disk_usage(CheckContext(config, store, now))
    metric_names = {metric.name: metric.value for metric in metrics}
    assert metric_names["disk_used_percent_root"] == "90"
    assert metric_names["disk_free_gb_root"] == str(int(10))
    assert any(alert.name == "disk_space_low" and alert.severity == "warning" for alert in alerts)


def test_disk_usage_missing_path(tmp_path, monkeypatch):
    config = Config(disk_usage_checks=[DiskUsageCheck(name="bad", path=Path("/missing"))])
    store = StateStore(tmp_path / "state.db")
    now = datetime.now(UTC)

    def _raise(path):
        raise FileNotFoundError(path)

    monkeypatch.setattr(checks.shutil, "disk_usage", _raise)

    metrics, alerts = check_disk_usage(CheckContext(config, store, now))
    assert any(metric.name == "disk_usage_status_bad" and metric.value == "FAIL" for metric in metrics)
    assert any(alert.name == "disk_path_missing" for alert in alerts)