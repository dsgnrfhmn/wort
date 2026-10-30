"""Ukrainian translations of German words.

Direct: the German Wiktionary (kaikki.org dewiktionary dump) lists translations per sense, Ukrainian among
them; only those are kept (lemma, part of speech, Ukrainian words in sense order) in dictionary-uk.db.

Via English, for a word the German Wiktionary has no Ukrainian for: the German entry's English glosses
(Antrag -> application, request) are looked up in the English Wiktionary's translation tables
(application -> заява), kept in dictionary-en-uk.db. English words are ambiguous, so a translation whose
sense shares words with the German entry's glosses is preferred, and the UI marks the result as indirect.

Each dump has its own file, so re-importing one never wipes another.
"""

from __future__ import annotations

import gzip
import json
import re
import sqlite3
import unicodedata
from collections.abc import Callable, Iterable
from pathlib import Path

from wort import sanitize
from wort.dictionary.importer import POS_KEPT, gloss_keys, iter_jsonl
from wort.text import normalize

MAX_WORDS = 8  # translations kept per lemma and part of speech
MAX_EN_PAIRS = 24  # (Ukrainian word, English sense) pairs kept per English word and part of speech
_WORDS = re.compile(r"[a-z]+")
_STOP = {"a", "an", "the", "of", "to", "or", "and", "in", "for", "on", "by", "with", "as", "be", "that", "which",
         "something", "someone", "one", "it", "from", "at", "is"}

