#!/bin/bash

cd "$(dirname "$0")/.."

if [ "$1" = "sync" ]; then
    # Запуск синхронизации без перезапуска контейнера
    shift
    echo "Запуск синхронизации в запущенном контейнере..."
    docker compose exec app python src/main.py --skip-web-server "$@"
    exit $?
fi

if [ ! -f .env ]; then
    echo "Ошибка: Файл .env не найден!"
    echo "Создайте файл .env на основе .env.example"
    exit 1
fi

if [ ! -f .cache ]; then
    echo "Ошибка: Файл кэша Spotify не найден!"
    echo "Сначала запустите скрипт scripts/start_auth.sh для аутентификации в Spotify."
    exit 1
fi

echo "Запуск приложения в Docker..."
docker compose down

if [ $# -gt 0 ]; then
    echo "Запуск с аргументами: $@"
    
    CMD="[\"python\", \"src/main.py\""
    for arg in "$@"; do
        CMD="$CMD, \"$arg\""
    done
    CMD="$CMD]"
    
    echo "services:" > docker-compose.override.yml
    echo "  app:" >> docker-compose.override.yml
    echo "    command: $CMD" >> docker-compose.override.yml
    
    docker compose up -d
    
    rm docker-compose.override.yml
else
    docker compose up -d
fi

echo "Приложение запущено в фоновом режиме."
echo "Для просмотра логов используйте: docker compose logs -f app"
echo "Для запуска синхронизации без перезапуска: docker compose exec app python src/main.py --skip-web-server --sync-playlists --sync-favorite-albums --sync-favorite-artists --force-full-sync"
echo "Или используйте: ./scripts/sync.sh" 