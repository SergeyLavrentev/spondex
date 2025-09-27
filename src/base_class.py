from typing import Iterable, List, Optional
from database_manager import DatabaseManager
from models import FavoriteAlbum, FavoriteArtist, PlaylistSnapshot


class MusicService:
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    def get_tracks(self, force_full_sync: bool) -> List[dict]:
        raise NotImplementedError("Subclasses must implement this method")

    def search_track(self, artist: str, title: str) -> Optional[dict]:
        raise NotImplementedError("Subclasses must implement this method")

    def add_track(self, track: dict) -> Optional[str]:
        raise NotImplementedError("Subclasses must implement this method")

    def remove_duplicates(self):
        raise NotImplementedError("Subclasses must implement this method")

    # --- Optional advanced features -------------------------------------

    def get_playlists(self, force_full_sync: bool) -> List[PlaylistSnapshot]:
        return []

    def create_or_update_playlist(
        self, playlist: PlaylistSnapshot, target_tracks: Iterable[str]
    ) -> None:
        raise NotImplementedError("Subclasses must implement this method")

    def get_favorite_albums(self) -> List[FavoriteAlbum]:
        return []

    def ensure_album_in_library(self, album: FavoriteAlbum) -> Optional[FavoriteAlbum]:
        raise NotImplementedError("Subclasses must implement this method")

    def get_favorite_artists(self) -> List[FavoriteArtist]:
        return []

    def ensure_artist_followed(self, artist: FavoriteArtist) -> Optional[FavoriteArtist]:
        raise NotImplementedError("Subclasses must implement this method")