import types
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.main import YandexMusic


def make_yandex_music() -> YandexMusic:
    instance = object.__new__(YandexMusic)
    instance.db_manager = MagicMock()
    instance.client = MagicMock()
    instance._max_attempts = 1
    instance._base_retry_delay = 0.0
    instance._execute_with_retry = types.MethodType(
        lambda self, description, func: func(), instance
    )
    return instance


def build_playlist(
    playlist_id: str,
    kind=None,
    owner_uid=None,
    tracks=None,
    revision=1,
    title="Test",
):
    owner = SimpleNamespace(uid=owner_uid) if owner_uid is not None else None
    playlist_tracks = tracks if tracks is not None else []
    return SimpleNamespace(
        playlist_id=playlist_id,
        kind=kind,
        owner=owner,
        tracks=playlist_tracks,
        revision=revision,
        title=title,
    )


def simple_track(title: str, artist: str):
    track_obj = SimpleNamespace(
        title=title,
        artists=[SimpleNamespace(name=artist)],
    )
    playlist_track = SimpleNamespace(
        track=track_obj,
        track_id=f"track:{title}",
        timestamp="2024-01-01T00:00:00+00:00",
    )
    return playlist_track


def test_refresh_playlist_object_resolves_owner_and_kind():
    yandex = make_yandex_music()
    refreshed_playlist = build_playlist(
        playlist_id="33646885:1019",
        kind=1019,
        owner_uid=33646885,
    )
    yandex.client.users_playlists.return_value = refreshed_playlist

    result = yandex._refresh_playlist_object(
        build_playlist(playlist_id="33646885:1019", kind=None, owner_uid=33646885)
    )

    yandex.client.users_playlists.assert_called_once_with(1019, user_id=33646885)
    assert result is refreshed_playlist


def test_make_space_in_playlist_deletes_oldest_and_refreshes():
    yandex = make_yandex_music()

    initial_playlist = build_playlist(
        playlist_id="33646885:1019",
        kind=1019,
        owner_uid=33646885,
        tracks=[simple_track("Old Song", "Artist A")],
        revision=42,
        title="Fitness",
    )
    refreshed_after_delete = build_playlist(
        playlist_id="33646885:1019",
        kind=1019,
        owner_uid=33646885,
        tracks=[],
        revision=43,
        title="Fitness",
    )

    yandex.client.users_playlists.side_effect = [initial_playlist, refreshed_after_delete]
    yandex.client.users_playlists_delete_track.return_value = initial_playlist

    result = yandex._make_space_in_playlist(initial_playlist)

    yandex.client.users_playlists_delete_track.assert_called_once_with(
        1019, from_=0, to=1, revision=42
    )
    assert yandex.client.users_playlists.call_count == 2
    assert result is refreshed_after_delete