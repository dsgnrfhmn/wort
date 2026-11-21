"""Schema and validator for wort's history files: `words.jsonl` and `sentences.jsonl`.

Standard library only, and self-contained: this exact file is copied into the data repository as
`validate.py` (`scripts/init_data_repo.py`), so CI and any other writer check the same rules wort does.
`wort sync` refuses to run when the copy in the data repository differs from this file.

One line per entry, a JSON object with exactly these keys:

    words.jsonl      {"text": "Haus", "ts": "2026-11-21T15:05:00Z", "found": true}
    sentences.jsonl  {"text": "Ich gehe nach Hause.", "ts": "2026-11-21T15:06:00Z"}

The rules are an allowlist: only letters, digits, a plain space and a few punctuation marks are
accepted, so no command, markup, template, path, link or control sequence can be stored. A line that
breaks a rule is rejected as a whole, never repaired. Run `python validate.py [DIR]` to check a directory.
"""

from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

WORDS_FILE = "words.jsonl"
SENTENCES_FILE = "sentences.jsonl"
FILES = {"word": WORDS_FILE, "sentence": SENTENCES_FILE}
KEYS = {"word": {"text", "ts", "found"}, "sentence": {"text", "ts"}}

# every path that may exist in the data repository (anything else is rejected)
REPO_FILES = {WORDS_FILE, SENTENCES_FILE, "validate.py", "README.md", ".gitattributes", ".gitignore", ".github/workflows/validate.yml"}

MAX_TEXT = {"word": 60, "sentence": 500}  # characters; the sentence limit matches the translator's
MAX_LINES = {"word": 100_000, "sentence": 20_000}
MAX_LINE_BYTES = 4096
MAX_FILE_BYTES = 16 * 1024 * 1024

PUNCTUATION = frozenset(".,:!?'’‘\"„“”«»‹›()-–—…")
OPENERS = frozenset("\"„“«‹'‘(")  # besides a letter or a digit, an entry may start with these
OPTION = re.compile(r"(?<!\S)-{1,2}[^\W\d_]")  # a token like --help or -rf: a command-line option, not a word
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class Invalid(ValueError):
    """A line, a file or a directory breaks the rules; the message says where and why."""


@dataclass(frozen=True)
class Entry:
    kind: str  # "word" or "sentence"
    text: str
    found: bool  # always True for a sentence
    ts: datetime  # timezone-aware, UTC, whole seconds


def text_problem(text: object, kind: str) -> str | None:
    """Why `text` may not be stored as a `kind`, or None when it may."""
    if not isinstance(text, str):
        return "text must be a string"
    if not text:
        return "text is empty"
    if len(text) > MAX_TEXT[kind]:
        return f"text is longer than {MAX_TEXT[kind]} characters"
    if not unicodedata.is_normalized("NFC", text):
        return "text is not NFC-normalized"
    if text != text.strip(" ") or "  " in text:
        return "text has leading, trailing or repeated spaces"
    for ch in text:
        category = unicodedata.category(ch)
        if category[0] in "LMN" or ch == " " or ch in PUNCTUATION:
            continue
        return f"character not allowed: {ch!r}"
    if not (unicodedata.category(text[0])[0] in "LN" or text[0] in OPENERS):
        return f"text may not start with {text[0]!r}"
    if not any(unicodedata.category(ch)[0] in "LN" for ch in text):
        return "text has no letter or digit"
    if re.search(r":[^\W\d_]", text):
        return "':' directly followed by a letter (looks like a link or a command)"
    if re.search(r"(?i)\bwww\.", text):
        return "looks like a web address"
    if OPTION.search(text):
        return "a word starting with '-' looks like a command-line option"
    return None


def make_entry(kind: str, text: str, found: bool = True, when: datetime | None = None) -> Entry:
    """A checked entry, ready to be written. Raises Invalid."""
    if kind not in FILES:
        raise Invalid(f"unknown kind: {kind!r}")
    if problem := text_problem(text, kind):
        raise Invalid(problem)
    when = (when or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    return Entry(kind, text, bool(found) if kind == "word" else True, when)


def dump_line(entry: Entry) -> str:
    data: dict[str, object] = {"text": entry.text, "ts": entry.ts.strftime(TIMESTAMP_FORMAT)}
    if entry.kind == "word":
        data["found"] = entry.found
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _reject_constant(name: str):
    raise ValueError(f"{name} is not allowed")


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate key")
    return dict(pairs)


def parse_line(line: str, kind: str) -> Entry:
    """One line of a history file. Raises Invalid."""
    if len(line.encode("utf-8", errors="replace")) > MAX_LINE_BYTES:
        raise Invalid("line is too long")
    if not line.isprintable():
        raise Invalid("line has control or invisible characters")
    try:
        data = json.loads(line, parse_constant=_reject_constant, object_pairs_hook=_no_duplicate_keys)
    except ValueError as exc:
        raise Invalid(f"not valid JSON ({exc})") from None
    if not isinstance(data, dict):
        raise Invalid("not a JSON object")
    if set(data) != KEYS[kind]:
        raise Invalid(f"keys must be exactly {sorted(KEYS[kind])}")
    if problem := text_problem(data["text"], kind):
        raise Invalid(problem)
    stamp = data["ts"]
    if not (isinstance(stamp, str) and TIMESTAMP.fullmatch(stamp)):
        raise Invalid("ts must look like 2026-11-21T15:05:00Z")
    try:
        when = datetime.strptime(stamp, TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        raise Invalid("ts is not a real date") from None
    found = True
    if kind == "word":
        found = data["found"]
        if not isinstance(found, bool):
            raise Invalid("found must be true or false")
    return Entry(kind, data["text"], found, when)


def check_bytes(data: bytes, kind: str) -> list[Entry]:
    """The whole content of a history file. All or nothing; raises Invalid naming the first bad line."""
    if len(data) > MAX_FILE_BYTES:
        raise Invalid("file is too large")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise Invalid("file is not valid UTF-8") from None
    if not text:
        return []
    if not text.endswith("\n"):
        raise Invalid("the last line has no newline")
    lines = text.split("\n")[:-1]
    if len(lines) > MAX_LINES[kind]:
        raise Invalid(f"more than {MAX_LINES[kind]} lines")
    entries = []
    for number, line in enumerate(lines, 1):
        try:
            entries.append(parse_line(line, kind))
        except Invalid as exc:
            raise Invalid(f"line {number}: {exc}") from None
    return entries


def check_tree(root: Path) -> dict[str, int]:
    """A whole data repository checkout: only allowed regular files, valid history files.

    Returns the entry count per file. Raises Invalid.
    """
    root = Path(root)
    seen: set[str] = set()
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != ".git"]
        for name in files:
            path = Path(folder, name)
            relative = path.relative_to(root).as_posix()
            if relative not in REPO_FILES:
                raise Invalid(f"{relative}: not an allowed file")
            if path.is_symlink() or not path.is_file():
                raise Invalid(f"{relative}: must be a regular file")
            seen.add(relative)
    counts = {}
    for kind, name in FILES.items():
        if name in seen:
            try:
                counts[name] = len(check_bytes((root / name).read_bytes(), kind))
            except Invalid as exc:
                raise Invalid(f"{name}: {exc}") from None
    return counts


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    root = Path(argv[0]) if argv else Path(".")
    try:
        counts = check_tree(root)
    except Invalid as exc:
        print(f"validate.py: {exc}", file=sys.stderr)
        return 1
    print("OK: " + ", ".join(f"{count} in {name}" for name, count in counts.items()) if counts else "OK: no history files yet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
