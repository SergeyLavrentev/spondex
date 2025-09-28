import argparse
import datetime
import json
import logging
import os
import random
import time
from typing import Any, Callable, Iterable, List, Optional, Sequence, Tuple

import spotipy
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyOAuth
from yandex_music import Client as YandexClient
from yandex_music.exceptions import YandexMusicError

from base_class import MusicService
from database_manager import DatabaseManager
from models import FavoriteAlbum, FavoriteArtist, PlaylistSnapshot, PlaylistTrack
from sync_helpers import album_key, artist_key, match_entities, normalize_text

from spotipy.exceptions import SpotifyException

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def _now_utc() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _parse_datetime(value: Optional[str]) -> Optional[datetime.datetime]:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.datetime.fromisoformat(value)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _join_artist_names(artists: Optional[Iterable[Any]]) -> Optional[str]:
    if not artists:
        return None
    filtered = []
    for artist in artists:
        name = getattr(artist, "name", None)
        if not name:
            continue
        stripped = name.strip()
        if stripped:
            filtered.append(stripped)
    if not filtered:
        return None
    return ", ".join(filtered)


def check_and_fix_spotify_cache():
    """Проверяет и исправляет кэш файл Spotify если он некорректный"""
    cache_path = "./.cache"
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r") as f:
                content = f.read().strip()
                
            # Проверяем, является ли это валидным JSON
            json.loads(content)
            logger.info("Кэш файл Spotify корректен")
            
        except json.JSONDecodeError:
            logger.warning("Обнаружен некорректный кэш файл Spotify, попытка исправления...")
            try:
                # Пытаемся исправить, если это Python dict строка
                if content.startswith("{'") and content.endswith("'}"):
                    # Преобразуем Python dict строку в валидный JSON
                    content_fixed = content.replace("'", '"')
                    # Проверяем, что теперь это валидный JSON
                    parsed = json.loads(content_fixed)
                    
                    # Перезаписываем файл с корректным JSON
                    with open(cache_path, "w") as f:
                        json.dump(parsed, f)
                    logger.info("Кэш файл Spotify успешно исправлен")
                else:
                    logger.error("Не удалось исправить кэш файл автоматически. Удаляем некорректный файл.")
                    os.remove(cache_path)
            except Exception as e:
                logger.error(f"Ошибка при исправлении кэш файла: {e}")
                logger.info("Удаляем некорректный кэш файл")
                try:
                    os.remove(cache_path)
                except OSError as cleanup_error:
                    logger.warning("Не удалось удалить некорректный кэш Spotify: %s", cleanup_error)
        except Exception as e:
            logger.error(f"Ошибка при проверке кэш файла: {e}")
    else:
        logger.warning("Кэш файл Spotify не найден. Убедитесь, что вы выполнили аутентификацию.")


