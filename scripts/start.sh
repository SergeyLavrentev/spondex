#!/bin/bash

cd "$(dirname "$0")/.."

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