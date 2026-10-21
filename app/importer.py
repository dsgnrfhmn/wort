"""Import a `wort export` JSON file into the web DB (untrusted input)."""

from __future__ import annotations

import json
from dataclasses import dataclass

from wort.transfer import parse_export

from app.db import WebStore

MAX_BYTES = 20 * 1024 * 1024
MAX_WORDS_PER_USER = 20_000


@dataclass
class ImportResult:
    queries_total: int
    queries_new: int
    words_total: int = 0
    words_new: int = 0


def import_export(store: WebStore, user_id: int, raw: bytes) -> ImportResult:
    """Validate and merge; raises ValueError on anything malformed (nothing is written then)."""
    if len(raw) > MAX_BYTES:
        raise ValueError("file too large")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError("not valid UTF-8 JSON") from e
    doc = parse_export(data)
    if store.word_count(user_id) + len(doc.words) > MAX_WORDS_PER_USER:  # conservative: duplicates still count
        raise ValueError(f"word list limit ({MAX_WORDS_PER_USER}) would be exceeded")
    new = store.add_history(user_id, [(q.query, q.found, q.queried_at) for q in doc.queries])
    words_new = sum(
        store.add_word(user_id, w.lemma, w.pos, added_from="cli", now=w.added_at) for w in doc.words
    )
    return ImportResult(len(doc.queries), new, len(doc.words), words_new)
