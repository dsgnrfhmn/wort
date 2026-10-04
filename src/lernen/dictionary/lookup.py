"""Read-only access to dictionary.db."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from lernen.text import normalize

Form = tuple[str, tuple[str, ...]]


@dataclass
class Entry:
    id: int
    lemma: str
    pos: str
    gender: str | None = None
    ipa: str | None = None
    aux: str | None = None
    separable: bool = False
    conj: str | None = None
    glosses: list[str] = field(default_factory=list)
    examples: list[tuple[str, str]] = field(default_factory=list)
    forms: list[Form] = field(default_factory=list)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Entry:
        return cls(
            id=row["id"],
            lemma=row["lemma"],
            pos=row["pos"],
            gender=row["gender"],
            ipa=row["ipa"],
            aux=row["aux"],
            separable=bool(row["separable"]),
            conj=row["conj"],
            glosses=json.loads(row["glosses"]),
            examples=[tuple(e) for e in json.loads(row["examples"])],
            forms=[(f, tuple(t)) for f, t in json.loads(row["forms"])],
        )


class Dictionary:
    def __init__(self, db_path: Path):
        if not db_path.exists():
            raise FileNotFoundError(db_path)
        self.conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

    def get(self, entry_id: int) -> Entry | None:
        row = self.conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
        return Entry.from_row(row) if row else None

    def find_lemma(self, lemma: str, pos: str | None = None) -> Entry | None:
        rows = self.conn.execute(
            "SELECT * FROM entries WHERE lemma_norm = ? ORDER BY (lemma = ?) DESC, weight DESC",
            (normalize(lemma), lemma),
        ).fetchall()
        for row in rows:
            if pos is None or row["pos"] == pos:
                return Entry.from_row(row)
        return Entry.from_row(rows[0]) if rows else None

    def lookup_german(self, query: str, limit: int = 5) -> list[Entry]:
        norm = normalize(query)
        rows = self.conn.execute(
            "SELECT * FROM entries WHERE lemma_norm = ? ORDER BY (lemma = ?) DESC, weight DESC LIMIT ?",
            (norm, query.strip(), limit),
        ).fetchall()
        if not rows:
            rows = self.conn.execute(
                "SELECT DISTINCT e.* FROM form_index f JOIN entries e ON e.id = f.entry_id"
                " WHERE f.form_norm = ? ORDER BY e.weight DESC LIMIT ?",
                (norm, limit),
            ).fetchall()
        return [Entry.from_row(r) for r in rows]

    def lookup_english(self, query: str, limit: int = 5) -> list[Entry]:
        key = normalize(query)
        for prefix in ("to ", "a ", "an ", "the "):
            if key.startswith(prefix):
                key = key[len(prefix):]
        rows = self.conn.execute(
            "SELECT e.* FROM en_index i JOIN entries e ON e.id = i.entry_id"
            " WHERE i.en_word = ? ORDER BY i.score ASC, e.weight DESC LIMIT ?",
            (key, limit),
        ).fetchall()
        return [Entry.from_row(r) for r in rows]

    def lookup(self, query: str, limit: int = 5) -> tuple[list[Entry], list[Entry]]:
        """Return (German matches, English→German matches)."""
        if not query.strip():
            return [], []
        german = self.lookup_german(query, limit)
        seen = {e.id for e in german}
        english = [e for e in self.lookup_english(query, limit) if e.id not in seen]
        return german, english
