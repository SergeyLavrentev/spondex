import datetime
import sqlite3
from typing import Optional


class DatabaseManager:
    def __init__(self, db_name: str):
        self.conn = sqlite3.connect(db_name)
        self.cursor = self.conn.cursor()
        self._create_tables()

    def _create_tables(self):
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS synced_tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                yandex_id TEXT UNIQUE,
                spotify_id TEXT UNIQUE,
                artist TEXT,
                title TEXT,
                last_synced TIMESTAMP
            )
        ''')
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS sync_status (
                service TEXT PRIMARY KEY,
                last_synced TIMESTAMP
            )
        ''')
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS undiscovered_tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service TEXT,
                artist TEXT,
                title TEXT,
                timestamp TIMESTAMP
            )
        ''')
        self.conn.commit()

    def get_last_sync_time(self, service: str) -> Optional[datetime.datetime]:
        self.cursor.execute('SELECT last_synced FROM sync_status WHERE service = ?', (service,))
        result = self.cursor.fetchone()
        return datetime.datetime.strptime(result[0], '%Y-%m-%d %H:%M:%S.%f') if result else None

    def update_last_sync_time(self, service: str, curr_ts: datetime.datetime=None):
        if curr_ts is None:
            curr_ts = datetime.datetime.now()
        self.cursor.execute('''
            INSERT OR REPLACE INTO sync_status (service, last_synced)
            VALUES (?, ?)
        ''', (service, curr_ts))
        self.conn.commit()

    def insert_or_update_track(self, yandex_id: str, spotify_id: str, artist: str, title: str):
        self.cursor.execute('''
            INSERT OR REPLACE INTO synced_tracks (yandex_id, spotify_id, artist, title, last_synced)
            VALUES (?, ?, ?, ?, ?)
        ''', (yandex_id, spotify_id, artist, title, datetime.datetime.now()))
        self.conn.commit()

    def check_track_exists(self, service: str, track_id: str) -> bool:
        column = 'yandex_id' if service == 'yandex' else 'spotify_id'
        self.cursor.execute(f'SELECT * FROM synced_tracks WHERE {column} = ?', (track_id,))
        return bool(self.cursor.fetchone())

    def add_undiscovered_track(self, service: str, artist: str, title: str):
        self.cursor.execute('''
            INSERT INTO undiscovered_tracks (service, artist, title, timestamp)
            VALUES (?, ?, ?, ?)
        ''', (service, artist, title, datetime.datetime.now()))
        self.conn.commit()

    def close(self):
        self.conn.close()