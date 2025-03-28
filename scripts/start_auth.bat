@echo off
setlocal enabledelayedexpansion

:: Переходим в корневую директорию проекта
cd /d "%~dp0\.."

echo Проверка наличия файла .env...
if not exist .env (
    echo Ошибка: Файл .env не найден!
    echo Создайте файл .env на основе .env.example
    exit /b 1
)

echo Создание временного виртуального окружения...
python -m venv temp_venv

echo Активация окружения...
call temp_venv\Scripts\activate.bat

echo Установка необходимых зависимостей...
pip install spotipy python-dotenv

echo Запуск скрипта аутентификации...
python scripts\spotify_auth.py

echo Деактивация окружения...
call deactivate

echo Удаление временного виртуального окружения...
rmdir /s /q temp_venv

if not exist .cache (
    echo Ошибка: Аутентификация не удалась или кэш не был создан.
    exit /b 1
)

echo Аутентификация успешно завершена!
echo Файл .cache создан и готов к использованию в Docker.
echo Теперь вы можете запустить скрипт scripts\start.bat для запуска приложения.

pause 