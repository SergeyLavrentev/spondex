import types
from unittest.mock import MagicMock

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
