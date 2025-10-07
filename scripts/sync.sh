#!/bin/bash

cd "$(dirname "$0")/.."

echo "Запуск полной синхронизации в запущенном контейнере..."
docker compose exec app python -m src.main \
    --skip-web-server \
    --sync-playlists \
    --sync-favorite-albums \
    --sync-favorite-artists \
    --force-full-sync \
    "$@"