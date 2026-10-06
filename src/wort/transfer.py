"""Export / import of the query history and word list (the CLI → web hand-off).

Everything travels as versioned JSON: the typed queries (query, found, queried_at)
and the practice word list (lemma, pos, added_at). `entry_id` differs between
dictionary DBs and scores are not synced, so neither is exported. Treat input as
untrusted data: `parse_export` validates everything and raises ValueError.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from wort.store import Store

FORMAT_VERSION = 2
MAX_WORDS = 10_000
MAX_QUERIES = 100_000
MAX_FIELD = 100


@dataclass
class ExportedWord:
    lemma: str
    pos: str
    added_at: datetime


@dataclass
class ExportedQuery:
    query: str
    found: bool
    queried_at: datetime


@dataclass
class ExportDoc:
    words: list[ExportedWord]
    queries: list[ExportedQuery]


def export_words(store: Store, now: datetime | None = None) -> dict:
    now = now or datetime.now()
    return {
        "format_version": FORMAT_VERSION,
        "exported_at": now.isoformat(timespec="seconds"),
        "words": [
            {"lemma": w.lemma, "pos": w.pos, "added_at": w.added_at.isoformat(timespec="seconds")}
            for w in store.words()
        ],
        "queries": [
            {"query": q.query, "found": q.found, "queried_at": q.ts.isoformat(timespec="seconds")}
            for q in store.queries()
        ],
    }


def _text(item: dict, key: str, index: int, label: str = "words") -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_FIELD:
        raise ValueError(f"{label}[{index}].{key}: expected a non-empty string of at most {MAX_FIELD} characters")
    return value.strip()


def _timestamp(item: dict, key: str, label: str, index: int) -> datetime:
    try:
        return datetime.fromisoformat(_text(item, key, index, label))
    except ValueError as e:
        raise ValueError(f"{label}[{index}].{key}: not an ISO timestamp") from e


def parse_export(data: object) -> ExportDoc:
    """Validate an export document; all-or-nothing."""
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    if data.get("format_version") != FORMAT_VERSION:
        raise ValueError(f"unsupported format_version {data.get('format_version')!r}, expected {FORMAT_VERSION}")
    words, queries = data.get("words"), data.get("queries")
    if not isinstance(words, list) or not isinstance(queries, list):
        raise ValueError("'words' and 'queries' must be lists")
    if len(words) > MAX_WORDS or len(queries) > MAX_QUERIES:
        raise ValueError("too many entries")
    out_words, out_queries = [], []
    for i, item in enumerate(words):
        if not isinstance(item, dict):
            raise ValueError(f"words[{i}]: expected an object")
        out_words.append(
            ExportedWord(_text(item, "lemma", i, "words"), _text(item, "pos", i, "words"), _timestamp(item, "added_at", "words", i))
        )
    for i, item in enumerate(queries):
        if not isinstance(item, dict):
            raise ValueError(f"queries[{i}]: expected an object")
        if not isinstance(item.get("found"), bool):
            raise ValueError(f"queries[{i}].found: expected true or false")
        out_queries.append(
            ExportedQuery(_text(item, "query", i, "queries"), item["found"], _timestamp(item, "queried_at", "queries", i))
        )
    return ExportDoc(out_words, out_queries)
