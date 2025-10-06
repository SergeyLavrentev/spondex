import datetime
import sqlite3
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


class DatabaseManager:
    def __init__(self, db_path: str = "spondex.db"):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        self._create_tables()

    def _create_tables(self):
        # Таблицы уже созданы через SQL-скрипт create_tables.sql
        self.conn.commit()

    def get_last_sync_time(self, service: str) -> Optional[datetime.datetime]:
        self.cursor.execute(
            "SELECT last_sync FROM sync_history WHERE service = ?",
            (service,)
        )
        result = self.cursor.fetchone()
        if result and result["last_sync"]:
            return datetime.datetime.fromisoformat(result["last_sync"])
        return None

    def update_last_sync_time(self, service: str, sync_time: datetime.datetime):
        self.cursor.execute(
            "INSERT OR REPLACE INTO sync_history (service, last_sync) VALUES (?, ?)",
            (service, sync_time.isoformat())
        )
        self.conn.commit()

    def check_track_exists(self, service: str, track_id: str) -> bool:
        if service == "yandex":
            self.cursor.execute(
                "SELECT 1 FROM tracks WHERE yandex_id = ?",
                (track_id,)
            )
        else:
            self.cursor.execute(
                "SELECT 1 FROM tracks WHERE spotify_id = ?",
                (track_id,)
            )
        return bool(self.cursor.fetchone())

    def insert_or_update_track(self, yandex_id: str, spotify_id: str, artist: str, title: str):
        self.cursor.execute(
            """
            INSERT OR REPLACE INTO tracks (yandex_id, spotify_id, artist, title)
            VALUES (?, ?, ?, ?)
            """,
            (yandex_id, spotify_id, artist, title)
        )
        self.conn.commit()

    def get_spotify_id(self, yandex_id: str) -> Optional[str]:
        self.cursor.execute(
            "SELECT spotify_id FROM tracks WHERE yandex_id = ?",
            (yandex_id,),
        )
        result = self.cursor.fetchone()
        return result["spotify_id"] if result else None

    def get_yandex_id(self, spotify_id: str) -> Optional[str]:
        self.cursor.execute(
            "SELECT yandex_id FROM tracks WHERE spotify_id = ?",
            (spotify_id,),
        )
        result = self.cursor.fetchone()
        return result["yandex_id"] if result else None

    # --- Album & artist link helpers -----------------------------------

    def link_album_ids(
        self,
        yandex_id: str,
        spotify_id: str,
        normalized_key: str | None = None,
    ) -> None:
        self.cursor.execute(
            "DELETE FROM album_links WHERE yandex_id = %s OR spotify_id = %s",
            (yandex_id, spotify_id),
        )
        self.cursor.execute(
            """
            INSERT INTO album_links (yandex_id, spotify_id, normalized_key)
            VALUES (%s, %s, %s)
            """,
            (yandex_id, spotify_id, normalized_key),
        )
        self.conn.commit()

    def get_album_link(self, service: str, entity_id: str) -> Optional[str]:
        if service == "yandex":
            self.cursor.execute(
                "SELECT spotify_id FROM album_links WHERE yandex_id = %s",
                (entity_id,),
            )
        else:
            self.cursor.execute(
                "SELECT yandex_id FROM album_links WHERE spotify_id = %s",
                (entity_id,),
            )
        result = self.cursor.fetchone()
        if not result:
            return None
        return result["spotify_id"] if service == "yandex" else result["yandex_id"]

    def find_album_link_by_key(self, normalized_key: str) -> Optional[Tuple[str, str]]:
        self.cursor.execute(
            "SELECT yandex_id, spotify_id FROM album_links WHERE normalized_key = %s",
            (normalized_key,),
        )
        result = self.cursor.fetchone()
        if result:
            return result["yandex_id"], result["spotify_id"]
        return None

    def unlink_album(self, service: str, entity_id: str) -> None:
        if service == "yandex":
            self.cursor.execute("DELETE FROM album_links WHERE yandex_id = %s", (entity_id,))
        else:
            self.cursor.execute("DELETE FROM album_links WHERE spotify_id = %s", (entity_id,))
        self.conn.commit()

    def link_artist_ids(
        self,
        yandex_id: str,
        spotify_id: str,
        normalized_key: str | None = None,
    ) -> None:
        self.cursor.execute(
            "DELETE FROM artist_links WHERE yandex_id = %s OR spotify_id = %s",
            (yandex_id, spotify_id),
        )
        self.cursor.execute(
            """
            INSERT INTO artist_links (yandex_id, spotify_id, normalized_key)
            VALUES (%s, %s, %s)
            """,
            (yandex_id, spotify_id, normalized_key),
        )
        self.conn.commit()

    def get_artist_link(self, service: str, entity_id: str) -> Optional[str]:
        if service == "yandex":
            self.cursor.execute(
                "SELECT spotify_id FROM artist_links WHERE yandex_id = %s",
                (entity_id,),
            )
        else:
            self.cursor.execute(
                "SELECT yandex_id FROM artist_links WHERE spotify_id = %s",
                (entity_id,),
            )
        result = self.cursor.fetchone()
        if not result:
            return None
        return result["spotify_id"] if service == "yandex" else result["yandex_id"]

    def find_artist_link_by_key(self, normalized_key: str) -> Optional[Tuple[str, str]]:
        self.cursor.execute(
            "SELECT yandex_id, spotify_id FROM artist_links WHERE normalized_key = %s",
            (normalized_key,),
        )
        result = self.cursor.fetchone()
        if result:
            return result["yandex_id"], result["spotify_id"]
        return None

    def unlink_artist(self, service: str, entity_id: str) -> None:
        if service == "yandex":
            self.cursor.execute("DELETE FROM artist_links WHERE yandex_id = %s", (entity_id,))
        else:
            self.cursor.execute("DELETE FROM artist_links WHERE spotify_id = %s", (entity_id,))
        self.conn.commit()

    # --- Playlist helpers -------------------------------------------------

    def upsert_playlist(
        self,
        service: str,
        playlist_id: str,
        name: Optional[str],
        owner: Optional[str],
    ) -> int:
        # Check if exists
        self.cursor.execute(
            "SELECT id FROM playlists WHERE service = ? AND playlist_id = ?",
            (service, playlist_id),
        )
        row = self.cursor.fetchone()
        if row:
            playlist_pk = row["id"]
            self.cursor.execute(
                "UPDATE playlists SET name = ?, owner = ? WHERE id = ?",
                (name, owner, playlist_pk),
            )
        else:
            self.cursor.execute(
                "INSERT INTO playlists (service, playlist_id, name, owner) VALUES (?, ?, ?, ?)",
                (service, playlist_id, name, owner),
            )
            playlist_pk = self.cursor.lastrowid
        self.conn.commit()
        return playlist_pk

    def get_playlist(self, service: str, playlist_id: str) -> Optional[Dict[str, Any]]:
        self.cursor.execute(
            "SELECT * FROM playlists WHERE service = %s AND playlist_id = %s",
            (service, playlist_id),
        )
        return self.cursor.fetchone()

    def fetch_playlists(self, service: str) -> List[Dict[str, Any]]:
        self.cursor.execute(
            "SELECT * FROM playlists WHERE service = %s ORDER BY name",
            (service,),
        )
        return list(self.cursor.fetchall())

    def find_playlist_by_name(self, service: str, name: str) -> Optional[Dict[str, Any]]:
        self.cursor.execute(
            "SELECT * FROM playlists WHERE service = %s AND LOWER(name) = LOWER(%s)",
            (service, name),
        )
        return self.cursor.fetchone()

    def remove_playlists_not_in(self, service: str, playlist_ids: Sequence[str]) -> None:
        if not playlist_ids:
            self.cursor.execute("DELETE FROM playlists WHERE service = ?", (service,))
        else:
            placeholders = ','.join('?' for _ in playlist_ids)
            self.cursor.execute(
                f"DELETE FROM playlists WHERE service = ? AND playlist_id NOT IN ({placeholders})",
                (service, *playlist_ids),
            )
        self.conn.commit()

    def set_playlist_tracks(
        self,
        playlist_pk: int,
        service: str,
        tracks: Iterable[Tuple[str, Optional[int], Optional[datetime.datetime]]],
    ) -> None:
        self.cursor.execute(
            "DELETE FROM playlist_tracks WHERE playlist_pk = ?",
            (playlist_pk,),
        )
        batch: List[Tuple[int, str, str, Optional[int], Optional[str]]] = []
        for track_id, position, added_at in tracks:
            added_at_str = added_at.isoformat() if added_at else None
            batch.append((playlist_pk, service, track_id, position, added_at_str))

        if batch:
            self.cursor.executemany(
                """
                INSERT INTO playlist_tracks (playlist_pk, service, track_id, position, added_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                batch,
            )
        self.conn.commit()

    def get_playlist_tracks(self, playlist_pk: int) -> List[Dict[str, Any]]:
        self.cursor.execute(
            """
            SELECT track_id, position, added_at
            FROM playlist_tracks
            WHERE playlist_pk = %s
            ORDER BY position NULLS LAST, added_at
            """,
            (playlist_pk,),
        )
        return list(self.cursor.fetchall())

    # --- Favorites helpers ------------------------------------------------

    def upsert_favorite_album(
        self,
        service: str,
        album_id: str,
        name: Optional[str],
        artist: Optional[str],
        last_seen: Optional[datetime.datetime],
    ) -> None:
        self.cursor.execute(
            """
            INSERT INTO favorite_albums (service, album_id, name, artist, last_seen)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (service, album_id) DO UPDATE
            SET name = EXCLUDED.name,
                artist = EXCLUDED.artist,
                last_seen = EXCLUDED.last_seen
            """,
            (service, album_id, name, artist, last_seen),
        )
        self.conn.commit()

    def remove_favorite_albums_not_in(self, service: str, album_ids: Sequence[str]) -> None:
        if not album_ids:
            self.cursor.execute("DELETE FROM favorite_albums WHERE service = ?", (service,))
        else:
            placeholders = ','.join('?' for _ in album_ids)
            self.cursor.execute(
                f"DELETE FROM favorite_albums WHERE service = ? AND album_id NOT IN ({placeholders})",
                (service, *album_ids),
            )
        self.conn.commit()

    def upsert_favorite_artist(
        self,
        service: str,
        artist_id: str,
        name: Optional[str],
        last_seen: Optional[datetime.datetime],
    ) -> None:
        self.cursor.execute(
            """
            INSERT INTO favorite_artists (service, artist_id, name, last_seen)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (service, artist_id) DO UPDATE
            SET name = EXCLUDED.name,
                last_seen = EXCLUDED.last_seen
            """,
            (service, artist_id, name, last_seen),
        )
        self.conn.commit()

    def remove_favorite_artists_not_in(self, service: str, artist_ids: Sequence[str]) -> None:
        if not artist_ids:
            self.cursor.execute("DELETE FROM favorite_artists WHERE service = %s", (service,))
        else:
            self.cursor.execute(
                "DELETE FROM favorite_artists WHERE service = %s AND NOT (artist_id = ANY(%s))",
                (service, list(artist_ids)),
            )
        self.conn.commit()

    def close(self):
        self.cursor.close()
        self.conn.close()