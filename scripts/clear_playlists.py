#!/usr/bin/env python3
"""Utility script to clear playlists from Yandex Music and/or Spotify.

The script supports dry-run confirmation and selective service targeting.
Use with extreme caution: removing playlists is irreversible.
"""

from __future__ import annotations

import argparse
import logging
import os
from typing import Any, Iterable, List, Sequence

from dotenv import load_dotenv

# Lazy imports for optional services
try:
    from yandex_music import Client as YandexClient  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    YandexClient = None  # type: ignore

try:
    import spotipy  # type: ignore
    from spotipy.oauth2 import SpotifyOAuth  # type: ignore
    from spotipy.exceptions import SpotifyException  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    spotipy = None  # type: ignore
    SpotifyOAuth = None  # type: ignore
    SpotifyException = Exception  # type: ignore

logger = logging.getLogger("clear_playlists")
SPOTIFY_SCOPE = (
    "playlist-read-private "
    "playlist-read-collaborative "
    "playlist-modify-private "
    "playlist-modify-public"
)


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s - %(levelname)s - %(message)s")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Delete playlists on Yandex Music and/or Spotify"
    )
    parser.add_argument(
        "--yandex",
        action="store_true",
        help="Target Yandex Music playlists",
    )
    parser.add_argument(
        "--spotify",
        action="store_true",
        help="Target Spotify playlists",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Execute without interactive confirmation",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only show what would be deleted without removing anything",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--skip-followed",
        action="store_true",
        help="Spotify: keep playlists you do not own (stop at unfollow stage)",
    )
    return parser.parse_args()


def iter_chunks(items: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for idx in range(0, len(items), size):
        yield items[idx : idx + size]


def clear_yandex_playlists(dry_run: bool, confirm: bool) -> None:
    if YandexClient is None:
        logger.error("yandex-music dependency is missing. Install it before running.")
        raise SystemExit(1)

    token = os.getenv("YANDEX_TOKEN")
    if not token:
        logger.error("Environment variable YANDEX_TOKEN is missing. Aborting Yandex cleanup.")
        return

    logger.info("Connecting to Yandex Music...")
    client = YandexClient(token=token).init()
    me = client.me.account
    my_uid = me.uid

    logger.debug("Fetching user playlists...")
    playlists = client.users_playlists_list()
    owned_playlists = [pl for pl in playlists if getattr(pl, "owner", None) and pl.owner.uid == my_uid]

    if not owned_playlists:
        logger.info("Yandex Music: no user-owned playlists found. Nothing to remove.")
        return

    logger.info("Yandex Music: %d owned playlists detected.", len(owned_playlists))
    for pl in owned_playlists:
        logger.debug("  - %s (kind=%s)", pl.title, pl.kind)

    if dry_run:
        logger.info("Dry-run enabled, skipping actual deletion for Yandex Music.")
        return

    if not confirm:
        logger.warning("Add --yes flag to confirm Yandex playlist deletion.")
        return

    for pl in owned_playlists:
        logger.debug("Deleting Yandex playlist '%s' (kind=%s)...", pl.title, pl.kind)
        client.users_playlists_delete(pl.kind, my_uid)

    logger.info("Yandex Music: removed %d playlists.", len(owned_playlists))


def fetch_spotify_playlists(sp_client: Any) -> List[dict]:
    playlists: List[dict] = []
    results = sp_client.current_user_playlists(limit=50)
    while True:
        playlists.extend(results["items"])
        if results["next"]:
            results = sp_client.next(results)
        else:
            break
    return playlists


def clear_spotify_playlists(dry_run: bool, confirm: bool, skip_followed: bool) -> None:
    if spotipy is None or SpotifyOAuth is None:
        logger.error("spotipy dependency is missing. Install it before running.")
        raise SystemExit(1)

    client_id = os.getenv("SPOTIPY_CLIENT_ID")
    client_secret = os.getenv("SPOTIPY_CLIENT_SECRET")
    redirect_uri = os.getenv("SPOTIPY_REDIRECT_URI")

    if not all([client_id, client_secret, redirect_uri]):
        logger.error(
            "Spotify credentials missing (require SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET, SPOTIPY_REDIRECT_URI)."
        )
        return

    logger.info("Authenticating with Spotify (may open browser if scopes changed)...")
    auth_manager = SpotifyOAuth(
        scope=SPOTIFY_SCOPE,
        cache_path="./.cache",
        open_browser=True,
    )
    sp = spotipy.Spotify(auth_manager=auth_manager)
    profile = sp.current_user()
    user_id = profile["id"]

    logger.debug("Fetching user playlists from Spotify...")
    playlists = fetch_spotify_playlists(sp)

    if skip_followed:
        owned = [pl for pl in playlists if pl["owner"]["id"] == user_id]
        removed_targets = owned
        skipped = [pl for pl in playlists if pl not in owned]
    else:
        removed_targets = playlists
        skipped = []

    if not removed_targets:
        logger.info("Spotify: no playlists match deletion criteria. Nothing to remove.")
        if skipped:
            logger.info("Spotify: %d followed playlists were skipped due to --skip-followed.", len(skipped))
        return

    logger.info(
        "Spotify: %d playlists scheduled for removal%s.",
        len(removed_targets),
        " (owned only)" if skip_followed else "",
    )
    for pl in removed_targets:
        owner_tag = "(owned)" if pl["owner"]["id"] == user_id else f"(owner: {pl['owner']['id']})"
        logger.debug("  - %s %s", pl["name"], owner_tag)

    if skipped:
        logger.info("Spotify: %d playlists skipped (not owned and --skip-followed enabled).", len(skipped))

    if dry_run:
        logger.info("Dry-run enabled, skipping Spotify unfollow/delete.")
        return

    if not confirm:
        logger.warning("Add --yes flag to confirm Spotify playlist unfollow/delete.")
        return

    failures = 0
    for pl in removed_targets:
        try:
            logger.debug("Removing Spotify playlist '%s' (%s)...", pl["name"], pl["id"])
            sp.current_user_unfollow_playlist(pl["id"])
        except SpotifyException as exc:  # pragma: no cover - network path
            failures += 1
            logger.error("Failed to remove playlist %s: %s", pl["name"], exc)

    successes = len(removed_targets) - failures
    logger.info("Spotify: successfully removed %d playlists; %d failures.", successes, failures)


def main() -> None:
    args = parse_args()
    configure_logging(args.verbose)
    load_dotenv(".env")

    targets: List[str] = []
    if args.yandex:
        targets.append("yandex")
    if args.spotify:
        targets.append("spotify")
    if not targets:
        targets = ["yandex", "spotify"]

    logger.info("Selected services: %s", ", ".join(targets))

    if "yandex" in targets:
        clear_yandex_playlists(dry_run=args.dry_run, confirm=args.yes)

    if "spotify" in targets:
        clear_spotify_playlists(
            dry_run=args.dry_run,
            confirm=args.yes,
            skip_followed=args.skip_followed,
        )


if __name__ == "__main__":
    main()
