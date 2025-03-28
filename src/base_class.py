from typing import List, Optional
from database_manager import DatabaseManager


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