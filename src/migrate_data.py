import sqlite3
import psycopg
import os
from dotenv import load_dotenv

def migrate_data():
    sqlite_conn = sqlite3.connect('music_sync.db')
    sqlite_cur = sqlite_conn.cursor()

    load_dotenv()
    
    pg_params = {
        "dbname": os.getenv("POSTGRES_DB", "music_sync"),
        "user": os.getenv("POSTGRES_USER"),
        "password": os.getenv("POSTGRES_PASSWORD"),
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": os.getenv("POSTGRES_PORT", "5432")
    }
    pg_conn = psycopg.connect(**pg_params)
    pg_cur = pg_conn.cursor()

    sqllite_history_table = "sync_status"
    sqllite_tracks_table = "synced_tracks"
    sqllite_undiscovered_tracks_table = "undiscovered_tracks"

    try:
        sqlite_cur.execute(f"SELECT * FROM {sqllite_history_table}")
        for row in sqlite_cur.fetchall():
            pg_cur.execute(
                "INSERT INTO sync_history (service, last_sync) VALUES (%s, %s)",
                row
            )

        sqlite_cur.execute(f"SELECT * FROM {sqllite_tracks_table}")
        for row in sqlite_cur.fetchall():
            pg_cur.execute(
                "INSERT INTO tracks (yandex_id, spotify_id, artist, title) VALUES (%s, %s, %s, %s)",
                row
            )

        sqlite_cur.execute(f"SELECT service, artist, title, created_at FROM {sqllite_undiscovered_tracks_table}")
        for row in sqlite_cur.fetchall():
            pg_cur.execute(
                "INSERT INTO undiscovered_tracks (service, artist, title, created_at) VALUES (%s, %s, %s, %s)",
                row
            )

        pg_conn.commit()
        print("Миграция успешно завершена")

    finally:
        sqlite_cur.close()
        sqlite_conn.close()
        pg_cur.close()
        pg_conn.close()

if __name__ == "__main__":
    migrate_data() 