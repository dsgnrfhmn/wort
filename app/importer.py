"""Import a `wort export` JSON file into the web DB (untrusted input)."""

from __future__ import annotations

import json
from dataclasses import dataclass

from wort.transfer import parse_export

from app.db import WebStore

MAX_BYTES = 20 * 1024 * 1024


@dataclass
class ImportResult:
    queries_total: int
    queries_new: int


def import_export(store: WebStore, raw: bytes) -> ImportResult:
    """Validate and merge; raises ValueError on anything malformed (nothing is written then)."""
    if len(raw) > MAX_BYTES:
        raise ValueError("file too large")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError("not valid UTF-8 JSON") from e
    doc = parse_export(data)
    new = store.add_history([(q.query, q.found, q.queried_at) for q in doc.queries])
    return ImportResult(len(doc.queries), new)
