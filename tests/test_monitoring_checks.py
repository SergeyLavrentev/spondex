from __future__ import annotations

from datetime import datetime, timedelta
import monitoring.checks as checks
from monitoring.checks import CheckContext, check_disk_iops, check_load, check_logs
from monitoring.config import Config, DiskDevice, LogCheck
from monitoring.storage import Metric, StateStore


def test_check_load_alert(tmp_path, monkeypatch):
    now = datetime.utcnow()
    store = StateStore(tmp_path / "state.db")
    store.save_metrics([Metric("loadavg_1", 3.0, now - timedelta(minutes=30))])

    config = Config(cpu_cores=1, load_window_minutes=60)

    monkeypatch.setattr(checks.os, "getloadavg", lambda: (4.0, 3.0, 2.0))

    metrics, alerts = check_load(CheckContext(config, store, now))
    assert any(alert.name == "load_average_high" for alert in alerts)
    assert any(metric.name == "loadavg_1" for metric in metrics)


def test_check_logs_detects_new_errors(tmp_path):
    log_file = tmp_path / "app.log"
    log_file.write_text("INFO ok\n", encoding="utf-8")

    config = Config(log_checks=[LogCheck(path=log_file, pattern="Traceback")])
    store = StateStore(tmp_path / "state.db")
    now = datetime.utcnow()

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
    now = datetime.utcnow()

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