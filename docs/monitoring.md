# Monitoring and Alerting

This document describes the monitoring script that replaces the original Monit-based
prototype. The monitoring job is implemented in Python and scheduled by
`systemd` on the production host.

## Overview

The entry point lives at `monitoring/monitor.py`. It collects runtime metrics,
records them in a local SQLite database for 365 days, and emits alert e-mails
through the local MTA when thresholds are breached. When invoked manually with
no flags the script reads `monitoring/config.yaml`, prints the full report to
stdout, and skips e-mail delivery. Pass `--email` to opt back into
notifications (the systemd service does this automatically).

Key checks implemented:

- **Load average**: the 60-minute average load must remain below the CPU core
  count. Load samples are aggregated every run and the hourly average is
  computed from stored metrics.
- **Memory pressure**: raises an alert when more than 95% of RAM is consumed
  (`MemAvailable` parser from `/proc/meminfo`).
- **Out-of-memory events**: scans `journalctl -k` logs since the previous run
  and alerts on `Out of memory` / `Kill process` entries.
- **Docker daemon**: verifies that `systemd` reports the Docker service as
  `active`.
- **Application containers**: ensures configured containers (default:
  `spondex-app-1`) are running.
- **Database container & port**: checks Docker state, confirms that port 5432 is
  open on `127.0.0.1`, and executes `SELECT 1` inside the Postgres container.
- **Application logs**: tails configured log files and looks for `Traceback` (or
  custom patterns). Offsets are persisted to survive rotations.
- **Server reboots**: compares the current boot timestamp with the stored value
  to detect unplanned reboots.
- **Disk IOPS**: computes per-device IOPS (normalised to a per-minute rate)
  from `/proc/diskstats` deltas between runs and alerts when the configured
  threshold is exceeded.
- **Disk space**: tracks used percentage and free GiB for configured mount
  points, raises warnings when the warn threshold is exceeded, and escalates to
  a critical alert when the remaining space drops below the configured
  minimum.

All metrics and state variables (log offsets, disk stats snapshot, last boot
stamp, etc.) are stored under the SQLite database declared in the configuration
(`/var/lib/spondex-monitor/state.db` by default).

## Configuration

`ansible` renders `/opt/spondex/monitoring/config.yaml` from
`ansible/templates/spondex-monitor-config.yaml.j2`. Parameters are exposed via
role defaults (`ansible/roles/monitoring/defaults/main.yml`) and can be
overridden per environment. Notable options:

- `monitor_app_containers`: list of Docker containers that must stay running.
- `monitor_disks`: devices and IOPS thresholds (`sysstat` is required so that
  `/proc/diskstats` values are meaningful).
- `monitor_disk_usage`: mount points to watch, percentage thresholds and the
  minimal free space (GiB) before triggering alerts.
- `monitor_log_files`: log paths and error patterns.
- `monitor_mail_to`, `monitor_mail_from`, `monitor_mail_subject`: e-mail
  recipients and message metadata.
- `monitor_timer_interval`: systemd timer cadence (default 5 minutes).
- `monitor_overwrite_config`: when `true`, Ansible will re-render
  `/opt/spondex/monitoring/config.yaml`; keep it `false` to preserve manual
  edits on the host.
- Thresholds live in `monitor_load_window_minutes`, `monitor_memory_threshold`,
  and `monitor_disks[*].max_iops`. Update them either in inventory variables
  (recommended for production) or by editing a local copy of
  `monitoring/config.sample.yaml` when experimenting on a workstation.

## Deployment automation

The `monitoring` role (see `ansible/roles/monitoring`) performs the following:

1. Installs required packages (`sysstat`, `mailutils`).
2. Creates the state directory (`/var/lib/spondex-monitor`).
3. Marks the monitoring script executable and drops the templated config.
4. Installs `systemd` service + timer units and enables the timer.

The main playbook (`ansible/deploy.yml`) imports the role after the application
stack is deployed, ensuring the script and configuration are present on the
host.

## How to roll out

To deploy the monitoring stack (or pick up code/config changes), run the
standard playbook so that the sources are synced to `/opt/spondex` and the role
re-templated:

```bash
ansible-playbook -i inventory/prod ansible/deploy.yml
```

Для точечных обновлений мониторинга без полного деплоя можно запустить отдельный
плейбук `ansible/monitoring.yml`:

```bash
ansible-playbook -i inventory/prod ansible/monitoring.yml
```

Variables under `ansible/roles/monitoring/defaults/main.yml` can be overridden
per-environment, for example:

```bash
ansible-playbook -i inventory/prod ansible/deploy.yml \
  --extra-vars "monitor_mail_to=['alerts@example.com']" \
  --extra-vars "monitor_timer_interval=10m"
```

After the run finishes, verify that systemd picked up the latest units:

```bash
sudo systemctl status spondex-monitor.timer
sudo systemctl list-timers spondex-monitor.timer
```

If you are iterating on the configuration only, you can launch a manual run of
the job without waiting for the timer:

```bash
sudo systemctl start spondex-monitor.service
```

## Operations quick reference

- View the last execution log:

  ```bash
  journalctl -u spondex-monitor.service -n 50
  ```

- Print the metrics and alerts without e-mail side effects (useful for smoke
  tests):

  ```bash
  sudo /opt/spondex/monitoring/monitor.py --config /opt/spondex/monitoring/config.yaml
  ```

- Inspect the SQLite store to confirm the timer is writing samples:

  ```bash
  sqlite3 /var/lib/spondex-monitor/state.db \
    "SELECT name, recorded_at, value FROM metrics ORDER BY recorded_at DESC LIMIT 10;"
  ```

- Tail the config used on the host (rendered from Ansible templates):

  ```bash
  sudo cat /opt/spondex/monitoring/config.yaml
  ```

## Manual tweaks without Ansible

If Ansible is not available on the host, you can edit the runtime configuration
in place. The timer reads `config.yaml` on every invocation, so the next run
will pick up the new thresholds automatically.

1. Open the config for editing (for example with `nano`):

   ```bash
   sudo nano /opt/spondex/monitoring/config.yaml
   ```

2. Adjust the desired fields under the **Thresholds** section (`load_window_minutes`,
   `memory_threshold`, `disk_devices[*].max_iops`, etc.) or add/remove entries in
   `log_checks`, `app_checks`, `notification.mail_to`.

3. Save the file and optionally run a dry check to validate parsing:

   ```bash
  sudo /opt/spondex/monitoring/monitor.py --config /opt/spondex/monitoring/config.yaml
   ```

4. The systemd timer will execute the script with the new settings on the next
   tick. To apply immediately, trigger it manually:

   ```bash
   sudo systemctl start spondex-monitor.service
   ```

> ⚠️ Note: Ansible changes will overwrite the file only if the deployment was
> executed with `monitor_overwrite_config=true`. Record long-term adjustments in
> inventory variables to keep them persistent.

## Email delivery

The script connects to `localhost:25`. Make sure Postfix or another MTA is
configured to relay mail from the server. Recipients can be amended with the
`monitor_mail_cc` variable.

## Local testing

Run the script locally with:

```bash
python -m monitoring.monitor --config monitoring/config.sample.yaml
```

The command prints the collected metrics and any alerts without attempting to
send mail. On the production host the script is executable, so you can run it
directly as `sudo /opt/spondex/monitoring/monitor.py` to trigger an ad-hoc
collection without remembering any UV-specific incantations. Unit tests live in
`tests/test_monitoring_checks.py` and can be executed via `pytest`.

For integration coverage, Molecule сценарий роли находится в
`ansible/roles/monitoring/molecule/default`. Локально запускайте его в отдельном
виртуальном окружении, чтобы не загрязнять системный Python:

```bash
python -m venv .venv
source .venv/bin/activate
pip install molecule molecule-plugins[docker] ansible
ANSIBLE_COLLECTIONS_PATHS="$PWD/.molecule-collections:/usr/share/ansible/collections" \
  molecule test --scenario-name default
```

CI workflow `.github/workflows/molecule.yml` делает то же самое, но если тесты
падают, пайплайн остаётся зелёным — ошибки можно посмотреть в логах шага.
