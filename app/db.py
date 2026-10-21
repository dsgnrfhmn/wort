"""The web app's own SQLite DB: users, sessions, per-user word list, practice attempts.

Separate from the CLI's user.db; history arrives only through the export JSON.
Every per-user query takes a user_id and filters on it.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app import scoring

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    query TEXT NOT NULL,
    found INTEGER NOT NULL,
    queried_at TEXT NOT NULL,
    UNIQUE (user_id, query, queried_at)
);
CREATE TABLE IF NOT EXISTS favorites (
    id INTEGER PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    lemma TEXT NOT NULL,
    pos TEXT NOT NULL DEFAULT '',
    added_at TEXT NOT NULL,
    UNIQUE (user_id, lemma, pos)
);
CREATE TABLE IF NOT EXISTS user_words (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    lemma TEXT NOT NULL,
    pos TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'learning' CHECK (status IN ('learning', 'known')),
    translation INTEGER, form INTEGER, usage INTEGER,
    streak INTEGER NOT NULL DEFAULT 0,
    added_from TEXT NOT NULL DEFAULT 'lookup' CHECK (added_from IN ('lookup', 'cli', 'practice')),
    own_translation TEXT NOT NULL DEFAULT '',
    added_at TEXT NOT NULL,
    last_seen TEXT,
    next_due TEXT,
    UNIQUE (user_id, lemma, pos)
);
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    word_id INTEGER NOT NULL REFERENCES user_words(id) ON DELETE CASCADE,
    skill TEXT NOT NULL,
    kind TEXT NOT NULL,
    prompt TEXT NOT NULL,
    answer TEXT NOT NULL,
    verdict TEXT NOT NULL CHECK (verdict IN ('correct', 'almost', 'wrong')),
    delta INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS practice_sessions (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('saetze', 'abfrage')),
    items TEXT NOT NULL,
    pos INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_usage (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    calls INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day)
);
"""

# v0 had single-user history/favorites without user_id. Rebuild them with the column
# (NULL = unowned; the first user created adopts those rows).
_MIGRATE_V0 = """
ALTER TABLE history RENAME TO history_v0;
ALTER TABLE favorites RENAME TO favorites_v0;
"""
_COPY_V0 = """
INSERT INTO history (id, query, found, queried_at) SELECT id, query, found, queried_at FROM history_v0;
INSERT INTO favorites (id, lemma, pos, added_at) SELECT id, lemma, pos, added_at FROM favorites_v0;
DROP TABLE history_v0;
DROP TABLE favorites_v0;
"""


@dataclass
class User:
    id: int
    name: str


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


@dataclass
class Attempt:
    kind: str
    prompt: str
    answer: str
    verdict: str
    delta: int
    created_at: datetime


@dataclass
class UserWord:
    id: int
    lemma: str
    pos: str
    status: str
    state: scoring.WordState
    added_from: str
    own_translation: str
    added_at: datetime
    last_seen: datetime | None
    next_due: datetime | None

    @property
    def score(self) -> int | None:
        return scoring.word_score(self.state)


