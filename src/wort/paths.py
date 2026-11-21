"""Where wort keeps its data: databases in the XDG data dir (WORT_HOME), history in the data repository (WORT_DATA_REPO)."""

import os
from pathlib import Path


def data_dir() -> Path:
    if override := os.environ.get("WORT_HOME"):
        path = Path(override)
    else:
        base = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
        path = Path(base) / "wort"
    path.mkdir(parents=True, exist_ok=True)
    return path


def dictionary_db() -> Path:
    return data_dir() / "dictionary.db"


def dictionary_uk_db() -> Path:
    """Ukrainian translations (German Wiktionary); separate so either dump can be re-imported alone."""
    return data_dir() / "dictionary-uk.db"


def dictionary_de_db() -> Path:
    """German definitions (German Wiktionary, the same dump as the Ukrainian file), for the lookup's explanation."""
    return data_dir() / "dictionary-de.db"


def dictionary_en_uk_db() -> Path:
    """English -> Ukrainian translation tables (English Wiktionary), for words the direct file lacks."""
    return data_dir() / "dictionary-en-uk.db"


def user_db() -> Path:
    return data_dir() / "user.db"


def data_repo() -> Path:
    """The git checkout that holds `words.jsonl` and `sentences.jsonl` (the query history); `wort sync` pushes it."""
    if override := os.environ.get("WORT_DATA_REPO"):
        return Path(override).expanduser()
    return Path.home() / "wort-data"
