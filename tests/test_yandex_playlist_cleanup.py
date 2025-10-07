import types
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.main import YandexMusic
from yandex_music.exceptions import YandexMusicError


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


def test_clear_playlist_tracks_removes_all_tracks():
    yandex = make_yandex_music()

    initial_playlist = build_playlist(
        playlist_id="33646885:1019",
        kind=1019,
        owner_uid=33646885,
        tracks=[simple_track("Song 1", "Artist"), simple_track("Song 2", "Artist")],
        revision=7,
        title="Workout",
    )
    cleared_playlist = build_playlist(
        playlist_id="33646885:1019",
        kind=1019,
        owner_uid=33646885,
        tracks=[],
        revision=8,
        title="Workout",
    )

    refresh_mock = MagicMock(return_value=initial_playlist)
    yandex._refresh_playlist_object = refresh_mock
    yandex.client.users_playlists_delete_track.return_value = cleared_playlist

    result = yandex._clear_playlist_tracks(initial_playlist)

    refresh_mock.assert_called_once_with(initial_playlist)
    yandex.client.users_playlists_delete_track.assert_called_once_with(
        1019, from_=0, to=2, revision=7
    )
    assert result is cleared_playlist


def test_clear_playlist_tracks_handles_wrong_revision_retry():
    yandex = make_yandex_music()

    initial_playlist = build_playlist(
        playlist_id="33646885:1019",
        kind=1019,
        owner_uid=33646885,
        tracks=[simple_track("Song 1", "Artist")],
        revision=10,
        title="Focus",
    )
    refreshed_playlist = build_playlist(
        playlist_id="33646885:1019",
        kind=1019,
        owner_uid=33646885,
        tracks=[simple_track("Song 1", "Artist")],
        revision=11,
        title="Focus",
    )
    cleared_playlist = build_playlist(
        playlist_id="33646885:1019",
        kind=1019,
        owner_uid=33646885,
        tracks=[],
        revision=12,
        title="Focus",
    )

    error = YandexMusicError("wrong-revision")
    error.errors = [{"name": "wrong-revision"}]

    refresh_mock = MagicMock(side_effect=[initial_playlist, refreshed_playlist])
    yandex._refresh_playlist_object = refresh_mock
    yandex.client.users_playlists_delete_track.side_effect = [error, cleared_playlist]

    result = yandex._clear_playlist_tracks(initial_playlist)

    assert refresh_mock.call_count == 2
    assert yandex.client.users_playlists_delete_track.call_count == 2
    first_call = yandex.client.users_playlists_delete_track.call_args_list[0]
    second_call = yandex.client.users_playlists_delete_track.call_args_list[1]
    assert first_call.kwargs == {"from_": 0, "to": 1, "revision": 10}
    assert first_call.args[0] == 1019
    assert second_call.kwargs == {"from_": 0, "to": 1, "revision": 11}
    assert second_call.args[0] == 1019
    assert result is cleared_playlist