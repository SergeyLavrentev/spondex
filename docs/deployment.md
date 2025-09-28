# CI/CD и деплой Spondex

Этот документ описывает, как настраивается автоматический деплой приложения на удалённый сервер Debian 13 с помощью GitHub Actions и Ansible. Пайплайн разворачивает Docker окружение, синхронизирует исходники и запускает `docker compose` на сервере при каждом `git push`. Ansible устанавливается **только** на GitHub runner; на сервере среды не нужно — он выполняет роли "управляемого хоста".

## Что делает плейбук

Ansible-плейбук `ansible/deploy.yml` выполняет следующие шаги:

1. Убеждается, что на целевой машине установлен Python 3 (требуется для Ansible).
2. Устанавливает системные пакеты, добавляет репозиторий Docker и ставит `docker-ce` + `docker compose` plugin.
3. При необходимости открывает входящие соединения в UFW для порта приложения (по умолчанию 8888) и дополнительных портов.
4. Синхронизирует файлы проекта в директорию `/opt/spondex` (можно изменить переменную `app_root`).
5. Создаёт/обновляет файл `.env` на сервере из базовых настроек и секрета GitHub (`APP_TOKENS`).
6. Подготавливает каталог `.cache` и, если передан секрет `SPOTIFY_CACHE_CONTENT`, записывает файл `.cache` для Spotipy.
7. При наличии `GHCR_PAT` логинится в GitHub Container Registry, затем выполняет `docker compose pull`, `docker compose up -d --remove-orphans` и выводит `docker compose ps`.

## Требования к серверу

- Debian 13 (или совместимый дистрибутив с `apt`).
- Пользователь с правами `sudo` без запроса пароля (используется для установки пакетов и управления Docker).
- SSH доступ по порту `49384`.
- Включённый UFW (если есть) должен разрешать SSH на этом порту.

## Шаги настройки

### 1. Генерация deploy-ключа

#### Вариант через `ssh-keygen`

На локальной машине выполните:

```bash
ssh-keygen -t ed25519 -C "spondex-deploy" -f ~/.ssh/spondex_deploy
```

- Файл `~/.ssh/spondex_deploy` — приватный ключ (добавим в секреты GitHub).
- Файл `~/.ssh/spondex_deploy.pub` — публичный ключ (добавим на сервер).

#### Вариант через GitHub UI

1. Откройте `Settings → SSH and GPG keys → New SSH key`.
2. Вставьте публичный ключ (`*.pub`) в поле и задайте описание (например, `spondex-deploy`).
3. Нажмите **Add SSH key** — теперь ключ будет доступен для использования GitHub Actions.

### 2. Добавление ключа на сервер

Скопируйте содержимое `spondex_deploy.pub` в файл `~/.ssh/authorized_keys` пользователя `github` (или другого выбранного сервисного пользователя), от имени которого будет запускаться деплой. Убедитесь, что SSH-сервер слушает порт `49384` и что UFW разрешает входящие соединения на этот порт.

### 3. Подготовка файлов окружения

- Скопируйте шаблон `cp .env.example .env` и при необходимости измените параметры PostgreSQL, `APP_PORT`, `EXTRA_UFW_PORTS` и другие не секретные настройки.
- Создайте файл `tokens.env` (можно начать с `cp tokens.env.example tokens.env`) и заполните чувствительные данные в формате `KEY="value"` — сюда входят `SPOTIPY_CLIENT_ID`, `SPOTIPY_CLIENT_SECRET`, `YANDEX_TOKEN` и другие секреты.
- В настройках секретов репозитория сохраните **полное содержимое** `tokens.env` в секрете `APP_TOKENS`. GitHub корректно хранит многострочные значения.

Файлы `.env` и `tokens.env` внесены в `.gitignore`, поэтому они не попадут в репозиторий. Секрет `APP_TOKENS` разворачивается плейбуком на сервере непосредственно перед запуском контейнеров.

### 4. Создание секретов GitHub

В настройках репозитория (`Settings → Secrets and variables → Actions`) добавьте следующие секреты:

| Секрет | Назначение |
| --- | --- |
| `SSH_HOST` | IP или доменное имя сервера. |
| `SSH_USER` | SSH-пользователь (например, `github`) с правами sudo без пароля. |
| `SSH_PRIVATE_KEY` | Приватный ключ из `~/.ssh/spondex_deploy` (вставить текст целиком). |
| `APP_TOKENS` | Многострочное содержимое `tokens.env` с чувствительными токенами. |
| `SPOTIFY_CACHE_CONTENT` | Полное содержимое файла `.cache` из Spotipy (монтируется в контейнер как refresh-token). |
| `GHCR_PAT` | Personal Access Token с правами `read:packages` для скачивания образа из GHCR. |

> Настройки `APP_PORT` и `EXTRA_UFW_PORTS` задаются в `.env` (есть дефолты). При необходимости их можно переопределить через inventory/extra-vars при запуске плейбука.

