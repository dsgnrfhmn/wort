"""The learner's own data: saved words, answers and spaced-repetition state (user.db)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from lernen.srs import SrsState, mastery, review

SCHEMA = """
CREATE TABLE IF NOT EXISTS words (
    id INTEGER PRIMARY KEY,
    lemma TEXT NOT NULL,
    pos TEXT NOT NULL,
    entry_id INTEGER,
    note TEXT NOT NULL DEFAULT '',
    added_at TEXT NOT NULL,
    UNIQUE (lemma, pos)
);
CREATE TABLE IF NOT EXISTS queries (
    id INTEGER PRIMARY KEY,
    query TEXT NOT NULL,
    found INTEGER NOT NULL,
    ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY,
    word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    exercise TEXT NOT NULL,
    verdict TEXT NOT NULL,
    answer TEXT NOT NULL DEFAULT '',
    ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reviews_word ON reviews(word_id, ts);
CREATE TABLE IF NOT EXISTS srs (
    word_id INTEGER PRIMARY KEY REFERENCES words(id) ON DELETE CASCADE,
    ease REAL NOT NULL,
    interval REAL NOT NULL,
    reps INTEGER NOT NULL,
    due TEXT NOT NULL
);
"""


@dataclass
class Word:
    id: int
    lemma: str
    pos: str
    entry_id: int | None
    added_at: datetime


@dataclass
class Query:
    id: int
    query: str
    found: bool
    ts: datetime


@dataclass
class WordStats:
    word: Word
    mastery: int
    attempts: int
    due: datetime | None
    by_exercise: dict[str, float]  # exercise -> accuracy 0..1


class Store:
    def __init__(self, db_path: Path):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)

    @staticmethod
    def _word(row: sqlite3.Row) -> Word:
        return Word(row["id"], row["lemma"], row["pos"], row["entry_id"], datetime.fromisoformat(row["added_at"]))

    def add_word(self, lemma: str, pos: str, entry_id: int | None, now: datetime | None = None) -> Word:
        now = now or datetime.now()
        self.conn.execute(
            "INSERT INTO words (lemma, pos, entry_id, added_at) VALUES (?, ?, ?, ?)"
            " ON CONFLICT (lemma, pos) DO UPDATE SET entry_id = excluded.entry_id",
            (lemma, pos, entry_id, now.isoformat(timespec="seconds")),
        )
        self.conn.commit()
        return self.get_word(lemma, pos)

    def log_query(self, query: str, found: bool, now: datetime | None = None) -> None:
        """Record what the user typed, whether or not anything was found."""
        now = now or datetime.now()
        self.conn.execute(
            "INSERT INTO queries (query, found, ts) VALUES (?, ?, ?)",
            (query, int(found), now.isoformat(timespec="seconds")),
        )
        self.conn.commit()

    def queries(self) -> list[Query]:
        return [
            Query(r["id"], r["query"], bool(r["found"]), datetime.fromisoformat(r["ts"]))
            for r in self.conn.execute("SELECT * FROM queries ORDER BY id")
        ]

    def get_word(self, lemma: str, pos: str) -> Word | None:
        row = self.conn.execute("SELECT * FROM words WHERE lemma = ? AND pos = ?", (lemma, pos)).fetchone()
        return self._word(row) if row else None

    def has_word(self, lemma: str, pos: str) -> bool:
        return self.get_word(lemma, pos) is not None

    def remove_word(self, word_id: int) -> None:
        self.conn.execute("DELETE FROM words WHERE id = ?", (word_id,))
        self.conn.commit()

    def words(self) -> list[Word]:
        return [self._word(r) for r in self.conn.execute("SELECT * FROM words ORDER BY added_at, id")]

    def srs_state(self, word_id: int) -> SrsState:
        row = self.conn.execute("SELECT * FROM srs WHERE word_id = ?", (word_id,)).fetchone()
        if row is None:
            return SrsState()
        return SrsState(row["ease"], row["interval"], row["reps"], datetime.fromisoformat(row["due"]))

    def record(self, word_id: int, exercise: str, verdict: str, answer: str = "", now: datetime | None = None) -> SrsState:
        now = now or datetime.now()
        state = review(self.srs_state(word_id), verdict, now)
        self.conn.execute(
            "INSERT INTO reviews (word_id, exercise, verdict, answer, ts) VALUES (?, ?, ?, ?, ?)",
            (word_id, exercise, verdict, answer, now.isoformat(timespec="seconds")),
        )
        self.conn.execute(
            "INSERT INTO srs (word_id, ease, interval, reps, due) VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT (word_id) DO UPDATE SET ease = excluded.ease, interval = excluded.interval,"
            " reps = excluded.reps, due = excluded.due",
            (word_id, state.ease, state.interval, state.reps, state.due.isoformat(timespec="seconds")),
        )
        self.conn.commit()
        return state

    def stats(self, word: Word) -> WordStats:
        rows = self.conn.execute(
            "SELECT exercise, verdict FROM reviews WHERE word_id = ? ORDER BY ts DESC, id DESC", (word.id,)
        ).fetchall()
        state = self.srs_state(word.id)
        by_exercise: dict[str, list[float]] = {}
        for r in rows:
            by_exercise.setdefault(r["exercise"], []).append({"correct": 1.0, "almost": 0.5}.get(r["verdict"], 0.0))
        return WordStats(
            word=word,
            mastery=mastery([r["verdict"] for r in rows], state.interval),
            attempts=len(rows),
            due=state.due,
            by_exercise={k: sum(v) / len(v) for k, v in by_exercise.items()},
        )

    def all_stats(self) -> list[WordStats]:
        return sorted((self.stats(w) for w in self.words()), key=lambda s: (s.mastery, s.word.lemma.lower()))

    def session_words(self, limit: int = 10, now: datetime | None = None) -> list[Word]:
        """Due or never-practised words first, then the weakest ones."""
        now = now or datetime.now()
        stats = self.all_stats()
        due = [s for s in stats if s.due is None or s.due <= now]
        rest = [s for s in stats if s not in due]
        return [s.word for s in (due + rest)[:limit]]
