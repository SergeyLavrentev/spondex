#!/usr/bin/env python3

import json
import os
import shutil
import sys
import traceback

from dotenv import load_dotenv

import spotipy
from spotipy.oauth2 import SpotifyOAuth

def main():
    # Загружаем переменные окружения
    try:
        load_dotenv()
    except Exception as e:
        print(f"Ошибка при загрузке переменных окружения: {e}")
        sys.exit(1)
    
    client_id = os.getenv("SPOTIPY_CLIENT_ID")
    client_secret = os.getenv("SPOTIPY_CLIENT_SECRET")
    redirect_uri = os.getenv("SPOTIPY_REDIRECT_URI")
    
    if not all([client_id, client_secret, redirect_uri]):
        print("Ошибка: Не найдены необходимые переменные окружения.")
        print("Убедитесь, что файл .env содержит SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET и SPOTIPY_REDIRECT_URI")
        sys.exit(1)
    
    print(f"Используется redirect URI: {redirect_uri}")
    print("Запуск процесса аутентификации Spotify...")
    
    # Инициализируем переменную токена перед try блоком
    token_info = None
    
    try:
        # Определяем путь к кэшу явно (используется в новых версиях spotipy)
        cache_path = os.path.join(os.path.expanduser("~"), ".cache")
        
        # Запускаем процесс аутентификации
        scopes = " ".join(
            [
                "user-library-read",
                "user-library-modify",
                "user-follow-read",
                "user-follow-modify",
                "playlist-read-private",
                "playlist-read-collaborative",
            ]
        )

        sp_oauth = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope=scopes,
            open_browser=True,
            cache_path=os.path.join(cache_path, "spotipy")  # Явно указываем путь к кэшу
        )
        
        print("Открывается браузер для авторизации. Пожалуйста, войдите в свой аккаунт Spotify и разрешите доступ...")
        print("После авторизации вас перенаправят. Скопируйте полученный URL и вставьте его здесь:")
        
        # Получаем токен
        token_info = sp_oauth.get_access_token(as_dict=True)
        
        # Создаем клиент Spotify для проверки аутентификации
        sp = spotipy.Spotify(auth=token_info['access_token'])
        user_info = sp.current_user()
        
        print(f"\nАутентификация успешна! Пользователь: {user_info['display_name']}")
        
        # Теперь мы знаем путь к кэш-файлу (передали его выше в SpotifyOAuth)
        spotipy_cache_path = os.path.join(cache_path, "spotipy")
        print(f"Путь к кэш-файлу: {spotipy_cache_path}")
        
        if os.path.exists(spotipy_cache_path):
            print(f"Кэш-файл найден по пути: {spotipy_cache_path}")
            
            # Копируем кэш в текущий каталог
            try:
                shutil.copy2(spotipy_cache_path, "./.cache")
                print("Кэш-файл успешно скопирован в ./.cache")
                print("Теперь вы можете запускать приложение в Docker!")
            except Exception as e:
                print(f"Ошибка при копировании кэша: {e}")
                traceback.print_exc()
        else:
            # Проверяем .cache в текущей директории
            if os.path.exists("./.cache"):
                print("Кэш-файл уже существует в текущей директории: ./.cache")
            else:
                print(f"Предупреждение: Кэш-файл не найден по пути {spotipy_cache_path}")
                print("Проверяем все возможные места расположения кэша...")
                
                # Проверяем другие возможные местоположения
                possible_locations = [
                    "./.cache",
                    os.path.expanduser("~/.cache/spotipy"),
                    os.path.expanduser("~/.spotipy/cache"),
                    "./.spotipy-cache"
                ]
                
                for loc in possible_locations:
                    if os.path.exists(loc):
                        print(f"Найден кэш в: {loc}")
                        shutil.copy2(loc, "./.cache")
                        print("Скопирован в ./.cache")
                        break
                else:
                    # Создаем новый кэш-файл на основе полученного токена
                    with open("./.cache", "w") as f:
                        json.dump(token_info, f)
                    print("Создан новый кэш-файл на основе полученного токена")
    
    except Exception as e:
        print(f"Произошла ошибка при аутентификации: {e}")
        traceback.print_exc()
        # Даже при ошибке мы создаем файл .cache, чтобы скрипт start.sh мог продолжить работу
        if token_info and not os.path.exists("./.cache"):
            with open("./.cache", "w") as f:
                json.dump(token_info, f)
            print("Создан резервный кэш-файл, несмотря на ошибку")
        sys.exit(1)

if __name__ == "__main__":
    main() 