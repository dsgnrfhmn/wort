"""German definitions of German words (Bedeutungen), for the lookup's monolingual explanation.

Source: the German Wiktionary (kaikki.org dewiktionary dump, the same file the Ukrainian translations come from);
its senses carry German glosses. Up to MAX_SENSES per lemma and part of speech, in sense order, are kept in their
own file (dictionary-de.db), so re-importing it never touches the other dictionaries.
"""

from __future__ import annotations

import gzip
import json
import sqlite3
from collections.abc import Callable, Iterable
from pathlib import Path

from wort import sanitize
from wort.dictionary.importer import POS_KEPT, iter_jsonl
from wort.text import normalize

MAX_SENSES = 3
MAX_GLOSS = 300

SCHEMA = """
CREATE TABLE de (lemma_norm TEXT NOT NULL, pos TEXT NOT NULL, senses TEXT NOT NULL);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""


def parse(raw: dict) -> tuple[str, str, list[str]] | None:
    """(lemma, pos, German definitions) for a German entry with glosses, else None."""
    if raw.get("lang_code") != "de" or raw.get("pos") not in POS_KEPT:
        return None
    try:  # the dump is untrusted: clean every string, skip what cannot be made safe
        lemma = sanitize.word(raw.get("word", ""), 100)
    except sanitize.Unsafe:
        return None
    senses: list[str] = []
    for sense in raw.get("senses", []):
        if not isinstance(sense, dict) or "form_of" in sense:
            continue  # "Nominativ Plural des Substantivs …": a form, not a meaning
        for gloss in sense.get("glosses", [])[:1]:
            text = sanitize.text(str(gloss), MAX_GLOSS) if isinstance(gloss, str) else ""
            if text and text not in senses:
                senses.append(text)
        if len(senses) >= MAX_SENSES:
            break
    return (lemma, raw["pos"], senses) if lemma and senses else None


def import_entries(raws: Iterable[dict], db_path: Path, progress: Callable[[int], None] | None = None) -> int:
    """Build a fresh dictionary-de.db. Homographs (same lemma and part of speech) are merged. Returns rows."""
    merged: dict[tuple[str, str], list[str]] = {}
    seen = 0
    for raw in raws:
        seen += 1
        if progress and seen % 50000 == 0:
            progress(seen)
        parsed = parse(raw)
        if parsed is None:
            continue
        lemma, pos, senses = parsed
        have = merged.setdefault((normalize(lemma), pos), [])
        have += [s for s in senses if s not in have][:MAX_SENSES - len(have)]
    tmp_path = db_path.with_suffix(".tmp")
    tmp_path.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp_path)
    conn.executescript(SCHEMA)
    conn.executemany("INSERT INTO de VALUES (?, ?, ?)",
                     [(n, p, json.dumps(s, ensure_ascii=False)) for (n, p), s in merged.items()])
    conn.execute("CREATE INDEX idx_de_lemma ON de(lemma_norm)")
    conn.execute("INSERT INTO meta VALUES ('entries', ?)", (str(len(merged)),))
    conn.commit()
    conn.close()
    tmp_path.replace(db_path)
    return len(merged)


def import_file(path: Path, db_path: Path, progress: Callable[[int], None] | None = None) -> int:
    """Import the raw dump, gzipped (as fetched) or not."""
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as fh:
        return import_entries(iter_jsonl(fh), db_path, progress)


class GermanDefinitions:
    """Read-only lookup. Missing file -> FileNotFoundError, like Dictionary and Ukrainian."""

    def __init__(self, db_path: Path):
        if not db_path.exists():
            raise FileNotFoundError(db_path)
        self.conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)

    def definitions(self, lemma: str, pos: str | None = None) -> list[str]:
        """German definitions for the lemma; the same part of speech first, any other if it has none."""
        rows = self.conn.execute("SELECT pos, senses FROM de WHERE lemma_norm = ?", (normalize(lemma),)).fetchall()
        rows.sort(key=lambda r: r[0] != pos)
        return json.loads(rows[0][1]) if rows else []
