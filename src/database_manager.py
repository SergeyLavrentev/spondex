import psycopg2
from psycopg2.extras import DictCursor
import datetime
from typing import Optional


class DatabaseManager:
    def __init__(self, connection_params: dict):
        self.conn = psycopg2.connect(**connection_params)
        self.cursor = self.conn.cursor(cursor_factory=DictCursor)
        self._create_tables()

    def _create_tables(self):
        # Таблицы уже созданы через SQL-скрипт create_tables.sql
        self.conn.commit()

    def get_last_sync_time(self, service: str) -> Optional[datetime.datetime]:
        self.cursor.execute(
            "SELECT last_sync FROM sync_history WHERE service = %s",
            (service,)
        )
        result = self.cursor.fetchone()
        return result[0] if result else None

    def update_last_sync_time(self, service: str, sync_time: datetime.datetime):
        self.cursor.execute(
            """
            INSERT INTO sync_history (service, last_sync)
            VALUES (%s, %s)
            ON CONFLICT (service) DO UPDATE SET last_sync = EXCLUDED.last_sync
            """,
            (service, sync_time)
        )
        self.conn.commit()

    def check_track_exists(self, service: str, track_id: str) -> bool:
        if service == "yandex":
            self.cursor.execute(
                "SELECT 1 FROM tracks WHERE yandex_id = %s",
                (track_id,)
            )
        else:
            self.cursor.execute(
                "SELECT 1 FROM tracks WHERE spotify_id = %s",
                (track_id,)
            )
        return bool(self.cursor.fetchone())

    def insert_or_update_track(self, yandex_id: str, spotify_id: str, artist: str, title: str):
        self.cursor.execute(
            """
            INSERT INTO tracks (yandex_id, spotify_id, artist, title)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (yandex_id, spotify_id) DO UPDATE 
            SET artist = EXCLUDED.artist, title = EXCLUDED.title
            """,
            (yandex_id, spotify_id, artist, title)
        )
        self.conn.commit()

    def add_undiscovered_track(self, service: str, artist: str, title: str):
        self.cursor.execute(
            """
            INSERT INTO undiscovered_tracks (service, artist, title)
            VALUES (%s, %s, %s)
            """,
            (service, artist, title)
        )
        self.conn.commit()

    def close(self):
        self.cursor.close()
        self.conn.close()