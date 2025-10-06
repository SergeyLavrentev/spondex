from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple, TypeVar

from models import FavoriteAlbum, FavoriteArtist, PlaylistTrack

_T = TypeVar("_T", FavoriteAlbum, FavoriteArtist)


_normalize_pattern = re.compile(r"[^a-z0-9]+", re.IGNORECASE)


def normalize_text(value: Optional[str]) -> str:
    if not value:
        return ""
    lowered = value.lower()
    simplified = _normalize_pattern.sub(" ", lowered)
    return re.sub(r"\s+", " ", simplified).strip()


def album_key(album: FavoriteAlbum) -> str:
    return "::".join(filter(None, (normalize_text(album.name), normalize_text(album.artist))))


def artist_key(artist: FavoriteArtist) -> str:
    return normalize_text(artist.name)


def track_key(track: PlaylistTrack) -> str:
    return normalize_text(track.title)


@dataclass
class EntityDiff:
    matched_pairs: List[Tuple[_T, _T]]
    left_only: List[_T]
    right_only: List[_T]


def match_entities(
    left: Sequence[_T],
    right: Sequence[_T],
    left_key_func,
    right_key_func,
) -> EntityDiff:
    left_buckets: Dict[str, List[_T]] = defaultdict(list)
    for entity in left:
        left_buckets[left_key_func(entity)].append(entity)

    right_buckets: Dict[str, List[_T]] = defaultdict(list)
    for entity in right:
        right_buckets[right_key_func(entity)].append(entity)

    matches: List[Tuple[_T, _T]] = []
    left_only: List[_T] = []

    for key, left_entities in left_buckets.items():
        right_entities = right_buckets.get(key)
        if right_entities:
            for pair in zip(left_entities, right_entities):
                matches.append(pair)
            if len(left_entities) > len(right_entities):
                left_only.extend(left_entities[len(right_entities):])
            right_count = len(right_entities)
            if right_count > len(left_entities):
                right_buckets[key] = right_entities[len(left_entities):]
            else:
                right_buckets.pop(key, None)
        else:
            left_only.extend(left_entities)

    right_only: List[_T] = []
    for remaining in right_buckets.values():
        right_only.extend(remaining)

    return EntityDiff(matched_pairs=matches, left_only=left_only, right_only=right_only)