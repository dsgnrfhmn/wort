"""The web app's own SQLite DB: imported query history and favorites.

Separate from the CLI's user.db; history arrives only through the export JSON.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY,
    query TEXT NOT NULL,
    found INTEGER NOT NULL,
    queried_at TEXT NOT NULL,
    UNIQUE (query, queried_at)
);
CREATE TABLE IF NOT EXISTS favorites (
    id INTEGER PRIMARY KEY,
    lemma TEXT NOT NULL,
    pos TEXT NOT NULL DEFAULT '',
    added_at TEXT NOT NULL,
    UNIQUE (lemma, pos)
);
"""


@dataclass
class HistoryRow:
    query: str
    found: bool
    count: int
    last_at: datetime
    favorite: bool


@dataclass
class Favorite:
    lemma: str
    pos: str
    added_at: datetime


class WebStore:
    def __init__(self, db_path: Path | str):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def add_history(self, rows: list[tuple[str, bool, datetime]]) -> int:
        """Insert (query, found, queried_at); duplicates are skipped. Returns the number of new rows."""
        before = self.conn.total_changes
        self.conn.executemany(
            "INSERT OR IGNORE INTO history (query, found, queried_at) VALUES (?, ?, ?)",
            [(q, int(f), t.isoformat(timespec="seconds")) for q, f, t in rows],
        )
        self.conn.commit()
        return self.conn.total_changes - before

    def history(self) -> list[HistoryRow]:
        """One row per query (case-insensitive), newest first."""
        favs = {f.lemma.casefold() for f in self.favorites()}
        latest: dict[str, tuple[str, bool, datetime]] = {}
        counts: dict[str, int] = {}
        for r in self.conn.execute("SELECT * FROM history ORDER BY queried_at, id"):
            key = r["query"].casefold()
            latest[key] = (r["query"], bool(r["found"]), datetime.fromisoformat(r["queried_at"]))
            counts[key] = counts.get(key, 0) + 1
        rows = [
            HistoryRow(q, found, counts[key], at, key in favs)
            for key, (q, found, at) in latest.items()
        ]
        return sorted(rows, key=lambda r: r.last_at, reverse=True)

    def favorites(self) -> list[Favorite]:
        return [
            Favorite(r["lemma"], r["pos"], datetime.fromisoformat(r["added_at"]))
            for r in self.conn.execute("SELECT * FROM favorites ORDER BY added_at DESC, id DESC")
        ]

    def is_favorite(self, lemma: str, pos: str = "") -> bool:
        return self.conn.execute(
            "SELECT 1 FROM favorites WHERE lemma = ? AND pos = ?", (lemma, pos)
        ).fetchone() is not None

    def toggle_favorite(self, lemma: str, pos: str = "", now: datetime | None = None) -> bool:
        """Flip the favorite flag; returns the new state."""
        if self.is_favorite(lemma, pos):
            self.conn.execute("DELETE FROM favorites WHERE lemma = ? AND pos = ?", (lemma, pos))
            self.conn.commit()
            return False
        now = now or datetime.now()
        self.conn.execute(
            "INSERT INTO favorites (lemma, pos, added_at) VALUES (?, ?, ?)",
            (lemma, pos, now.isoformat(timespec="seconds")),
        )
        self.conn.commit()
        return True
