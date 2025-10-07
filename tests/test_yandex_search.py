import types
from unittest.mock import MagicMock

from typing import Any

from src.main import YandexMusic


def make_yandex_music() -> YandexMusic:
    instance = object.__new__(YandexMusic)
    instance.client = MagicMock()
    instance._max_attempts = 1
    instance._base_retry_delay = 0.0
    instance._execute_with_retry = types.MethodType(
        lambda self, description, func: func(),
        instance,
    )
    return instance


class DummyAlbum:
    def __init__(self, identifier: Any):
        self.id = identifier

    def to_dict(self, for_request: bool = False) -> dict:
        return {"id": str(self.id)}


class DummyTrack:
    def __init__(self, identifier: Any, album_identifier: Any):
        self.id = identifier
        self.track_id = identifier
        self.albums = [DummyAlbum(album_identifier)]
        self.title = "Dummy"
        self.artists = [types.SimpleNamespace(name="Dummy Artist")]

    def to_dict(self, for_request: bool = False) -> dict:
        return {
            "id": str(self.id),
            "track_id": str(self.track_id),
            "albums": [album.to_dict() for album in self.albums],
            "artists": [{"name": artist.name} for artist in self.artists],
        }


class DummyBest:
    def __init__(self, payload: Any):
        self.type = "track"
        self.result = payload

    def to_dict(self, for_request: bool = False) -> dict:
        return {"type": self.type, "result": self.result.to_dict()}


class DummyTracksSection:
    def __init__(self, results: Any):
        self.results = results

    def to_dict(self, for_request: bool = False) -> dict:
        return {"results": [item.to_dict() for item in self.results]}


class DummySearch:
    def __init__(self, best: Any = None, tracks: Any = None):
        self.best = best
        self.tracks = tracks

    def to_dict(self, for_request: bool = False) -> dict:
        data: dict = {}
        if self.best is not None:
            data["best"] = self.best.to_dict()
        if self.tracks is not None:
            data["tracks"] = self.tracks.to_dict()
        return data


def test_search_track_falls_back_to_track_results_when_best_not_track():
    yandex = make_yandex_music()
    track_payload = {"id": "123:456", "albums": [{"id": "456"}]}

    yandex.client.search.return_value = {
        "best": {"type": "album", "result": {"id": "789"}},
        "tracks": {"results": [track_payload]},
    }

    result = yandex.search_track("Artist", "Song")

    assert result == track_payload
    yandex.client.search.assert_called_once_with("Artist Song")


def test_search_track_handles_tracks_section_list():
    yandex = make_yandex_music()
    track_payload = {"id": "42:24", "albums": [{"id": "24"}]}

    yandex.client.search.return_value = {"tracks": [track_payload]}

    result = yandex.search_track("Another", "Tune")

    assert result == track_payload


def test_search_track_handles_search_object_with_best_track():
    yandex = make_yandex_music()
    track_obj = DummyTrack(identifier=777, album_identifier=555)
    yandex.client.search.return_value = DummySearch(best=DummyBest(track_obj))

    result = yandex.search_track("Object", "Best")

    assert result["id"] == "777"
    assert result["track_id"] == "777"
    assert result["albums"][0]["id"] == "555"


def test_search_track_handles_search_object_tracks_payload():
    yandex = make_yandex_music()
    track_obj = DummyTrack(identifier=888, album_identifier=999)
    tracks_section = DummyTracksSection(results=[track_obj])
    yandex.client.search.return_value = DummySearch(tracks=tracks_section)

    result = yandex.search_track("Object", "Tracks")

    assert result["id"] == "888"
    assert result["albums"][0]["id"] == "999"
