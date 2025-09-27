from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class PlaylistTrack:
    track_id: str
    title: Optional[str] = None
    artist: Optional[str] = None
    position: Optional[int] = None
    added_at: Optional[datetime] = None


@dataclass
class PlaylistSnapshot:
    service: str
    playlist_id: str
    name: Optional[str]
    owner: Optional[str]
    tracks: List[PlaylistTrack] = field(default_factory=list)
    last_modified: Optional[datetime] = None
    is_owned: bool = True


@dataclass
class FavoriteAlbum:
    service: str
    album_id: str
    name: Optional[str]
    artist: Optional[str]
    last_seen: Optional[datetime] = None


@dataclass
class FavoriteArtist:
    service: str
    artist_id: str
    name: Optional[str]
    last_seen: Optional[datetime] = None
