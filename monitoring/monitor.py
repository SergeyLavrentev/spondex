#!/usr/bin/env python3
"""Spondex monitoring entry point."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from typing import List

from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

import logging

from monitoring.checks import Alert, CheckContext, run_checks
from monitoring.config import load_config
from monitoring.notifier import poll_telegram_subscribers, send_notifications
from monitoring.storage import Metric, StateStore


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Spondex monitoring checks")
    parser.add_argument("--config", type=str, help="Path to monitoring config YAML", default=None)
    parser.add_argument("--telegram", dest="telegram", action="store_true", help="Enable Telegram notifications for this run")
    parser.add_argument("--no-telegram", dest="telegram", action="store_false", help="Disable Telegram notifications for this run")
    parser.set_defaults(telegram=None)
    parser.add_argument("--print", dest="print_report", action="store_true", help="Print alerts and metrics to stdout (default)")
    parser.add_argument("--no-print", dest="print_report", action="store_false", help="Suppress stdout output")
    parser.set_defaults(print_report=None)
    parser.add_argument("--test-notify", action="store_true", help="Send a test notification using all enabled channels")
    parser.add_argument(
        "--poll-telegram-updates",
        action="store_true",
        help="Poll Telegram updates to refresh subscribers and exit",
    )
    return parser.parse_args()


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )


def _format_metric_value(metric: Metric) -> str:
    value = metric.value
    name = metric.name
    if name.endswith("_percent"):
        return f"{value}%"
    if name.endswith("_status"):
        return value
    if name.endswith("_ms"):
        return f"{value} ms"
    return value


def format_alerts_only(now: datetime, alerts: List[Alert]) -> str:
    lines = [f"Spondex alerts at {now.strftime('%Y-%m-%d %H:%M %Z')}", ""]
    if alerts:
        for alert in alerts:
            lines.append(f"[{alert.severity.upper()}] {alert.name}: {alert.message}")
    else:
        lines.append("No alerts.")
    return "\n".join(lines)


def format_report(now: datetime, alerts: List[Alert], metrics: List[Metric]) -> str:
    lines = [f"Spondex monitoring report at {now.strftime('%Y-%m-%d %H:%M %Z')}", ""]
    if alerts:
        lines.append("Alerts:")
        for alert in alerts:
            lines.append(f"- [{alert.severity}] {alert.name}: {alert.message}")
    else:
        lines.append("No alerts triggered.")
    lines.append("")
    lines.append("Recent metrics:")
    for metric in metrics:
        lines.append(f"- {metric.name} = {_format_metric_value(metric)}")
    return "\n".join(lines)


def main() -> int:
    # Load environment variables from .env file
    _configure_logging()
    load_dotenv()
    
    args = parse_args()
    config_path = Path(args.config) if args.config else DEFAULT_CONFIG_PATH
    if config_path.exists():
        config = load_config(path=config_path)
    else:
        config = load_config()

    if args.telegram is not None:
        config.notification.telegram.enabled = args.telegram

    if args.poll_telegram_updates:
        try:
            polled = poll_telegram_subscribers(config)
        except RuntimeError as exc:
            print(f"Telegram polling failed: {exc}", file=sys.stderr)
            return 2
        if polled:
            print("Telegram subscribers refreshed.")
        else:
            print("Telegram polling disabled in config; nothing to do.")
        return 0

    now = datetime.now().astimezone()
    store = StateStore(config.state_path)
    ctx = CheckContext(config=config, store=store, now=now)

    metrics, alerts = run_checks(ctx)
    if metrics:
        store.save_metrics(metrics)
        cutoff = now - timedelta(days=config.retention_days)
        store.prune_metrics_older_than(cutoff)

    # Load previous alerts state
    prev_alerts_state = store.get_json_state("active_alerts", {})
    prev_alert_names = set(prev_alerts_state.keys())
    current_alert_names = {alert.name for alert in alerts}
    
    # Determine new and resolved alerts
    new_alerts = [alert for alert in alerts if alert.name not in prev_alert_names]
    resolved_alert_names = prev_alert_names - current_alert_names
    resolved_alerts = [Alert(name=name, message="Alert resolved", severity="info") 
                      for name in resolved_alert_names]

    report = format_report(now, alerts, metrics)
    should_print = True if args.print_report is None else args.print_report

    if should_print:
        print(report)

    test_requested = args.test_notify
    if test_requested:
        errors = send_notifications(config, [], report, force=True)
        if errors:
            for err in errors:
                print(f"Notification error: {err}", file=sys.stderr)
            return 2
        print("Test notification sent successfully.")
        return 0
    else:
        # Send notifications for new alerts
        if new_alerts:
            alert_message = format_alerts_only(now, new_alerts)
            errors = send_notifications(config, new_alerts, alert_message)
            if errors:
                for err in errors:
                    print(f"Notification error: {err}", file=sys.stderr)
                return 2
        
        # Send notifications for resolved alerts
        if resolved_alerts:
            resolved_message = format_alerts_only(now, resolved_alerts)
            errors = send_notifications(config, resolved_alerts, resolved_message)
            if errors:
                for err in errors:
                    print(f"Notification error: {err}", file=sys.stderr)
                return 2
    
    # Save current alerts state
    current_alerts_state = {alert.name: {"message": alert.message, "severity": alert.severity} 
                           for alert in alerts}
    store.set_json_state("active_alerts", current_alerts_state)
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
