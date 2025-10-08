#!/usr/bin/env python3
"""Utility script to wipe all liked tracks from Yandex Music.

Requires YANDEX_TOKEN to be set in .env. Use with caution: the removal
is irreversible unless you re-import the tracks manually.
"""

from __future__ import annotations

import argparse
import importlib
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, TYPE_CHECKING


if TYPE_CHECKING:  # pragma: no cover - import only for type hints
    from yandex_music import Client as YandexClient


def _running_in_virtualenv() -> bool:
    base_prefix = getattr(sys, "base_prefix", sys.prefix)
    real_prefix = getattr(sys, "real_prefix", None)
    return (
        sys.prefix != base_prefix
        or real_prefix is not None
        or "VIRTUAL_ENV" in os.environ
    )


def _ensure_runtime_python() -> None:
    runtime_root = Path(__file__).resolve().parent.parent / ".venv-runtime"
    runtime_python = runtime_root / "bin" / "python"

    if _running_in_virtualenv():
        return

    if os.environ.get("SPONDEX_RUNTIME_ACTIVE") == "1":
        return

    if runtime_python.exists():
        os.environ["SPONDEX_RUNTIME_ACTIVE"] = "1"
        os.execv(str(runtime_python), [str(runtime_python), __file__, *sys.argv[1:]])


def _ensure_pip(logger: logging.Logger) -> bool:
    try:
        importlib.import_module("pip")
        return True
    except ModuleNotFoundError:
        logger.info("pip is missing; attempting to bootstrap it via ensurepip...")

    try:
        subprocess.check_call([sys.executable, "-m", "ensurepip", "--upgrade"])
        importlib.invalidate_caches()
        importlib.import_module("pip")
        logger.info("pip bootstrap successful.")
        return True
    except (subprocess.CalledProcessError, ModuleNotFoundError) as exc:
        logger.error("Failed to bootstrap pip: %s", exc)
        return False


def _ensure_package(package: str, *, required: bool = True) -> bool:
    """Ensure package is importable; optionally install it via pip.

    Returns True if the package is available afterwards. If ``required`` is False,
    failures will be logged but won't terminate the script.
    """

    logger = logging.getLogger("clear_yandex_favorites")

    try:
        importlib.import_module(package)
        return True
    except ModuleNotFoundError:
        logger.warning("Package '%s' not found. Attempting to install...", package)
    except Exception as exc:  # pragma: no cover - extremely rare env issues
        logger.debug("Unexpected import error for '%s': %s", package, exc)
        logger.warning("Attempting to (re)install '%s'...", package)

    if not _running_in_virtualenv():
        if not required:
            logger.info(
                "Skipping auto-install of optional package '%s' outside of a virtual environment.",
                package,
            )
            return False

        logger.error(
            "Package '%s' is required but cannot be auto-installed in this managed environment. "
            "Please install it manually (e.g., via apt, pipx, or inside a virtualenv) and rerun the script.",
            package,
        )
        raise SystemExit(1)

    if not _ensure_pip(logger):
        if required:
            raise SystemExit(1)
        return False

    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        message = (
            "Failed to install optional package '%s'; continuing without it: %s"
            if not required
            else "Failed to install '%s'. Please install it manually and rerun the script: %s"
        )
        log_method = logger.warning if not required else logger.error
        log_method(message, package, exc)
        if required:
            raise SystemExit(1)
        return False

    try:
        importlib.import_module(package)
        return True
    except ModuleNotFoundError as exc:  # pragma: no cover - indicates broken install
        message = (
            "Package '%s' remains unavailable after installation attempt; continuing without it: %s"
            if not required
            else "Package '%s' is still unavailable after installation attempt: %s"
        )
        log_method = logger.warning if not required else logger.error
        log_method(message, package, exc)
        if required:
            raise SystemExit(1)
        return False


def _load_dotenv(path: str | os.PathLike[str] | None = None) -> None:
    _real_load_dotenv = None

    try:
        from dotenv import load_dotenv as _real_load_dotenv  # type: ignore
    except ModuleNotFoundError:
        if _ensure_package("python-dotenv", required=False):
            try:
                from dotenv import load_dotenv as _real_load_dotenv  # type: ignore
            except Exception:  # pragma: no cover - exotic import issues
                _real_load_dotenv = None
    except Exception:  # pragma: no cover - exotic import issues
        _real_load_dotenv = None

    if _real_load_dotenv is not None:
        try:
            _real_load_dotenv(path)
            return
        except Exception:  # pragma: no cover - dotenv failed unexpectedly
            pass

    candidate = Path(path) if path is not None else Path(".env")
    logging.getLogger("clear_yandex_favorites").info(
        "Falling back to manual .env parsing at %s", candidate
    )
    if not candidate.exists():
        logging.getLogger("clear_yandex_favorites").warning(
            "Unable to load .env file at %s", candidate
        )
        return

    for raw_line in candidate.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value



load_dotenv = _load_dotenv

logger = logging.getLogger("clear_yandex_favorites")


def _get_yandex_client(token: str) -> "YandexClient":
    _ensure_package("yandex-music")
    module = importlib.import_module("yandex_music")
    YandexClient = getattr(module, "Client")
    return YandexClient(token=token).init()


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s - %(levelname)s - %(message)s")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Remove all liked tracks from Yandex Music favorites."
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Execute the removal without interactive confirmation.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print how many tracks would be removed without deleting them.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=100,
        help="Number of track IDs to send per delete request (default: 100).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging.",
    )
    return parser.parse_args()


def chunked(sequence: List[str], size: int) -> Iterable[List[str]]:
    for start in range(0, len(sequence), size):
        yield sequence[start : start + size]


def main() -> None:
    _ensure_runtime_python()

    args = parse_args()
    configure_logging(args.verbose)

    load_dotenv()
    token = os.getenv("YANDEX_TOKEN")
    if not token:
        logger.error("Environment variable YANDEX_TOKEN is missing. Aborting.")
        raise SystemExit(1)

    logger.info("Connecting to Yandex Music API...")
    client = _get_yandex_client(token)

    logger.info("Fetching liked tracks list...")
    liked_tracks = client.users_likes_tracks()
    track_ids = [track.track_id for track in liked_tracks]
    total = len(track_ids)
    logger.info("Found %d liked tracks.", total)

    if total == 0:
        logger.info("Favorites are already empty. Nothing to do.")
        return

    if args.dry_run:
        logger.info("Dry-run mode enabled; no tracks will be removed.")
        return

    if not args.yes:
        logger.warning(
            "Confirmation flag --yes not provided. Re-run with --yes to proceed."
        )
        raise SystemExit(1)

    logger.warning(
        "Deleting ALL liked tracks from Yandex Music in batches of %d...",
        args.chunk_size,
    )

    removed = 0
    for batch in chunked(track_ids, args.chunk_size):
        client.users_likes_tracks_remove(batch)
        removed += len(batch)
        logger.debug("Removed %d tracks so far...", removed)

    logger.info("Removal complete. %d tracks deleted from favorites.", removed)


if __name__ == "__main__":
    main()
