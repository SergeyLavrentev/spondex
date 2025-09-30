#!/usr/bin/env python3
"""Spondex monitoring entry point."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from typing import List

from pathlib import Path

from monitoring.checks import Alert, CheckContext, run_checks
from monitoring.config import Config, load_config
from monitoring.notifier import send_alert_email
from monitoring.storage import Metric, StateStore


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Spondex monitoring checks")
    parser.add_argument("--config", type=str, help="Path to monitoring config YAML", default=None)
    parser.add_argument("--email", dest="email", action="store_true", help="Send alert emails if thresholds are exceeded")
    parser.add_argument("--no-email", dest="email", action="store_false", help="Disable email sending for this run")
    parser.set_defaults(email=None)
    parser.add_argument("--print", dest="print_report", action="store_true", help="Print alerts and metrics to stdout (default)")
    parser.add_argument("--no-print", dest="print_report", action="store_false", help="Suppress stdout output")
    parser.set_defaults(print_report=None)
    return parser.parse_args()


def format_report(now: datetime, alerts: List[Alert], metrics: List[Metric]) -> str:
    lines = [f"Spondex monitoring report at {now.isoformat()}", ""]
    if alerts:
        lines.append("Alerts:")
        for alert in alerts:
            lines.append(f"- [{alert.severity}] {alert.name}: {alert.message}")
    else:
        lines.append("No alerts triggered.")
    lines.append("")
    lines.append("Recent metrics:")
    for metric in metrics:
        lines.append(f"- {metric.name} = {metric.value:.3f} at {metric.recorded_at.isoformat()}")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    config_path = Path(args.config) if args.config else DEFAULT_CONFIG_PATH
    if config_path.exists():
        config = load_config(path=config_path)
    else:
        config = load_config()

    if args.email is not None:
        config.enable_email = args.email
    else:
        config.enable_email = False

    now = datetime.utcnow()
    store = StateStore(config.state_path)
    ctx = CheckContext(config=config, store=store, now=now)

    metrics, alerts = run_checks(ctx)
    if metrics:
        store.save_metrics(metrics)
        cutoff = now - timedelta(days=config.retention_days)
        store.prune_metrics_older_than(cutoff)

    report = format_report(now, alerts, metrics)
    should_print = True if args.print_report is None else args.print_report

    if should_print:
        print(report)

    if alerts:
        try:
            send_alert_email(config, alerts, report)
        except Exception as exc:  # pragma: no cover
            print(f"Failed to send email: {exc}", file=sys.stderr)
            return 2
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
