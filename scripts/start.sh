#!/bin/bash

# Переходим в корневую директорию проекта
cd "$(dirname "$0")/.."

# Проверка наличия файла .env
if [ ! -f .env ]; then
    echo "Ошибка: Файл .env не найден!"
    echo "Создайте файл .env на основе .env.example"
    exit 1
fi

# Проверка наличия файла кэша
if [ ! -f .cache ]; then
    echo "Ошибка: Файл кэша Spotify не найден!"
    echo "Сначала запустите скрипт scripts/start_auth.sh для аутентификации в Spotify."
    exit 1
fi

# Запуск Docker Compose
echo "Запуск приложения в Docker..."
docker-compose down
docker-compose up -d

echo "Приложение запущено в фоновом режиме."
echo "Для просмотра логов используйте: docker-compose logs -f app" 