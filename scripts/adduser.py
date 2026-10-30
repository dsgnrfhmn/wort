"""Create a web user (there is no signup). Usage: python scripts/adduser.py NAME  (password is prompted)."""

from __future__ import annotations

import getpass
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from wort import paths  # noqa: E402

from app import auth  # noqa: E402
from app.db import WebStore  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not argv[1].strip():
        print(__doc__, file=sys.stderr)
        return 2
    name = argv[1].strip()
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Repeat: "):
        print("Passwords differ.", file=sys.stderr)
        return 1
    try:
        pw_hash = auth.hash_password(password)
        user = WebStore(paths.data_dir() / "web.db").create_user(name, pw_hash)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except sqlite3.IntegrityError:
        print(f"User {name!r} already exists.", file=sys.stderr)
        return 1
    print(f"Created user {user.name!r} (id {user.id}).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