> ⚠️ Убедитесь, что `SSH_PRIVATE_KEY` имеет права только на деплой (при желании ограничьте команды с помощью `authorized_keys`).

### 5. Проверка доступа по SSH из GitHub

Локально убедитесь, что можете подключиться ключом:

```bash
ssh -p 49384 -i ~/.ssh/spondex_deploy <user>@<host>
```

Если всё ок, добавьте хост в `known_hosts` внутри GitHub-секрета (или позвольте workflow сделать это автоматически).

## Запуск пайплайна

Workflow `Build and Publish Docker Image` (`.github/workflows/docker-image.yml`) собирает образ и выкладывает его в GitHub Container Registry (`ghcr.io/<owner>/spondex`). Он запускается при каждом push в `main` и помечает образ тегами `latest`, именем ветки и SHA.

Workflow `Deploy to Production` (`.github/workflows/deploy.yml`) выполняется **при любом push** в репозиторий. Он:

1. Проверяет репозиторий и устанавливает Ansible.
2. Настраивает SSH (используя секреты `SSH_PRIVATE_KEY`, `SSH_HOST`, `SSH_USER`), формирует inventory с портом `49384`.
3. Формирует файл с дополнительными переменными и запускает `ansible/deploy.yml`, который тянет образ из GHCR и разворачивает `docker-compose.prod.yml`.

### Ручной запуск

Для локального деплоя без GitHub Actions можно выполнить:

```bash
uv tool install ansible
ansible-galaxy collection install -r ansible/requirements.yml
printf '[prod]\n%s ansible_port=49384\n' <host> > /tmp/inventory.ini
python -c "import json, pathlib; pathlib.Path('/tmp/extra_vars.json').write_text(json.dumps({'app_tokens_content': open('tokens.env').read()}))"
ANSIBLE_HOST_KEY_CHECKING=false \
ansible-playbook ansible/deploy.yml \
  -i /tmp/inventory.ini \
  --limit prod \
  -u <user> \
  --private-key ~/.ssh/spondex_deploy \
  --extra-vars '@/tmp/extra_vars.json'
```

Перед запуском убедитесь, что файл `tokens.env` находится в корне проекта и заполнен актуальными токенами — он будет прочитан Python-обработкой в шаге выше.

По умолчанию плейбук синхронизирует весь проект в `/opt/spondex`. При необходимости можно переопределить переменную `app_root` через `--extra-vars`.

## Дополнительные заметки

- Файл `.cache` с токеном Spotify не синхронизируется Ansible через `rsync` и не попадает в Docker-образ. Вместо этого пайплайн берет содержимое из секрета `SPOTIFY_CACHE_CONTENT` (если он задан) и разворачивает его на сервере перед запуском `docker compose`. Можно также скопировать файл вручную в `/opt/spondex/.cache/`.
- После первоначального деплоя файл `.env` на сервере будет перезаписываться значением из секрета при каждом запуске пайплайна.
- Продакшен запускается через `docker-compose.prod.yml`, который тянет образ `ghcr.io/<owner>/spondex:latest`. При необходимости можно переопределить владельца (`GHCR_IMAGE_OWNER`) и тег (`SPONDEX_TAG`) через переменные окружения.
- Для авторизации в GHCR по умолчанию используется владелец репозитория (`github.repository_owner`). Если образ размещён в другом аккаунте/организации, задайте переменную Actions `GHCR_IMAGE_OWNER` — она попадёт в плейбук как логин и имя образа.
- При смене SSH-ключа не забудьте обновить секрет `SSH_PRIVATE_KEY` и authorized_keys на сервере.
- Если UFW выключен или отсутствует, задачи по открытию портов будут пропущены.
- Все Docker-команды выполняются от имени `root` через `become: true`. Рекомендуется использовать отдельного системного пользователя с правами sudo: создайте его на сервере, добавьте в sudoers без пароля и настройте ключи.

## GHCR_PAT: зачем нужен и как получить

Пакетный регистр GHCR по умолчанию приватный. Чтобы `docker compose pull` на сервере смог скачать образ `ghcr.io/<owner>/spondex`, GitHub Actions пробрасывает в Ansible персональный токен `GHCR_PAT` с правом `read:packages`.

1. Создайте токен в [настройках GitHub → Developer settings → Personal access tokens → Fine-grained tokens](https://github.com/settings/personal-access-tokens/new). Привяжите его к репозиторию Spondex и отметьте право **Packages → Read**.
2. Сохраните токен в секрете Actions `GHCR_PAT`.
3. При деплое плейбук выполнит `docker login ghcr.io` при помощи этого токена и только затем дернёт `docker compose pull`. Если секрет не задан, плейбук пытается тянуть образ без авторизации — это сработает только для публичных пакетов.

> Токен используется **только** на сервере, данные не попадают в Docker-образ и не сохраняются в репозитории.
