"""The query history: two plain files in the data repository, `words.jsonl` and `sentences.jsonl`.

Rules and format: `wort.dataschema`. Nothing that breaks them is ever written (`add` raises
`Invalid`). Reading is tolerant: a bad line (hand edit, another writer) is skipped and counted in
`skipped`, and it is dropped by the next rewrite (`delete`, `clear`); `wort sync` is strict and
refuses to push such a file.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, NamedTuple

from wort import dataschema
from wort.dataschema import Entry, Invalid
from wort.sentence import MIN_SENTENCE_WORDS


@dataclass
class Item:
    """One row of the history: every try of the same text (case-insensitive) folded together."""

    text: str  # the latest spelling
    found: bool  # at the latest try
    count: int
    ts: datetime  # the latest try


class HistoryStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.skipped = {kind: 0 for kind in dataschema.FILES}  # bad lines met by the last read of each file

    def path(self, kind: str) -> Path:
        return self.root / dataschema.FILES[kind]

    @contextlib.contextmanager
    def _locked(self):
        """One writer at a time (other wort sessions): an exclusive lock on the directory."""
        self.root.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.root, os.O_RDONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)  # closing releases the lock

    def read(self, kind: str) -> list[Entry]:
        """Every valid entry, oldest first."""
        entries: list[Entry] = []
        skipped = 0
        try:
            raw = self.path(kind).read_bytes().decode("utf-8", errors="replace")
        except FileNotFoundError:
            raw = ""
        for line in raw.split("\n"):
            if not line:
                continue
            try:
                entries.append(dataschema.parse_line(line, kind))
            except Invalid:
                skipped += 1
        self.skipped[kind] = skipped
        return entries

    def add(self, kind: str, text: str, found: bool = True, now: datetime | None = None) -> Entry:
        """Append one entry. Raises Invalid, and writes nothing, when `text` may not be stored."""
        entry = dataschema.make_entry(kind, text, found, now)
        self.append([entry])
        return entry

    def append(self, entries: list[Entry]) -> None:
        by_kind: dict[str, list[str]] = {}
        for entry in entries:
            by_kind.setdefault(entry.kind, []).append(dataschema.dump_line(entry))
        with self._locked():
            for kind, lines in by_kind.items():
                with open(self.path(kind), "ab") as handle:
                    handle.write(("\n".join(lines) + "\n").encode("utf-8"))

    def replace(self, kind: str, old: str, new: str, found: bool = True, latest_only: bool = False) -> int:
        """Save `new` instead of `old`: every try of `old` (case-insensitive) gets the text `new`, keeping its time.

        With `latest_only`, only the newest try changes (the lookup that was just saved, not older ones). Returns
        how many lines changed (0: there was no such text). Raises Invalid, and changes nothing, when `new` may
        not be stored.
        """
        key = old.casefold()
        with self._locked():
            entries = self.read(kind)
            hits = [i for i, e in enumerate(entries) if e.text.casefold() == key]
            if latest_only:
                hits = hits[-1:]
            if not hits:
                return 0
            for i in hits:
                entries[i] = dataschema.make_entry(kind, new, found, entries[i].ts)
            self._rewrite(kind, entries)
        return len(hits)

    def merge(self, entries: list[Entry]) -> int:
        """Add entries that are not in the files yet (same kind, text and time), keeping each file in time order.

        Used for older history (migration): its entries go in front of newer ones. Returns how many were added;
        running it twice with the same entries adds nothing the second time.
        """
        added = 0
        with self._locked():
            for kind in dataschema.FILES:
                existing = self.read(kind)
                known = {(e.text, e.ts) for e in existing}
                new = []
                for entry in entries:
                    if entry.kind == kind and (entry.text, entry.ts) not in known:
                        known.add((entry.text, entry.ts))
                        new.append(entry)
                if new:
                    self._rewrite(kind, sorted(existing + new, key=lambda e: e.ts))  # stable: ties keep the file's order
                    added += len(new)
        return added

    def unique(self, kind: str, since: datetime | None = None) -> list[Item]:
        """One item per text, case-insensitive, oldest first (the newest ends up at the bottom).

        With `since`, only tries made at or after that moment count: how a session sees just its own.
        """
        latest: dict[str, Entry] = {}
        counts: dict[str, int] = {}
        for entry in self.read(kind):
            if since is not None and entry.ts < since:
                continue
            key = entry.text.casefold()
            latest.pop(key, None)  # re-insert so the order follows the latest occurrence
            latest[key] = entry
            counts[key] = counts.get(key, 0) + 1
        return [Item(e.text, e.found, counts[key], e.ts) for key, e in latest.items()]

    def delete(self, kind: str, text: str) -> int:
        """Remove every try of `text` (case-insensitive); returns how many lines went."""
        key = text.casefold()
        with self._locked():
            entries = self.read(kind)
            kept = [e for e in entries if e.text.casefold() != key]
            if len(kept) != len(entries) or self.skipped[kind]:
                self._rewrite(kind, kept)
        return len(entries) - len(kept)

    def clear(self, kind: str | None = None) -> int:
        """Remove the whole history (one kind, or both); returns how many entries went."""
        removed = 0
        with self._locked():
            for each in [kind] if kind else list(dataschema.FILES):
                removed += len(self.read(each))
                if self.path(each).exists():
                    self._rewrite(each, [])
        return removed

    def _rewrite(self, kind: str, entries: list[Entry]) -> None:
        path = self.path(kind)
        tmp = path.with_name(f".{path.name}.tmp")
        body = "".join(dataschema.dump_line(e) + "\n" for e in entries)
        with open(tmp, "wb") as handle:
            handle.write(body.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)

    def is_empty(self) -> bool:
        return not any(self.read(kind) for kind in dataschema.FILES)


# --- the old history in user.db (table `queries`), moved by `wort migrate-history` ---------------------


def legacy_count(db_path: Path) -> int:
    """How many rows the old `queries` table of user.db holds (0 if there is none)."""
    if not Path(db_path).exists():
        return 0
    try:
        with contextlib.closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as conn:
            return conn.execute("SELECT COUNT(*) FROM queries").fetchone()[0]
    except sqlite3.Error:
        return 0


def legacy_kind(text: str, found: bool) -> bool:
    """Without a dictionary: a not-found query of three or more words was a sentence."""
    return not found and len(text.split()) >= MIN_SENTENCE_WORDS


class Migrated(NamedTuple):
    words: int  # added
    sentences: int  # added
    skipped: int  # rows that break the storage rules
    present: int  # rows that were already in the files


def migrate(db_path: Path, store: HistoryStore, is_sentence: Callable[[str, bool], bool] = legacy_kind) -> Migrated:
    """Merge the old query log into the two files.

    `is_sentence(text, found)` decides the kind; the command passes the same test the live lookup uses (the old log
    saved a sentence as found whenever one of its words was). Older entries go in front of newer ones in time
    order, entries that are already there are not added again, so it can be run at any time and twice. The old
    table is not touched.
    """
    with contextlib.closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as conn:
        rows = conn.execute("SELECT query, found, ts FROM queries ORDER BY id").fetchall()
    entries: list[Entry] = []
    skipped = 0
    for query, found, ts in rows:
        text = " ".join(str(query).split())
        kind = "sentence" if is_sentence(text, bool(found)) else "word"
        try:
            when = datetime.fromisoformat(ts)
            when = when.astimezone() if when.tzinfo is None else when  # the old log used local time
            entries.append(dataschema.make_entry(kind, text, bool(found), when.astimezone(timezone.utc)))
        except (Invalid, ValueError):
            skipped += 1
    before = {kind: len(store.read(kind)) for kind in dataschema.FILES}
    store.merge(entries)
    added = {kind: len(store.read(kind)) - before[kind] for kind in dataschema.FILES}
    present = len(entries) - sum(added.values())
    return Migrated(added["word"], added["sentence"], skipped, present)
