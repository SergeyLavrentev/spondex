# Monitoring and Alerting

This document describes the monitoring script that replaces the original Monit-based
prototype. The monitoring job is implemented in Python and scheduled by
`systemd` on the production host.

## Overview

The entry point lives at `monitoring/monitor.py`. It collects runtime metrics,
records them in a local SQLite database for 365 days, and ships alerts through
a Telegram bot by default. When invoked manually
with no flags the script reads `monitoring/config.yaml`, prints the full report
to stdout, and skips network delivery. Pass `--telegram` to
enable notification channels (the systemd service opts into Telegram
automatically). Every run
performs a lightweight `getUpdates` poll (when enabled) so that new users who
press `/start` instantly receive a welcome brief about tracked checks and are
added to the subscriber store.

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
- **Application /status endpoint**: queries the application's health check API
  at `http://127.0.0.1:8888/status`, validates JSON response structure, and
  alerts on HTTP errors, unhealthy status, or malformed responses.
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
- `notification.telegram.chat_ids`, `notification.telegram.token_env` or
  `notification.telegram.token`: Telegram бот отправляет уведомления всем
  chat_id из массива и подписчикам, зарегистрированным через `/start`.
  Токен обычно хранится в переменной окружения `TG_BOT_TOKEN`.
- `notification.telegram.subscriber_store`: путь к JSON-файлу со списком
  подписчиков и `last_update_id`. По умолчанию лежит рядом со state.db.
- `notification.telegram.poll_updates`: включает авто-регистрацию — бот раз в
  запуск читает `getUpdates` и добавляет всех, кто написал `/start` в личку.
- `monitor_timer_interval`: systemd timer cadence (default 1 minute).
- `monitor_overwrite_config`: when `true`, Ansible will re-render
  `/opt/spondex/monitoring/config.yaml`; keep it `false` to preserve manual
  edits on the host.
- Thresholds live in `monitor_load_window_minutes`, `monitor_memory_threshold`,
  and `monitor_disks[*].max_iops`. Update them either in inventory variables
  (recommended for production) or by editing a local copy of
  `monitoring/config.sample.yaml` when experimenting on a workstation.

## Deployment automation

The `monitoring` role (see `ansible/roles/monitoring`) performs the following:

1. Installs required packages (`sysstat`, `curl`, `python3-venv`).
2. Creates the state directory (`/var/lib/spondex-monitor`).
3. Marks the monitoring script executable and drops the templated config.
4. Installs `systemd` service + timer units and enables the timer. The unit now
  executes a post-step that calls `monitoring/monitor.py --poll-telegram-updates`
  to refresh Telegram subscribers (it exits immediately when polling is
  disabled in the config).

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
  --extra-vars "monitor_telegram_chat_ids=['123456789']" \
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

- Print the metrics and alerts without triggering notifications (useful for
  smoke tests):

  ```bash
  sudo /opt/spondex/monitoring/monitor.py --config /opt/spondex/monitoring/config.yaml
  ```

- Send a one-off test message to configured channels:

  ```bash
  sudo /opt/spondex/monitoring/monitor.py --config /opt/spondex/monitoring/config.yaml --test-notify --telegram
  ```

- Force a Telegram poll without collecting metrics (updates welcome messages
  and the subscriber store only):

  ```bash
  sudo /opt/spondex/monitoring/monitor.py --config /opt/spondex/monitoring/config.yaml --poll-telegram-updates
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
  `log_checks`, `app_checks`, `notification.telegram.chat_ids`.

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

## Notification channels

### Telegram (по умолчанию)

- Укажите ID чатов в `monitor_telegram_chat_ids` (или задайте их напрямую в
  `notification.telegram.chat_ids` при ручном редактировании конфига).
- Токен бота передаётся через переменную окружения `TG_BOT_TOKEN`
  (`notification.telegram.token_env`). Для локальных тестов можно временно
  записать значение в `notification.telegram.token`, но хранить токен в файле
  на сервере не рекомендуется.
- Systemd unit пробрасывает токен из окружения (секрет `DEPLOY_TG_BOT_TOKEN`
  в CI). Скрипт валидирует наличие токена и чат-идов перед отправкой.
- Если `notification.telegram.poll_updates=true`, бот автоматически добавляет
  в конфиг всех пользователей, которые в личке нажали `/start`. Список хранится
  в `notification.telegram.subscriber_store` (JSON). При регистрации подписчик
  получает приветственное сообщение с описанием мониторинга и подсказкой про
  `--test-notify`.
- Флаг `--poll-telegram-updates` запускает только синхронизацию подписчиков и
  используется `systemd`-юнитом после основного запуска. Инструмент можно
  вызывать вручную для хаотичного синка или при отладке Telegram.

## Local testing

Запустите скрипт локально с нужными каналами:

```bash
python -m monitoring.monitor --config monitoring/config.sample.yaml --telegram
```

Флаг `--test-notify` выполнит
проверку конфигурации и отослёт короткое сообщение в выбранные каналы.

На продакшене скрипт исполняемый, поэтому его можно запускать напрямую как
`sudo /opt/spondex/monitoring/monitor.py` для ручного сбора метрик.
Юнит-тесты живут в `tests/test_monitoring_checks.py` и `tests/test_notifier.py`
и запускаются через `pytest`.

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