class YandexMusic(MusicService):
    def __init__(self, db_manager: DatabaseManager, token: str):
        super().__init__(db_manager)
        self.client = YandexClient(token=token).init()
        self._max_attempts = 5
        self._base_retry_delay = 1.5

    def _execute_with_retry(self, description: str, func: Callable[[], Any]):
        for attempt in range(1, self._max_attempts + 1):
            try:
                return func()
            except YandexMusicError as exc:
                last_attempt = attempt == self._max_attempts
                wait_time = self._base_retry_delay * (2 ** (attempt - 1))
                jitter = random.uniform(0, 0.5)
                total_wait = wait_time + jitter
                if last_attempt:
                    logger.error(
                        "%s failed after %s attempts: %s",
                        description,
                        attempt,
                        exc,
                    )
                    raise
                logger.warning(
                    "%s failed (attempt %s/%s): %s. Retrying in %.1fs",
                    description,
                    attempt,
                    self._max_attempts,
                    exc,
                    total_wait,
                )
                time.sleep(total_wait)
            except Exception:
                if attempt == self._max_attempts:
                    raise
                time.sleep(self._base_retry_delay * (2 ** (attempt - 1)))

    def get_tracks(self, force_full_sync: bool) -> List[dict]:
        short_tracks = self.client.users_likes_tracks()
        full_tracks = []

        last_sync = (
            self.db_manager.get_last_sync_time("yandex")
            if not force_full_sync
            else None
        )
        if last_sync:
            last_sync = last_sync.replace(tzinfo=datetime.timezone.utc)

        for track in short_tracks:
            added_at = datetime.datetime.strptime(
                track.timestamp, "%Y-%m-%dT%H:%M:%S%z"
            ) + datetime.timedelta(hours=3)
            if force_full_sync or not self.db_manager.check_track_exists(
                "yandex", track.id
            ):
                if last_sync is None or added_at > last_sync:
                    full_tracks.append(track.fetch_track())

        return full_tracks

    def search_track(self, artist: str, title: str) -> Optional[dict]:
        query = f"{artist} {title}"
        result = self.client.search(query)
        if result["best"] and result["best"]["type"] == "track":
            return result["best"]["result"]
        return None

    def add_track(self, track: dict) -> Optional[str]:
        yandex_track = self.search_track(
            track["track"]["artists"][0]["name"], track["track"]["name"]
        )
        if yandex_track:
            self.client.users_likes_tracks_add(yandex_track["id"])
            return yandex_track["id"]
        logger.warning(
            f"Track not found in Yandex: {track['track']['artists'][0]['name']} - {track['track']['name']}"
        )
        self.db_manager.add_undiscovered_track(
            "yandex", track["track"]["artists"][0]["name"], track["track"]["name"]
        )
        return None

    def remove_duplicates(self):
        tracks = self.client.users_likes_tracks()
        tracks_seen = set()
        tracks_to_remove = []

        for track in tracks:
            full_track = track.fetch_track()
            track_key = (full_track.title.lower(), full_track.artists[0].name.lower())

            if track_key in tracks_seen:
                tracks_to_remove.append(track.track_id)
            else:
                tracks_seen.add(track_key)

        if tracks_to_remove:
            self.client.users_likes_tracks_remove(tracks_to_remove)
            logger.info(f"Removed {len(tracks_to_remove)} duplicate tracks from Yandex")

    def _get_album_id_for_track(self, track_id: str) -> Optional[str]:
        def _fetch():
            return self.client.tracks(track_id)

        tracks = self._execute_with_retry(
            f"Fetch Yandex track metadata {track_id}", _fetch
        )
        if not tracks:
            return None
        track_obj = tracks[0]
        albums = getattr(track_obj, "albums", None)
        if not albums:
            return None
        album = albums[0]
        album_id = getattr(album, "id", None)
        return str(album_id) if album_id is not None else None

    def resolve_track_for_playlist(
        self,
        spotify_track_id: Optional[str],
        title: Optional[str],
        artist: Optional[str],
    ) -> Optional[Tuple[str, str, str]]:
        if spotify_track_id:
            stored_id = self.db_manager.get_yandex_id(spotify_track_id)
        else:
            stored_id = None

        track_part: Optional[str] = None
        album_part: Optional[str] = None

        if stored_id:
            if ":" in stored_id:
                track_part, album_part = stored_id.split(":", 1)
            else:
                track_part = stored_id
                album_part = self._get_album_id_for_track(stored_id)
            if track_part and album_part:
                composite = f"{track_part}:{album_part}"
                return track_part, album_part, composite

        if not title or not artist:
            return None

        def _search():
            return self.search_track(artist, title)

        search_result = self._execute_with_retry(
            f"Search Yandex track '{artist} - {title}'",
            _search,
        )
        if not search_result:
            return None

        def _get_value(obj: Any, key: str) -> Any:
            if obj is None:
                return None
            if isinstance(obj, dict):
                return obj.get(key)
            return getattr(obj, key, None)

        track_identifier = _get_value(search_result, "id")
        if track_identifier is None:
            track_identifier = _get_value(search_result, "track_id")
        if track_identifier is None:
            return None

        track_id_raw = str(track_identifier)
        if ":" in track_id_raw:
            track_part, album_part = track_id_raw.split(":", 1)
        else:
            track_part = track_id_raw
            albums = _get_value(search_result, "albums") or []
            first_album = albums[0] if albums else None
            album_candidate = _get_value(first_album, "id")
            album_part = str(album_candidate) if album_candidate is not None else None

        if track_part and not album_part:
            album_part = self._get_album_id_for_track(track_part)

        if not track_part or not album_part:
            return None

        composite = f"{track_part}:{album_part}"
        try:
            self._execute_with_retry(
                f"Ensure Yandex track {composite} is liked",
                lambda: self.client.users_likes_tracks_add([composite]),
            )
        except YandexMusicError:
            pass

        if spotify_track_id:
            self.db_manager.insert_or_update_track(
                track_part,
                spotify_track_id,
                artist,
                title,
            )

        return track_part, album_part, composite

    def fetch_playlist(self, playlist_id: str) -> Optional[Any]:
        def _fetch():
            return self.client.users_playlists(playlist_id)

        return self._execute_with_retry(
            f"Fetch Yandex playlist details {playlist_id}", _fetch
        )

    def ensure_playlist(
        self, name: str, existing_playlist_id: Optional[str] = None
    ) -> Optional[Any]:
        if existing_playlist_id:
            return self.fetch_playlist(existing_playlist_id)

        normalized_target = normalize_text(name)

        def _list():
            return self.client.users_playlists_list()

        playlists = self._execute_with_retry("List Yandex playlists", _list)
        for playlist in playlists or []:
            title = getattr(playlist, "title", "")
            if normalize_text(title) == normalized_target:
                return self.fetch_playlist(str(getattr(playlist, "kind", "")))

        def _create():
            return self.client.users_playlists_create(name, visibility="private")

        created = self._execute_with_retry(
            f"Create Yandex playlist '{name}'", _create
        )
        return created

    def insert_track_into_playlist(
        self,
        playlist_obj,
        track_id: str,
        album_id: str,
        at: Optional[int] = None,
    ):
        position = at if at is not None else len(getattr(playlist_obj, "tracks", []) or [])

        def _insert():
            return self.client.users_playlists_insert_track(
                getattr(playlist_obj, "kind"),
                track_id,
                album_id,
                at=position,
                revision=getattr(playlist_obj, "revision", 1),
            )

        updated = self._execute_with_retry(
            f"Insert track {track_id}:{album_id} into Yandex playlist {getattr(playlist_obj, 'kind', 'unknown')}",
            _insert,
        )
        return updated or playlist_obj

    def get_playlists(
        self, force_full_sync: bool, include_followed: bool = True
    ) -> List[PlaylistSnapshot]:
        playlists = self._execute_with_retry(
            "Fetch Yandex playlists", self.client.users_playlists_list
        )
        snapshots: List[PlaylistSnapshot] = []

        for playlist in playlists:
            self._execute_with_retry(
                f"Fetch Yandex playlist tracks ({playlist.kind})",
                playlist.fetch_tracks,
            )
            full_playlist = playlist
            tracks: List[PlaylistTrack] = []
            for position, playlist_track in enumerate(getattr(full_playlist, "tracks", []) or []):
                track_id = getattr(playlist_track, "track_id", None)
                if not track_id:
                    continue
                title = None
                artist_name = None
                track_obj = getattr(playlist_track, "track", None)
                if track_obj:
                    title = getattr(track_obj, "title", None)
                    artist_name = _join_artist_names(getattr(track_obj, "artists", []))
                added_at = _parse_datetime(getattr(playlist_track, "timestamp", None))
                tracks.append(
                    PlaylistTrack(
                        track_id=str(track_id),
                        title=title,
                        artist=artist_name,
                        position=position,
                        added_at=added_at,
                    )
                )

            owner_login = None
            if getattr(full_playlist, "owner", None):
                owner_login = getattr(full_playlist.owner, "login", None) or getattr(
                    full_playlist.owner, "name", None
                )

            snapshots.append(
                PlaylistSnapshot(
                    service="yandex",
                    playlist_id=str(full_playlist.kind),
                    name=getattr(full_playlist, "title", None),
                    owner=owner_login,
                    tracks=tracks,
                    last_modified=_parse_datetime(
                        getattr(full_playlist, "modified", None)
                    ),
                    is_owned=True,
                )
            )

        return snapshots

    def get_favorite_albums(self) -> List[FavoriteAlbum]:
        likes = self._execute_with_retry(
            "Fetch Yandex favorite albums", self.client.users_likes_albums
        )
        favorites: List[FavoriteAlbum] = []
        for like in likes or []:
            album_obj = getattr(like, "album", None)
            if not album_obj:
                continue
            favorites.append(
                FavoriteAlbum(
                    service="yandex",
                    album_id=str(getattr(album_obj, "id", "")),
                    name=getattr(album_obj, "title", None),
                    artist=_join_artist_names(getattr(album_obj, "artists", [])),
                    last_seen=_parse_datetime(getattr(like, "timestamp", None)),
                )
            )
        return favorites

    def ensure_album_in_library(self, album: FavoriteAlbum) -> Optional[FavoriteAlbum]:
        query_parts = [album.name or "", album.artist or ""]
        query = " ".join(part for part in query_parts if part).strip()
        if not query:
            logger.debug("Skipping Yandex album ensure: missing metadata for %s", album)
            return None

        search = self._execute_with_retry(
            f"Search Yandex album '{query}'",
            lambda: self.client.search(query, type_="album"),
        )

        candidates = []
        if search and getattr(search, "albums", None):
            candidates = getattr(search.albums, "results", []) or []

        target_key = album_key(album)
        for candidate in candidates:
            candidate_album = FavoriteAlbum(
                service="yandex",
                album_id=str(getattr(candidate, "id", "")),
                name=getattr(candidate, "title", None),
                artist=_join_artist_names(getattr(candidate, "artists", [])),
                last_seen=_now_utc(),
            )
            if target_key and album_key(candidate_album) != target_key:
                continue

            def _add_candidate():
                return self.client.users_likes_albums_add([candidate_album.album_id])

            self._execute_with_retry(
                f"Add Yandex album {candidate_album.album_id}", _add_candidate
            )
            logger.info(
                "Добавлен альбом в Yandex: %s — %s",
                candidate_album.artist,
                candidate_album.name,
            )
            return candidate_album

        logger.warning(
            "Не удалось найти альбом в Yandex по запросу '%s'", query
        )
        return None

    def get_favorite_artists(self) -> List[FavoriteArtist]:
        likes = self._execute_with_retry(
            "Fetch Yandex favorite artists", self.client.users_likes_artists
        )
        favorites: List[FavoriteArtist] = []
        for like in likes or []:
            artist_obj = getattr(like, "artist", None)
            if not artist_obj:
                continue
            favorites.append(
                FavoriteArtist(
                    service="yandex",
                    artist_id=str(getattr(artist_obj, "id", "")),
                    name=getattr(artist_obj, "name", None),
                    last_seen=_parse_datetime(getattr(like, "timestamp", None)),
                )
            )
        return favorites

    def ensure_artist_followed(self, artist: FavoriteArtist) -> Optional[FavoriteArtist]:
        query = artist.name
        if not query:
            logger.debug("Skipping Yandex artist ensure: missing name for %s", artist)
            return None

        search = self._execute_with_retry(
            f"Search Yandex artist '{query}'",
            lambda: self.client.search(query, type_="artist"),
        )
        candidates = []
        if search and getattr(search, "artists", None):
            candidates = getattr(search.artists, "results", []) or []

        target_key = artist_key(artist)
        for candidate in candidates:
            candidate_artist = FavoriteArtist(
                service="yandex",
                artist_id=str(getattr(candidate, "id", "")),
                name=getattr(candidate, "name", None),
                last_seen=_now_utc(),
            )
            if target_key and artist_key(candidate_artist) != target_key:
                continue

            def _follow_candidate():
                return self.client.users_likes_artists_add(
                    [candidate_artist.artist_id]
                )

            self._execute_with_retry(
                f"Follow Yandex artist {candidate_artist.artist_id}",
                _follow_candidate,
            )
            logger.info("Добавлен исполнитель в Yandex: %s", candidate_artist.name)
            return candidate_artist

        logger.warning("Не удалось найти исполнителя в Yandex по запросу '%s'", query)
        return None


