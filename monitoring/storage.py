from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator, Optional


SCHEMA = """
CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    value REAL,
    recorded_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_metrics_name_time
    ON metrics (name, recorded_at);
"""


@dataclass
class Metric:
    name: str
    value: float
    recorded_at: datetime


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        try:
            yield conn
        finally:
            conn.close()

    def save_metrics(self, metrics: Iterable[Metric]) -> None:
        items = [(m.name, m.value, m.recorded_at.isoformat()) for m in metrics]
        with self.connection() as conn:
            conn.executemany(
                "INSERT INTO metrics (name, value, recorded_at) VALUES (?, ?, ?)",
                items,
            )
            conn.commit()

    def prune_metrics_older_than(self, cutoff: datetime) -> None:
        with self.connection() as conn:
            conn.execute("DELETE FROM metrics WHERE recorded_at < ?", (cutoff.isoformat(),))
            conn.commit()

    def fetch_metric_window(self, name: str, since: datetime) -> list[Metric]:
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT name, value, recorded_at FROM metrics WHERE name = ? AND recorded_at >= ? ORDER BY recorded_at",
                (name, since.isoformat()),
            )
            rows = cursor.fetchall()
        return [Metric(row[0], float(row[1]), datetime.fromisoformat(row[2])) for row in rows]

    def get_state(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self.connection() as conn:
            cursor = conn.execute("SELECT value FROM state WHERE key = ?", (key,))
            row = cursor.fetchone()
        if row is None:
            return default
        return row[0]

    def set_state(self, key: str, value: str) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            conn.commit()

    def set_json_state(self, key: str, value: dict) -> None:
        self.set_state(key, json.dumps(value))

    def get_json_state(self, key: str, default: Optional[dict] = None) -> dict:
        raw = self.get_state(key)
        if raw is None:
            return default or {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return default or {}


__all__ = ["StateStore", "Metric"]
