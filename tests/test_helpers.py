import sys
from pathlib import Path

import pytest

# Ensure src directory is on sys.path for direct module imports
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import main  # noqa: E402
import sync_helpers  # noqa: E402
from models import FavoriteAlbum, FavoriteArtist  # noqa: E402


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2024-08-05T12:34:56Z", (2024, 8, 5, 12, 34, 56, 0, 0)),
        ("2024-08-05T12:34:56+03:00", (2024, 8, 5, 12, 34, 56, 3, 0)),
        ("2024-08-05 12:34:56", (2024, 8, 5, 12, 34, 56, None, None)),
    ],
)
def test_parse_datetime_valid_variants(raw, expected):
    dt = main._parse_datetime(raw)
    assert dt is not None
    year, month, day, hour, minute, second, tz_hour, tz_minute = expected
    assert (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second) == (
        year,
        month,
        day,
        hour,
        minute,
        second,
    )
    if tz_hour is None:
        assert dt.tzinfo is None
    else:
        offset = dt.utcoffset()
        assert offset is not None
        offset_minutes = offset.total_seconds() / 60
        assert offset_minutes == pytest.approx(tz_hour * 60 + tz_minute)


def test_parse_datetime_invalid():
    assert main._parse_datetime("not-a-date") is None
    assert main._parse_datetime("") is None


class DummyArtist:
    def __init__(self, name):
        self.name = name


def test_join_artist_names_basic():
    artists = [DummyArtist("Alice"), DummyArtist("Bob")]
    assert main._join_artist_names(artists) == "Alice, Bob"


def test_join_artist_names_filters_empty():
    artists = [DummyArtist(None), DummyArtist(" "), DummyArtist("Charlie")]
    assert main._join_artist_names(artists) == "Charlie"


def test_join_artist_names_all_empty():
    artists = [DummyArtist(None), DummyArtist("")]
    assert main._join_artist_names(artists) is None
    assert main._join_artist_names(None) is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Hello, World!", "hello world"),
        ("  Multiple   Spaces  ", "multiple spaces"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_text(text, expected):
    assert sync_helpers.normalize_text(text) == expected


def test_album_key_combines_fields():
    album = FavoriteAlbum(
        service="yandex",
        album_id="1",
        name=" The Wall ",
        artist="Pink Floyd",
    )
    assert sync_helpers.album_key(album) == "the wall::pink floyd"


def test_artist_key():
    artist = FavoriteArtist(
        service="spotify",
        artist_id="42",
        name="Daft Punk",
    )
    assert sync_helpers.artist_key(artist) == "daft punk"


def test_match_entities_balances_counts():
    left = [
        FavoriteAlbum("yandex", "y1", "Album", "Artist"),
        FavoriteAlbum("yandex", "y2", "Album", "Artist"),
    ]
    right = [FavoriteAlbum("spotify", "s1", "Album", "Artist")]

    diff = sync_helpers.match_entities(left, right, sync_helpers.album_key, sync_helpers.album_key)

    assert len(diff.matched_pairs) == 1
    assert len(diff.left_only) == 1
    assert len(diff.right_only) == 0
    matched_left, matched_right = diff.matched_pairs[0]
    assert matched_left.album_id == "y1"
    assert matched_right.album_id == "s1"


def test_match_entities_right_excess():
    left = [FavoriteArtist("yandex", "y1", "Artist", None)]
    right = [
        FavoriteArtist("spotify", "s1", "Artist", None),
        FavoriteArtist("spotify", "s2", "Artist", None),
    ]

    diff = sync_helpers.match_entities(left, right, sync_helpers.artist_key, sync_helpers.artist_key)

    assert len(diff.matched_pairs) == 1
    assert diff.left_only == []
    assert len(diff.right_only) == 1
    assert diff.right_only[0].artist_id == "s2"