class SpotifyMusic(MusicService):
    def __init__(self, db_manager: DatabaseManager):
        super().__init__(db_manager)
        required_scopes = " ".join(
            [
                "user-library-read",
                "user-library-modify",
                "user-follow-read",
                "user-follow-modify",
                "playlist-read-private",
                "playlist-read-collaborative",
            ]
        )
        self.client = spotipy.Spotify(
            auth_manager=SpotifyOAuth(scope=required_scopes)
        )
        self._max_attempts = 5
        self._base_retry_delay = 1.0
        user_profile = self._execute_with_retry(
            "Fetch Spotify current user",
            self.client.me,
        )
        self._current_user_id = (user_profile or {}).get("id")
        self._user_country = (user_profile or {}).get("country")
    
    def _build_playlist_snapshot(
        self,
        playlist_obj: dict,
        include_followed: bool,
    ) -> Optional[PlaylistSnapshot]:
        playlist_id = playlist_obj.get("id")
        if not playlist_id:
            return None

        owner = (playlist_obj.get("owner") or {}).get("id")
        is_owned = owner == self._current_user_id
        if not is_owned and not include_followed:
            return None

        tracks: List[PlaylistTrack] = []
        track_offset = 0
        position = 0
        while True:
            track_response = self._execute_with_retry(
                f"Fetch Spotify playlist {playlist_id} tracks offset={track_offset}",
                lambda off=track_offset: self.client.playlist_items(
                    playlist_id,
                    offset=off,
                    limit=100,
                    additional_types=("track",),
                ),
            )
            track_items = track_response.get("items", [])
            if not track_items:
                break

            for item in track_items:
                track_data = item.get("track") or {}
                track_id = track_data.get("id")
                if not track_id:
                    continue
                added_at = _parse_datetime(item.get("added_at"))
                artist_name = ", ".join(
                    artist.get("name")
                    for artist in track_data.get("artists", [])
                    if artist.get("name")
                ) or None
                tracks.append(
                    PlaylistTrack(
                        track_id=track_id,
                        title=track_data.get("name"),
                        artist=artist_name,
                        position=position,
                        added_at=added_at,
                    )
                )
                position += 1

            track_offset += len(track_items)
            if not track_response.get("next"):
                break

        return PlaylistSnapshot(
            service="spotify",
            playlist_id=playlist_id,
            name=playlist_obj.get("name"),
            owner=(playlist_obj.get("owner") or {}).get("display_name")
            or owner,
            tracks=tracks,
            last_modified=None,
            is_owned=is_owned,
        )

    def _execute_with_retry(self, description: str, func: Callable[[], Any]):
        for attempt in range(1, self._max_attempts + 1):
            try:
                return func()
            except SpotifyException as exc:
                last_attempt = attempt == self._max_attempts
                wait_time = self._base_retry_delay * (2 ** (attempt - 1))
                jitter = random.uniform(0, 0.5)
                total_wait = wait_time + jitter
                if last_attempt:
                    logger.error(
                        "%s failed after %s attempts: %s",
                        description,
                        attempt,
                        exc,
                    )
                    raise
                logger.warning(
                    "%s failed (attempt %s/%s): %s. Retrying in %.1fs",
                    description,
                    attempt,
                    self._max_attempts,
                    exc,
                    total_wait,
                )
                time.sleep(total_wait)
            except Exception:
                if attempt == self._max_attempts:
                    raise
                time.sleep(self._base_retry_delay * (2 ** (attempt - 1)))

    def get_tracks(self, force_full_sync: bool) -> List[dict]:
        last_sync = (
            self.db_manager.get_last_sync_time("spotify")
            if not force_full_sync
            else None
        )
        if last_sync:
            last_sync = last_sync.replace(tzinfo=datetime.timezone.utc)

        results = self._execute_with_retry(
            "Fetch Spotify saved tracks", self.client.current_user_saved_tracks
        )
        tracks = []

        while results["items"]:
            for item in results["items"]:
                track = item["track"]
                added_at = datetime.datetime.strptime(
                    item["added_at"], "%Y-%m-%dT%H:%M:%SZ"
                ).replace(tzinfo=datetime.timezone.utc) + datetime.timedelta(hours=3)
                if force_full_sync or last_sync is None or added_at > last_sync:
                    if force_full_sync or not self.db_manager.check_track_exists(
                        "spotify", track["id"]
                    ):
                        tracks.append(item)

            if results["next"] and (
                force_full_sync
                or not last_sync
                or any(added_at > last_sync for item in results["items"])
            ):
                results = self._execute_with_retry(
                    "Fetch next page of Spotify saved tracks",
                    lambda: self.client.next(results),
                )
            else:
                break

        return tracks

    def search_track(self, artist: str, title: str) -> Optional[dict]:
        query = f"{artist} {title}"
        results = self.client.search(q=query, type="track", limit=1)
        if results["tracks"]["items"]:
            return results["tracks"]["items"][0]
        return None

    def add_track(self, track: dict) -> Optional[str]:
        if not self._check_duplicate(track.artists[0].name, track.title):
            spotify_track = self.search_track(track.artists[0].name, track.title)
            if spotify_track:
                self._execute_with_retry(
                    f"Add track to Spotify ({spotify_track['id']})",
                    lambda: self.client.current_user_saved_tracks_add(
                        [spotify_track["id"]]
                    ),
                )
                return spotify_track["id"]
            else:
                logger.warning(
                    f"Track not found in Spotify: {track.artists[0].name} - {track.title}"
                )
                self.db_manager.add_undiscovered_track(
                    "spotify", track.artists[0].name, track.title
                )
        else:
            logger.info(
                f"Duplicate found in Spotify: {track.artists[0].name} - {track.title}"
            )
        return None

    def _check_duplicate(self, artist: str, title: str) -> bool:
        results = self.client.search(
            q=f"track:{title} artist:{artist}", type="track", limit=50
        )
        for item in results["tracks"]["items"]:
            if (
                item["name"].lower() == title.lower()
                and item["artists"][0]["name"].lower() == artist.lower()
            ):
                if self.client.current_user_saved_tracks_contains([item["id"]])[0]:
                    return True
        return False

    def remove_duplicates(self):
        offset = 0
        limit = 50
        tracks_seen = set()
        tracks_to_remove = []

        while True:
            results = self.client.current_user_saved_tracks(limit=limit, offset=offset)
            if len(results["items"]) == 0:
                break

            for item in results["items"]:
                track = item["track"]
                track_key = (track["name"].lower(), track["artists"][0]["name"].lower())

                if track_key in tracks_seen:
                    tracks_to_remove.append(track["id"])
                else:
                    tracks_seen.add(track_key)

            offset += limit

        if tracks_to_remove:
            for i in range(0, len(tracks_to_remove), 50):
                batch = tracks_to_remove[i : i + 50]
                self._execute_with_retry(
                    "Delete duplicate tracks batch in Spotify",
                    lambda batch_ids=batch: self.client.current_user_saved_tracks_delete(batch_ids),
                )
                logger.info(f"Removed {len(batch)} duplicate tracks from Spotify")

    def get_playlists(
        self,
        force_full_sync: bool,
        include_followed: bool = False,
    ) -> List[PlaylistSnapshot]:
        offset = 0
        limit = 50
        playlists: List[PlaylistSnapshot] = []

        while True:
            response = self._execute_with_retry(
                f"Fetch Spotify playlists offset={offset}",
                lambda off=offset: self.client.current_user_playlists(
                    limit=limit, offset=off
                ),
            )
            items = response.get("items", [])
            if not items:
                break

            for playlist in items:
                snapshot = self._build_playlist_snapshot(playlist, include_followed)
                if snapshot:
                    playlists.append(snapshot)

            offset += len(items)
            if not response.get("next"):
                break

        extra_ids_raw = os.getenv("SPOTIFY_EXTRA_PLAYLIST_IDS", "")
        for raw_id in extra_ids_raw.split(","):
            playlist_id = raw_id.strip()
            if not playlist_id:
                continue
            if any(p.playlist_id == playlist_id for p in playlists):
                continue
            try:
                playlist_data = self._execute_with_retry(
                    f"Fetch Spotify playlist {playlist_id}",
                    lambda pid=playlist_id: self.client.playlist(pid),
                )
            except SpotifyException as exc:
                logger.error(
                    "Не удалось получить дополнительный плейлист %s: %s",
                    playlist_id,
                    exc,
                )
                continue

            if not playlist_data:
                continue

            snapshot = self._build_playlist_snapshot(playlist_data, include_followed=True)
            if snapshot:
                playlists.append(snapshot)

        return playlists

    def get_favorite_albums(self) -> List[FavoriteAlbum]:
        favorites: List[FavoriteAlbum] = []
        offset = 0
        limit = 50
        while True:
            response = self._execute_with_retry(
                f"Fetch Spotify saved albums offset={offset}",
                lambda off=offset: self.client.current_user_saved_albums(
                    limit=limit, offset=off
                ),
            )
            items = response.get("items", [])
            if not items:
                break
            for item in items:
                album_data = item.get("album") or {}
                album_id = album_data.get("id")
                if not album_id:
                    continue
                artist_name = ", ".join(
                    artist.get("name")
                    for artist in album_data.get("artists", [])
                    if artist.get("name")
                ) or None
                favorites.append(
                    FavoriteAlbum(
                        service="spotify",
                        album_id=album_id,
                        name=album_data.get("name"),
                        artist=artist_name,
                        last_seen=_parse_datetime(item.get("added_at")),
                    )
                )
            offset += len(items)
            if not response.get("next"):
                break
        return favorites

    def ensure_album_in_library(self, album: FavoriteAlbum) -> Optional[FavoriteAlbum]:
        query_parts = []
        if album.name:
            query_parts.append(f"album:{album.name}")
        if album.artist:
            query_parts.append(f"artist:{album.artist}")
        query = " ".join(query_parts)
        if not query:
            logger.debug("Skipping Spotify album ensure: missing metadata for %s", album)
            return None

        search = self._execute_with_retry(
            f"Search Spotify album '{query}'",
            lambda: self.client.search(q=query, type="album", limit=5),
        )
        albums_data = (search or {}).get("albums", {})
        target_key = album_key(album)
        for candidate in albums_data.get("items", []):
            candidate_album = FavoriteAlbum(
                service="spotify",
                album_id=candidate.get("id"),
                name=candidate.get("name"),
                artist=", ".join(
                    artist.get("name")
                    for artist in candidate.get("artists", [])
                    if artist.get("name")
                ) or None,
                last_seen=_now_utc(),
            )
            if candidate_album.album_id is None:
                continue
            if target_key and album_key(candidate_album) != target_key:
                continue

            self._execute_with_retry(
                f"Add Spotify album {candidate_album.album_id}",
                lambda: self.client.current_user_saved_albums_add(
                    [candidate_album.album_id]
                ),
            )
            logger.info(
                "Добавлен альбом в Spotify: %s — %s",
                candidate_album.artist,
                candidate_album.name,
            )
            return candidate_album

        logger.warning(
            "Не удалось найти альбом в Spotify по запросу '%s'", query
        )
        return None

    def get_favorite_artists(self) -> List[FavoriteArtist]:
        favorites: List[FavoriteArtist] = []
        after: Optional[str] = None
        limit = 50
        while True:
            response = self._execute_with_retry(
                f"Fetch Spotify followed artists after={after}",
                lambda cursor=after: self.client.current_user_followed_artists(
                    limit=limit, after=cursor
                ),
            )
            artists_data = (response or {}).get("artists", {})
            items = artists_data.get("items", [])
            if not items:
                break
            for artist in items:
                artist_id = artist.get("id")
                if not artist_id:
                    continue
                favorites.append(
                    FavoriteArtist(
                        service="spotify",
                        artist_id=artist_id,
                        name=artist.get("name"),
                        last_seen=None,
                    )
                )
            after = (artists_data.get("cursors") or {}).get("after")
            if not after:
                break
        return favorites

    def ensure_artist_followed(self, artist: FavoriteArtist) -> Optional[FavoriteArtist]:
        query = artist.name
        if not query:
            logger.debug("Skipping Spotify artist ensure: missing name for %s", artist)
            return None

        search = self._execute_with_retry(
            f"Search Spotify artist '{query}'",
            lambda: self.client.search(q=query, type="artist", limit=5),
        )
        artists_data = (search or {}).get("artists", {})
        target_key = artist_key(artist)
        for candidate in artists_data.get("items", []):
            candidate_artist = FavoriteArtist(
                service="spotify",
                artist_id=candidate.get("id"),
                name=candidate.get("name"),
                last_seen=_now_utc(),
            )
            if candidate_artist.artist_id is None:
                continue
            if target_key and artist_key(candidate_artist) != target_key:
                continue

            self._execute_with_retry(
                f"Follow Spotify artist {candidate_artist.artist_id}",
                lambda: self.client.user_follow_artists(
                    [candidate_artist.artist_id]
                ),
            )
            logger.info("Добавлен исполнитель в Spotify: %s", candidate_artist.name)
            return candidate_artist

        logger.warning(
            "Не удалось найти исполнителя в Spotify по запросу '%s'",
            query,
        )
        return None


