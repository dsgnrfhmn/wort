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


def dictionary_db() -> Path:
    return data_dir() / "dictionary.db"


def user_db() -> Path:
    return data_dir() / "user.db"