SCHEMA = """
CREATE TABLE uk (lemma_norm TEXT NOT NULL, pos TEXT NOT NULL, words TEXT NOT NULL);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""


def _sense_key(index: object) -> tuple[int, str]:
    """'1', '2a', '' -> sortable; senses without an index go last."""
    s = str(index or "")
    digits = "".join(c for c in s if c.isdigit()) or "999"
    return int(digits[:4]), s


def parse(raw: dict) -> tuple[str, str, list[str]] | None:
    """(lemma, pos, Ukrainian words) for a German entry with Ukrainian translations, else None."""
    if raw.get("lang_code") != "de" or raw.get("pos") not in POS_KEPT:
        return None
    found = [t for t in raw.get("translations", []) if isinstance(t, dict)]
    for sense in raw.get("senses", []):
        found += [t for t in sense.get("translations", []) if isinstance(t, dict)]
    found = [t for t in found if t.get("lang_code") == "uk"]
    if not found:
        return None
    try:  # the dump is untrusted: clean every string, skip what cannot be made safe
        lemma = sanitize.word(raw.get("word", ""), 100)
    except sanitize.Unsafe:
        return None
    words: list[str] = []
    for t in sorted(found, key=lambda t: _sense_key(t.get("sense_index"))):
        try:
            w = sanitize.word(t.get("word", ""), 80)
        except sanitize.Unsafe:
            continue
        if w not in words:
            words.append(w)
    return (lemma, raw["pos"], words[:MAX_WORDS]) if lemma and words else None


def import_entries(raws: Iterable[dict], db_path: Path, progress: Callable[[int], None] | None = None) -> int:
    """Build a fresh dictionary-uk.db. Homographs (same lemma and part of speech) are merged. Returns rows."""
    merged: dict[tuple[str, str], list[str]] = {}
    seen = 0
    for raw in raws:
        seen += 1
        if progress and seen % 50000 == 0:
            progress(seen)
        parsed = parse(raw)
        if parsed is None:
            continue
        lemma, pos, words = parsed
        have = merged.setdefault((normalize(lemma), pos), [])
        have += [w for w in words if w not in have][:MAX_WORDS - len(have)]
    tmp_path = db_path.with_suffix(".tmp")
    tmp_path.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp_path)
    conn.executescript(SCHEMA)
    conn.executemany("INSERT INTO uk VALUES (?, ?, ?)",
                     [(n, p, json.dumps(w, ensure_ascii=False)) for (n, p), w in merged.items()])
    conn.execute("CREATE INDEX idx_uk_lemma ON uk(lemma_norm)")
    conn.execute("INSERT INTO meta VALUES ('entries', ?)", (str(len(merged)),))
    conn.commit()
    conn.close()
    tmp_path.replace(db_path)
    return len(merged)


def import_file(path: Path, db_path: Path, progress: Callable[[int], None] | None = None) -> int:
    """Import the raw dump, gzipped (as fetched) or not."""
    with _open(path) as fh:
        return import_entries(iter_jsonl(fh), db_path, progress)


def _open(path: Path):
    return (gzip.open if path.suffix == ".gz" else open)(path, "rt", encoding="utf-8", errors="replace")


def _unstressed(word: str) -> str:
    """Drop the stress accents dictionaries put on Ukrainian words (словни́к -> словник)."""
    return unicodedata.normalize("NFC", "".join(c for c in unicodedata.normalize("NFD", word) if c != "\u0301"))


def parse_english(raw: dict) -> tuple[str, str, list[tuple[str, str]]] | None:
    """(English word, pos, [(Ukrainian word, English sense)]) for an English entry with Ukrainian translations."""
    if raw.get("lang_code") != "en" or raw.get("pos") not in POS_KEPT:
        return None
    found = [t for t in raw.get("translations", []) if isinstance(t, dict)]
    for sense in raw.get("senses", []):
        found += [t for t in sense.get("translations", []) if isinstance(t, dict)]
    try:
        word = sanitize.word(raw.get("word", ""), 100)
    except sanitize.Unsafe:
        return None
    pairs: list[tuple[str, str]] = []
    for t in found:
        if t.get("lang_code") != "uk":
            continue
        try:
            uk = _unstressed(sanitize.word(t.get("word", ""), 80))
        except sanitize.Unsafe:
            continue
        sense = sanitize.text(t.get("sense", ""), 120)
        if uk and (uk, sense) not in pairs:
            pairs.append((uk, sense))
    return (word, raw["pos"], pairs[:MAX_EN_PAIRS]) if pairs else None


def import_english(path: Path, db_path: Path, progress: Callable[[int], None] | None = None) -> int:
    """Build a fresh dictionary-en-uk.db from the English dump (or the filtered file fetch_data.py writes)."""
    merged: dict[tuple[str, str], list[tuple[str, str]]] = {}
    with _open(path) as fh:
        for seen, raw in enumerate(iter_jsonl(fh), 1):
            if progress and seen % 50000 == 0:
                progress(seen)
            parsed = parse_english(raw)
            if parsed is None:
                continue
            word, pos, pairs = parsed
            have = merged.setdefault((word.casefold(), pos), [])
            have += [p for p in pairs if p not in have][:MAX_EN_PAIRS - len(have)]
    tmp_path = db_path.with_suffix(".tmp")
    tmp_path.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp_path)
    conn.executescript("CREATE TABLE en_uk (en TEXT NOT NULL, pos TEXT NOT NULL, pairs TEXT NOT NULL);"
                       "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);")
    conn.executemany("INSERT INTO en_uk VALUES (?, ?, ?)",
                     [(w, p, json.dumps(v, ensure_ascii=False)) for (w, p), v in merged.items()])
    conn.execute("CREATE INDEX idx_en_uk ON en_uk(en)")
    conn.execute("INSERT INTO meta VALUES ('entries', ?)", (str(len(merged)),))
    conn.commit()
    conn.close()
    tmp_path.replace(db_path)
    return len(merged)


def _content_words(text: str) -> set[str]:
    return {w for w in _WORDS.findall(text.lower()) if w not in _STOP and len(w) > 2}


class Ukrainian:
    """Read-only lookup. Missing direct file -> FileNotFoundError, like Dictionary; the English file is optional."""

    def __init__(self, db_path: Path, en_db_path: Path | None = None):
        if not db_path.exists():
            raise FileNotFoundError(db_path)
        self.conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)
        self.en = (sqlite3.connect(f"file:{en_db_path}?mode=ro", uri=True, check_same_thread=False)
                   if en_db_path and en_db_path.exists() else None)

    def translations(self, lemma: str, pos: str | None = None) -> list[str]:
        """Ukrainian words for the lemma; the same part of speech first, any other if it has none."""
        rows = self.conn.execute("SELECT pos, words FROM uk WHERE lemma_norm = ?", (normalize(lemma),)).fetchall()
        rows.sort(key=lambda r: r[0] != pos)
        return json.loads(rows[0][1]) if rows else []

    def via_english(self, glosses: list[str], pos: str | None = None, limit: int = 3) -> list[str]:
        """Ukrainian words reached through the entry's English glosses, best first; [] without the English file.

        Per English key (in gloss order), its translation whose English sense shares the most content words
        with all of the entry's glosses wins; ties keep the dictionary's order."""
        if self.en is None or not glosses:
            return []
        context = _content_words(" ".join(glosses))
        out: list[str] = []
        for key in [k for g in glosses[:2] for k in gloss_keys(g)]:
            rows = self.en.execute("SELECT pos, pairs FROM en_uk WHERE en = ?", (key.casefold(),)).fetchall()
            rows.sort(key=lambda r: r[0] != pos)
            if not rows:
                continue
            pairs = json.loads(rows[0][1])
            ranked = sorted(range(len(pairs)), key=lambda i: (-len(_content_words(pairs[i][1]) & (context - {key})), i))
            for i in ranked[:1]:
                if pairs[i][0] not in out:
                    out.append(pairs[i][0])
            if len(out) >= limit:
                break
        return out