class MusicSynchronizer:
    def __init__(
        self,
        yandex_service: YandexMusic,
        spotify_service: SpotifyMusic,
        db_manager: DatabaseManager,
    ):
        self.yandex = yandex_service
        self.spotify = spotify_service
        self.db_manager = db_manager

    def sync_tracks(
        self,
        force_full_sync: bool = False,
        target: str = "yandex",
    ):
        current_time = _now_utc()

        if target in {"both", "spotify"}:
            logger.info("Синхронизация треков из Yandex в Spotify")
            yandex_tracks = self.yandex.get_tracks(force_full_sync)
            for track in yandex_tracks:
                spotify_id = self.spotify.add_track(track)
                if spotify_id:
                    self.db_manager.insert_or_update_track(
                        track.id, spotify_id, track.artists[0].name, track.title
                    )
                    logger.info(
                        "Добавлен трек в Spotify: %s - %s",
                        track.artists[0].name,
                        track.title,
                    )

            self.db_manager.update_last_sync_time("yandex", current_time)
        else:
            logger.info(
                "Пропуск синхронизации треков в Spotify (target=%s)",
                target,
            )

        if target in {"both", "yandex"}:
            logger.info("Синхронизация треков из Spotify в Yandex")
            spotify_tracks = self.spotify.get_tracks(force_full_sync)
            for item in spotify_tracks:
                track = item["track"]
                yandex_id = self.yandex.add_track(item)
                if yandex_id:
                    self.db_manager.insert_or_update_track(
                        yandex_id,
                        track["id"],
                        track["artists"][0]["name"],
                        track["name"],
                    )
                    logger.info(
                        "Добавлен трек в Yandex: %s - %s",
                        track["artists"][0]["name"],
                        track["name"],
                    )

            self.db_manager.update_last_sync_time("spotify", current_time)
        else:
            logger.info(
                "Пропуск синхронизации треков в Yandex (target=%s)",
                target,
            )

    def remove_duplicates(self):
        self.spotify.remove_duplicates()
        self.yandex.remove_duplicates()

    def _record_playlist_snapshots(
        self, service: str, playlists: Sequence[PlaylistSnapshot]
    ) -> None:
        playlist_ids: List[str] = []
        snapshot_time = _now_utc()
        for playlist in playlists:
            playlist_ids.append(playlist.playlist_id)
            playlist_pk = self.db_manager.upsert_playlist(
                service=service,
                playlist_id=playlist.playlist_id,
                name=playlist.name,
                owner=playlist.owner,
                last_synced=snapshot_time,
            )
            track_rows = []
            seen_track_ids = set()
            for track in playlist.tracks:
                if not track.track_id:
                    continue
                if track.track_id in seen_track_ids:
                    continue
                seen_track_ids.add(track.track_id)
                track_rows.append((track.track_id, track.position, track.added_at))
            self.db_manager.set_playlist_tracks(
                playlist_pk,
                service,
                track_rows,
            )

        self.db_manager.remove_playlists_not_in(service, playlist_ids)

    def _sync_spotify_playlists_to_yandex(
        self,
        spotify_playlists: Sequence[PlaylistSnapshot],
        existing_yandex: Sequence[PlaylistSnapshot],
    ) -> None:
        existing_map = {
            normalize_text(playlist.name or playlist.playlist_id): playlist
            for playlist in existing_yandex
        }

        for playlist in spotify_playlists:
            if not playlist.is_owned:
                continue
            if not playlist.name:
                continue

            normalized = normalize_text(playlist.name)
            matched = existing_map.get(normalized)

            try:
                yandex_playlist = self.yandex.ensure_playlist(
                    playlist.name,
                    existing_playlist_id=matched.playlist_id if matched else None,
                )
            except Exception as exc:
                logger.error(
                    "Не удалось подготовить плейлист '%s' в Yandex: %s",
                    playlist.name,
                    exc,
                )
                continue

            if not yandex_playlist:
                logger.warning(
                    "Yandex API не вернул плейлист '%s' после подготовки",
                    playlist.name,
                )
                continue

            tracks_attr = getattr(yandex_playlist, "tracks", []) or []
            existing_ids = {
                str(getattr(track_obj, "track_id", ""))
                for track_obj in tracks_attr
                if getattr(track_obj, "track_id", None)
            }

            additions = 0
            for item in playlist.tracks:
                if not item.track_id:
                    continue

                resolved = self.yandex.resolve_track_for_playlist(
                    item.track_id,
                    item.title,
                    item.artist,
                )
                if not resolved:
                    logger.warning(
                        "Пропускаю трек при синхронизации плейлиста '%s': %s — %s",
                        playlist.name,
                        item.artist,
                        item.title,
                    )
                    continue

                track_part, album_part, composite = resolved
                compare_id = composite or f"{track_part}:{album_part}"
                if compare_id in existing_ids:
                    continue

                try:
                    updated_playlist = self.yandex.insert_track_into_playlist(
                        yandex_playlist,
                        track_part,
                        album_part,
                        at=len(getattr(yandex_playlist, "tracks", []) or []),
                    )
                except Exception as exc:
                    logger.error(
                        "Ошибка добавления трека %s — %s в плейлист '%s': %s",
                        item.artist,
                        item.title,
                        playlist.name,
                        exc,
                    )
                    continue

                if updated_playlist:
                    yandex_playlist = updated_playlist

                tracks_attr = getattr(yandex_playlist, "tracks", []) or []
                existing_ids = {
                    str(getattr(track_obj, "track_id", ""))
                    for track_obj in tracks_attr
                    if getattr(track_obj, "track_id", None)
                }
                additions += 1

            if additions:
                logger.info(
                    "Добавлено %s треков в плейлист Yandex '%s'",
                    additions,
                    playlist.name,
                )

    def sync_playlists(
        self, force_full_sync: bool, include_followed_spotify: bool
    ) -> None:
        yandex_playlists = self.yandex.get_playlists(force_full_sync)
        spotify_playlists = self.spotify.get_playlists(
            force_full_sync, include_followed=include_followed_spotify
        )

        logger.info(
            "Получено %s плейлистов из Yandex и %s из Spotify",
            len(yandex_playlists),
            len(spotify_playlists),
        )

        self._sync_spotify_playlists_to_yandex(spotify_playlists, yandex_playlists)

        updated_yandex = self.yandex.get_playlists(force_full_sync)
        self._record_playlist_snapshots("yandex", updated_yandex)
        self._record_playlist_snapshots("spotify", spotify_playlists)

    def _store_favorite_albums(
        self, service: str, albums: Sequence[FavoriteAlbum]
    ) -> None:
        ids: List[str] = []
        for album in albums:
            if not album.album_id:
                continue
            ids.append(album.album_id)
            self.db_manager.upsert_favorite_album(
                service,
                album.album_id,
                album.name,
                album.artist,
                album.last_seen,
            )
        self.db_manager.remove_favorite_albums_not_in(service, ids)

    def _store_favorite_artists(
        self, service: str, artists: Sequence[FavoriteArtist]
    ) -> None:
        ids: List[str] = []
        for artist in artists:
            if not artist.artist_id:
                continue
            ids.append(artist.artist_id)
            self.db_manager.upsert_favorite_artist(
                service,
                artist.artist_id,
                artist.name,
                artist.last_seen,
            )
        self.db_manager.remove_favorite_artists_not_in(service, ids)

    def sync_favorite_albums(self, readonly: bool, target: str) -> None:
        yandex_albums = self.yandex.get_favorite_albums()
        spotify_albums = self.spotify.get_favorite_albums()

        logger.info(
            "Избранные альбомы — Yandex: %s, Spotify: %s",
            len(yandex_albums),
            len(spotify_albums),
        )

        self._store_favorite_albums("yandex", yandex_albums)
        self._store_favorite_albums("spotify", spotify_albums)

        diff = match_entities(
            yandex_albums,
            spotify_albums,
            album_key,
            album_key,
        )

        for yandex_album, spotify_album in diff.matched_pairs:
            normalized = album_key(yandex_album)
            if yandex_album.album_id and spotify_album.album_id:
                self.db_manager.link_album_ids(
                    yandex_album.album_id,
                    spotify_album.album_id,
                    normalized if normalized else None,
                )

        if readonly:
            logger.info("Режим только записи снимков включен, изменения в сервисах не применяются")
            return

        if target in {"both", "spotify"}:
            for album in diff.left_only:
                logger.info(
                    "Добавление альбома в Spotify: %s — %s",
                    album.artist,
                    album.name,
                )
                added = self.spotify.ensure_album_in_library(album)
                if added and album.album_id and added.album_id:
                    self.db_manager.link_album_ids(
                        album.album_id,
                        added.album_id,
                        album_key(album),
                    )

        if target in {"both", "yandex"}:
            for album in diff.right_only:
                logger.info(
                    "Добавление альбома в Yandex: %s — %s",
                    album.artist,
                    album.name,
                )
                added = self.yandex.ensure_album_in_library(album)
                if added and album.album_id and added.album_id:
                    self.db_manager.link_album_ids(
                        added.album_id,
                        album.album_id,
                        album_key(album),
                    )

    def sync_favorite_artists(self, readonly: bool, target: str) -> None:
        yandex_artists = self.yandex.get_favorite_artists()
        spotify_artists = self.spotify.get_favorite_artists()

        logger.info(
            "Избранные исполнители — Yandex: %s, Spotify: %s",
            len(yandex_artists),
            len(spotify_artists),
        )

        self._store_favorite_artists("yandex", yandex_artists)
        self._store_favorite_artists("spotify", spotify_artists)

        diff = match_entities(
            yandex_artists,
            spotify_artists,
            artist_key,
            artist_key,
        )

        for yandex_artist, spotify_artist in diff.matched_pairs:
            normalized = artist_key(yandex_artist)
            if yandex_artist.artist_id and spotify_artist.artist_id:
                self.db_manager.link_artist_ids(
                    yandex_artist.artist_id,
                    spotify_artist.artist_id,
                    normalized if normalized else None,
                )

        if readonly:
            logger.info("Режим только записи снимков включен, изменения в сервисах не применяются")
            return

        if target in {"both", "spotify"}:
            for artist in diff.left_only:
                logger.info("Добавление исполнителя в Spotify: %s", artist.name)
                added = self.spotify.ensure_artist_followed(artist)
                if added and artist.artist_id and added.artist_id:
                    self.db_manager.link_artist_ids(
                        artist.artist_id,
                        added.artist_id,
                        artist_key(artist),
                    )

        if target in {"both", "yandex"}:
            for artist in diff.right_only:
                logger.info("Добавление исполнителя в Yandex: %s", artist.name)
                added = self.yandex.ensure_artist_followed(artist)
                if added and artist.artist_id and added.artist_id:
                    self.db_manager.link_artist_ids(
                        added.artist_id,
                        artist.artist_id,
                        artist_key(artist),
                    )