def _ts(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class WebStore:
    def __init__(self, db_path: Path | str):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")  # readers never block the admin script's writes
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self._migrate()

    def _migrate(self) -> None:
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        legacy = version == 0 and self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'history'"
        ).fetchone()
        if legacy:
            self.conn.executescript(_MIGRATE_V0)
        self.conn.executescript(SCHEMA)
        if legacy:
            self.conn.executescript(_COPY_V0)
        self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self.conn.commit()

    # --- users and sessions -------------------------------------------------

    def create_user(self, name: str, password_hash: str, now: datetime | None = None) -> User:
        """Create a user; the first one also adopts the unowned pre-v1 history and favorites."""
        now = now or datetime.now()
        first = self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        cur = self.conn.execute(
            "INSERT INTO users (name, password_hash, created_at) VALUES (?, ?, ?)",
            (name, password_hash, _ts(now)),
        )
        uid = cur.lastrowid
        if first:
            self.conn.execute("UPDATE history SET user_id = ? WHERE user_id IS NULL", (uid,))
            self.conn.execute("UPDATE favorites SET user_id = ? WHERE user_id IS NULL", (uid,))
        self.conn.commit()
        return User(uid, name)

    def user_by_name(self, name: str) -> tuple[User, str] | None:
        r = self.conn.execute("SELECT id, name, password_hash FROM users WHERE name = ?", (name,)).fetchone()
        return (User(r["id"], r["name"]), r["password_hash"]) if r else None

    def create_session(self, user_id: int, token_hash: str, now: datetime, expires: datetime) -> None:
        self.conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token_hash, user_id, _ts(now), _ts(expires)),
        )
        self.conn.commit()

    def user_for_session(self, token_hash: str, now: datetime) -> User | None:
        self.conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (_ts(now),))
        self.conn.commit()  # an open implicit transaction would keep the write lock between requests
        r = self.conn.execute(
            "SELECT u.id, u.name FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?",
            (token_hash,),
        ).fetchone()
        return User(r["id"], r["name"]) if r else None

    def delete_session(self, token_hash: str) -> None:
        self.conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
        self.conn.commit()

    # --- history and favorites ----------------------------------------------

    def add_history(self, user_id: int, rows: list[tuple[str, bool, datetime]]) -> int:
        """Insert (query, found, queried_at); duplicates are skipped. Returns the number of new rows."""
        before = self.conn.total_changes
        self.conn.executemany(
            "INSERT OR IGNORE INTO history (user_id, query, found, queried_at) VALUES (?, ?, ?, ?)",
            [(user_id, q, int(f), _ts(t)) for q, f, t in rows],
        )
        self.conn.commit()
        return self.conn.total_changes - before

    def history(self, user_id: int) -> list[HistoryRow]:
        """One row per query (case-insensitive), newest first."""
        favs = {f.lemma.casefold() for f in self.favorites(user_id)}
        latest: dict[str, tuple[str, bool, datetime]] = {}
        counts: dict[str, int] = {}
        for r in self.conn.execute("SELECT * FROM history WHERE user_id = ? ORDER BY queried_at, id", (user_id,)):
            key = r["query"].casefold()
            latest[key] = (r["query"], bool(r["found"]), datetime.fromisoformat(r["queried_at"]))
            counts[key] = counts.get(key, 0) + 1
        rows = [HistoryRow(q, found, counts[key], at, key in favs) for key, (q, found, at) in latest.items()]
        return sorted(rows, key=lambda r: r.last_at, reverse=True)

    def favorites(self, user_id: int) -> list[Favorite]:
        return [
            Favorite(r["lemma"], r["pos"], datetime.fromisoformat(r["added_at"]))
            for r in self.conn.execute(
                "SELECT * FROM favorites WHERE user_id = ? ORDER BY added_at DESC, id DESC", (user_id,)
            )
        ]

    def is_favorite(self, user_id: int, lemma: str, pos: str = "") -> bool:
        return self.conn.execute(
            "SELECT 1 FROM favorites WHERE user_id = ? AND lemma = ? AND pos = ?", (user_id, lemma, pos)
        ).fetchone() is not None

    def toggle_favorite(self, user_id: int, lemma: str, pos: str = "", now: datetime | None = None) -> bool:
        """Flip the favorite flag; returns the new state."""
        if self.is_favorite(user_id, lemma, pos):
            self.conn.execute(
                "DELETE FROM favorites WHERE user_id = ? AND lemma = ? AND pos = ?", (user_id, lemma, pos)
            )
            self.conn.commit()
            return False
        self.conn.execute(
            "INSERT INTO favorites (user_id, lemma, pos, added_at) VALUES (?, ?, ?, ?)",
            (user_id, lemma, pos, _ts(now or datetime.now())),
        )
        self.conn.commit()
        return True

    # --- word list ----------------------------------------------------------

    @staticmethod
    def _word(r: sqlite3.Row) -> UserWord:
        return UserWord(
            r["id"], r["lemma"], r["pos"], r["status"],
            scoring.WordState(r["translation"], r["form"], r["usage"], r["streak"]),
            r["added_from"], r["own_translation"], datetime.fromisoformat(r["added_at"]),
            _dt(r["last_seen"]), _dt(r["next_due"]),
        )

    def add_word(self, user_id: int, lemma: str, pos: str = "", added_from: str = "lookup",
                 now: datetime | None = None) -> bool:
        """Add a word to learn; returns False when the user already has it."""
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO user_words (user_id, lemma, pos, added_from, added_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, lemma, pos, added_from, _ts(now or datetime.now())),
        )
        self.conn.commit()
        return cur.rowcount == 1

    def words(self, user_id: int) -> list[UserWord]:
        """All words of the user, newest first."""
        return [
            self._word(r)
            for r in self.conn.execute(
                "SELECT * FROM user_words WHERE user_id = ? ORDER BY added_at DESC, id DESC", (user_id,)
            )
        ]

    def word(self, user_id: int, word_id: int) -> UserWord | None:
        r = self.conn.execute(
            "SELECT * FROM user_words WHERE user_id = ? AND id = ?", (user_id, word_id)
        ).fetchone()
        return self._word(r) if r else None

    def words_by_ids(self, user_id: int, ids: list[int]) -> list[UserWord]:
        """The user's words among ids; ids of other users' words are silently absent."""
        found = [self.word(user_id, i) for i in dict.fromkeys(ids)]
        return [w for w in found if w]

    def set_own_translation(self, user_id: int, word_id: int, text: str) -> bool:
        cur = self.conn.execute(
            "UPDATE user_words SET own_translation = ? WHERE user_id = ? AND id = ?", (text, user_id, word_id)
        )
        self.conn.commit()
        return cur.rowcount == 1

    def delete_word(self, user_id: int, word_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM user_words WHERE user_id = ? AND id = ?", (user_id, word_id))
        self.conn.commit()
        return cur.rowcount == 1

    # --- practice -----------------------------------------------------------

    def record_attempt(self, user_id: int, word_id: int, skill: str, kind: str, prompt: str,
                       answer: str, verdict: str, now: datetime | None = None) -> int | None:
        """Log one graded answer and update the word. Returns the score change, None for an unknown word."""
        now = now or datetime.now()
        w = self.word(user_id, word_id)
        if w is None:
            return None
        after = scoring.apply_verdict(w.state, skill, verdict)
        delta = scoring.score_delta(w.state, after)
        self.conn.execute(
            "UPDATE user_words SET translation = ?, form = ?, usage = ?, streak = ?, last_seen = ?, next_due = ? "
            "WHERE user_id = ? AND id = ?",
            (after.translation, after.form, after.usage, after.streak, _ts(now),
             _ts(scoring.next_due(after, verdict, now)), user_id, word_id),
        )
        self.conn.execute(
            "INSERT INTO attempts (user_id, word_id, skill, kind, prompt, answer, verdict, delta, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, word_id, skill, kind, prompt, answer, verdict, delta, _ts(now)),
        )
        self.conn.commit()
        return delta

    def attempts(self, user_id: int, word_id: int) -> list[Attempt]:
        """The user's answers for one word, newest first."""
        return [
            Attempt(r["kind"], r["prompt"], r["answer"], r["verdict"], r["delta"],
                    datetime.fromisoformat(r["created_at"]))
            for r in self.conn.execute(
                "SELECT * FROM attempts WHERE user_id = ? AND word_id = ? ORDER BY created_at DESC, id DESC",
                (user_id, word_id),
            )
        ]

    # --- practice sessions --------------------------------------------------

    def create_practice(self, user_id: int, kind: str, items: list[dict], now: datetime | None = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO practice_sessions (user_id, kind, items, created_at) VALUES (?, ?, ?, ?)",
            (user_id, kind, json.dumps(items), _ts(now or datetime.now())),
        )
        self.conn.commit()
        return cur.lastrowid

    def practice(self, user_id: int, session_id: int) -> dict | None:
        r = self.conn.execute(
            "SELECT * FROM practice_sessions WHERE user_id = ? AND id = ?", (user_id, session_id)
        ).fetchone()
        return {"id": r["id"], "kind": r["kind"], "items": json.loads(r["items"]), "pos": r["pos"]} if r else None

    def save_practice(self, user_id: int, session_id: int, items: list[dict], pos: int) -> None:
        self.conn.execute(
            "UPDATE practice_sessions SET items = ?, pos = ? WHERE user_id = ? AND id = ?",
            (json.dumps(items), pos, user_id, session_id),
        )
        self.conn.commit()

    # --- AI usage -----------------------------------------------------------

    def ai_calls_today(self, user_id: int, day: str) -> int:
        r = self.conn.execute("SELECT calls FROM ai_usage WHERE user_id = ? AND day = ?", (user_id, day)).fetchone()
        return r["calls"] if r else 0

    def ai_count_call(self, user_id: int, day: str) -> int:
        self.conn.execute(
            "INSERT INTO ai_usage (user_id, day, calls) VALUES (?, ?, 1) "
            "ON CONFLICT (user_id, day) DO UPDATE SET calls = calls + 1",
            (user_id, day),
        )
        self.conn.commit()
        return self.ai_calls_today(user_id, day)
