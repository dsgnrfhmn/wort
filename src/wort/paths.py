"""Where wort keeps its data (XDG data dir, overridable with WORT_HOME)."""

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


def config_dir() -> Path:
    """Settings (sync endpoint) and, by convention, the token file; never inside the data dir's database."""
    if override := os.environ.get("WORT_CONFIG_HOME"):
        return Path(override)
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "wort"


def dictionary_db() -> Path:
    return data_dir() / "dictionary.db"


def dictionary_uk_db() -> Path:
    """Ukrainian translations (German Wiktionary); separate so either dump can be re-imported alone."""
    return data_dir() / "dictionary-uk.db"


def dictionary_en_uk_db() -> Path:
    """English -> Ukrainian translation tables (English Wiktionary), for words the direct file lacks."""
    return data_dir() / "dictionary-en-uk.db"


def user_db() -> Path:
    return data_dir() / "user.db"
