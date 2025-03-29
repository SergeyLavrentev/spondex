@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0\.."

echo Проверка наличия файла .env...
if not exist .env (
    echo Ошибка: Файл .env не найден!
    echo Создайте файл .env на основе .env.example
    exit /b 1
)

echo Проверка наличия файла кэша Spotify...
if not exist .cache (
    echo Ошибка: Файл кэша Spotify не найден!
    echo Сначала запустите скрипт scripts\start_auth.bat для аутентификации в Spotify.
    exit /b 1
)

echo Остановка существующих контейнеров...
docker-compose down

if "%~1"=="" (
    echo Запуск приложения в Docker...
    docker-compose up -d
) else (
    echo Запуск с аргументами: %*
    
    set CMD=[\"python\", \"src/main.py\"
    
    for %%a in (%*) do (
        set CMD=!CMD!, \"%%a\"
    )
    
    set CMD=!CMD!]
    
    echo services: > docker-compose.override.yml
    echo   app: >> docker-compose.override.yml
    echo     command: !CMD! >> docker-compose.override.yml
    
    docker-compose up -d
    
    del docker-compose.override.yml
)

echo Приложение запущено в фоновом режиме.
echo Для просмотра логов используйте: docker-compose logs -f app

pause 