def parse_arguments():
    parser = argparse.ArgumentParser(description="Music Synchronizer")
    parser.add_argument(
        "--sleep",
        type=int,
        default=60,
        help="Time to sleep between syncs in seconds (default: 60)",
    )
    parser.add_argument(
        "--force-full-sync",
        action="store_true",
        help="Force a full sync of all tracks",
    )
    parser.add_argument(
        "--track-sync-target",
        choices=["both", "spotify", "yandex"],
        default="yandex",
        help="Select which platform receives missing tracks when syncing libraries",
    )
    parser.add_argument(
        "--remove-duplicates",
        action="store_true",
        help="Remove duplicate tracks after the first sync",
    )
    parser.add_argument(
        "--sync-playlists",
        action="store_true",
        help="Collect playlists from both services and store snapshots in the database",
    )
    parser.add_argument(
        "--include-followed-playlists",
        action="store_true",
        help="Include followed Spotify playlists when syncing playlist snapshots",
    )
    parser.add_argument(
        "--sync-favorite-albums",
        action="store_true",
        help="Synchronize favorite albums between services",
    )
    parser.add_argument(
        "--sync-favorite-artists",
        action="store_true",
        help="Synchronize favorite artists between services",
    )
    parser.add_argument(
        "--favorite-sync-readonly",
        action="store_true",
        help="Only record favorite snapshots without modifying Spotify or Yandex libraries",
    )
    parser.add_argument(
        "--favorite-sync-target",
        choices=["both", "spotify", "yandex"],
        default="yandex",
        help="Select which platform receives missing favorites when syncing",
    )
    return parser.parse_args()

