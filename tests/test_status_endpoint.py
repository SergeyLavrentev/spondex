import json
import time
from types import SimpleNamespace

import pytest

from src import main


def _stub_system_metrics(monkeypatch):
    monkeypatch.setattr(main.psutil, "cpu_percent", lambda interval=0: 12.5)
    monkeypatch.setattr(main.psutil, "virtual_memory", lambda: SimpleNamespace(percent=42.0))
    monkeypatch.setattr(main.psutil, "disk_usage", lambda path: SimpleNamespace(free=15 * 1024 ** 3))


@pytest.fixture()
def status_client(monkeypatch):
    _stub_system_metrics(monkeypatch)
    # Reset start time for deterministic uptime handling
    main.app._start_time = time.time() - 120
    with main.app.test_client() as client:
        yield client


def test_status_reports_tag_version(monkeypatch, tmp_path, status_client):
    metadata = {
        "commit": "abcdef1234567890",
        "tag": "v1.2.3",
        "build_time": "2025-10-07T00:00:00Z",
        "source": "deploy",
    }
    version_file = tmp_path / "version.json"
    version_file.write_text(json.dumps(metadata))
    monkeypatch.setenv("SPONDEX_VERSION_FILE", str(version_file))

    response = status_client.get("/status")
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["version"] == "v1.2.3"
    assert payload["release"]["commit"] == "abcdef1234567890"
    assert payload["release"]["commit_short"] == "abcdef1"
    assert payload["release"]["tag"] == "v1.2.3"
    assert payload["release"]["package"] == main._load_package_version()


def test_status_falls_back_to_commit_short(monkeypatch, tmp_path, status_client):
    metadata = {
        "commit": "1234567890abcdef",
        "build_time": "2025-10-07T01:00:00Z",
        "source": "deploy",
    }
    version_file = tmp_path / "version.json"
    version_file.write_text(json.dumps(metadata))
    monkeypatch.setenv("SPONDEX_VERSION_FILE", str(version_file))

    response = status_client.get("/status")
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["version"] == "1234567"
    assert payload["release"]["tag"] in (None, "")
    assert payload["release"]["commit"] == "1234567890abcdef"
    assert payload["release"]["commit_short"] == "1234567"


def test_status_uses_package_version_when_metadata_missing(monkeypatch, tmp_path, status_client):
    missing_file = tmp_path / "missing.json"
    monkeypatch.setenv("SPONDEX_VERSION_FILE", str(missing_file))

    response = status_client.get("/status")
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["release"]["commit"] is None
    assert payload["release"]["tag"] is None
    assert payload["version"] == main._load_package_version()