from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from monitoring.config import Config
from monitoring.notifier import send_notifications


class _SMTPStub:
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, Any]] = []

    def __enter__(self) -> "_SMTPStub":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - standard context behaviour
        pass

    # signature aligned with smtplib.SMTP.send_message
    def send_message(self, msg, to_addrs=None):  # type: ignore[no-untyped-def]
        self.sent_messages.append({"message": msg, "to_addrs": to_addrs})


class _ResponseStub:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> "_ResponseStub":  # pragma: no cover - standard context behaviour
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - standard context behaviour
        pass


def test_send_notifications_telegram(monkeypatch):
    config = Config()
    config.notification.telegram.enabled = True
    config.notification.telegram.chat_ids = ["123"]
    config.notification.mail.enabled = False

    token_env = config.notification.telegram.bot_token_env
    monkeypatch.setenv(token_env, "secret-token")

    def fake_urlopen(request, timeout):  # type: ignore[no-untyped-def]
        payload = json.loads(request.data.decode("utf-8"))
        assert payload["chat_id"] == "123"
        assert "text" in payload
        return _ResponseStub({"ok": True})

    monkeypatch.setattr("monitoring.notifier.urllib.request.urlopen", fake_urlopen)

    errors = send_notifications(config, [], "Test report", force=True)
    assert errors == []


def test_send_notifications_telegram_inline_token(monkeypatch):
    config = Config()
    config.notification.telegram.enabled = True
    config.notification.telegram.chat_ids = ["777"]
    config.notification.telegram.token = "inline-token"
    config.notification.mail.enabled = False

    token_env = config.notification.telegram.bot_token_env
    monkeypatch.delenv(token_env, raising=False)

    def fake_urlopen(request, timeout):  # type: ignore[no-untyped-def]
        payload = json.loads(request.data.decode("utf-8"))
        assert payload["chat_id"] == "777"
        assert payload["text"].startswith("Test")
        return _ResponseStub({"ok": True})

    monkeypatch.setattr("monitoring.notifier.urllib.request.urlopen", fake_urlopen)

    errors = send_notifications(config, [], "Test inline", force=True)
    assert errors == []


def test_send_notifications_telegram_auto_register(monkeypatch, tmp_path):
    config = Config()
    config.notification.telegram.enabled = True
    config.notification.telegram.chat_ids = []
    config.notification.telegram.token = "inline-token"
    config.notification.telegram.poll_updates = True
    store_path = tmp_path / "subs.json"
    config.notification.telegram.subscriber_store = store_path
    config.notification.mail.enabled = False

    def fake_urlopen(request, timeout):  # type: ignore[no-untyped-def]
        url = request.full_url if hasattr(request, "full_url") else request.get_full_url()
        if "getUpdates" in url:
            return _ResponseStub(
                {
                    "ok": True,
                    "result": [
                        {
                            "update_id": 42,
                            "message": {
                                "text": "/start",
                                "chat": {"id": 555, "type": "private"},
                            },
                        }
                    ],
                }
            )
        payload = json.loads(request.data.decode("utf-8"))
        assert payload["chat_id"] == "555"
        return _ResponseStub({"ok": True})

    monkeypatch.setattr("monitoring.notifier.urllib.request.urlopen", fake_urlopen)

    errors = send_notifications(config, [], "Auto-register", force=True)
    assert errors == []
    saved = json.loads(store_path.read_text(encoding="utf-8"))
    assert saved["chat_ids"] == ["555"]
    assert saved["last_update_id"] == 42


def test_send_notifications_telegram_existing_subscribers(monkeypatch, tmp_path):
    config = Config()
    config.notification.telegram.enabled = True
    config.notification.telegram.chat_ids = []
    config.notification.telegram.token = "inline-token"
    config.notification.telegram.poll_updates = False
    store_path = tmp_path / "subs.json"
    config.notification.telegram.subscriber_store = store_path
    config.notification.mail.enabled = False

    store_path.write_text(
        json.dumps({"chat_ids": ["101", "202"], "last_update_id": 99}),
        encoding="utf-8",
    )

    sent = []

    def fake_urlopen(request, timeout):  # type: ignore[no-untyped-def]
        payload = json.loads(request.data.decode("utf-8"))
        sent.append(payload["chat_id"])
        return _ResponseStub({"ok": True})

    monkeypatch.setattr("monitoring.notifier.urllib.request.urlopen", fake_urlopen)

    errors = send_notifications(config, [SimpleNamespace()], "Alert body")
    assert errors == []
    assert sorted(sent) == ["101", "202"]


def test_send_notifications_email(monkeypatch):
    config = Config()
    config.notification.mail.enabled = True
    config.notification.mail.recipients = ["ops@example.com"]
    config.notification.telegram.enabled = False

    smtp_stub = _SMTPStub()
    monkeypatch.setattr("monitoring.notifier.smtplib.SMTP", lambda host: smtp_stub)

    errors = send_notifications(config, [SimpleNamespace()], "Alert", force=True)
    assert errors == []
    assert smtp_stub.sent_messages


def test_send_notifications_missing_telegram_token(monkeypatch):
    config = Config()
    config.notification.telegram.enabled = True
    config.notification.telegram.chat_ids = ["123"]
    config.notification.mail.enabled = False

    token_env = config.notification.telegram.bot_token_env
    monkeypatch.delenv(token_env, raising=False)

    errors = send_notifications(config, [SimpleNamespace()], "body")
    assert any(err.startswith("telegram:") for err in errors)


def test_send_notifications_no_channels():
    config = Config()
    config.notification.telegram.enabled = False
    config.notification.mail.enabled = False

    errors = send_notifications(config, [SimpleNamespace()], "body")
    assert errors == []