def main():
    args = parse_arguments()
    logger.info(f"Запущен скрипт с параметрами: {args}")
    load_dotenv()
    
    # Проверяем и исправляем кэш файл Spotify перед началом работы
    check_and_fix_spotify_cache()
    
    yandex_token = os.getenv("YANDEX_TOKEN")
    if not yandex_token:
        logger.error("YANDEX_TOKEN не найден в файле .env")
        return

    # Параметры подключения к PostgreSQL
    db_params = {
        "dbname": os.getenv("POSTGRES_DB", "music_sync"),
        "user": os.getenv("POSTGRES_USER"),
        "password": os.getenv("POSTGRES_PASSWORD"),
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": os.getenv("POSTGRES_PORT", "5432")
    }

    db_manager = DatabaseManager(db_params)
    yandex_service = YandexMusic(db_manager, yandex_token)
    spotify_service = SpotifyMusic(db_manager)
    synchronizer = MusicSynchronizer(yandex_service, spotify_service, db_manager)

    try:
        first_run = True
        while True:
            try:
                logger.info("Синхронизация треков...")
                synchronizer.sync_tracks(
                    force_full_sync=args.force_full_sync,
                    target=args.track_sync_target,
                )

                if args.sync_playlists:
                    logger.info("Сбор снимков плейлистов...")
                    synchronizer.sync_playlists(
                        force_full_sync=args.force_full_sync,
                        include_followed_spotify=args.include_followed_playlists,
                    )

                if args.sync_favorite_albums:
                    logger.info("Синхронизация избранных альбомов...")
                    synchronizer.sync_favorite_albums(
                        readonly=args.favorite_sync_readonly,
                        target=args.favorite_sync_target,
                    )

                if args.sync_favorite_artists:
                    logger.info("Синхронизация избранных исполнителей...")
                    synchronizer.sync_favorite_artists(
                        readonly=args.favorite_sync_readonly,
                        target=args.favorite_sync_target,
                    )
                
                if first_run and args.remove_duplicates:
                    logger.info("Удаление дубликатов...")
                    synchronizer.remove_duplicates()
                    first_run = False
                
                logger.info(f"Ожидание {args.sleep} секунд...")
                time.sleep(args.sleep)
            except Exception:
                logger.exception("Произошла ошибка во время синхронизации")
                logger.info("Ожидание 60 секунд перед повторной попыткой...")
                time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Процесс синхронизации прерван пользователем")
    finally:
        db_manager.close()


if __name__ == "__main__":
    main()
