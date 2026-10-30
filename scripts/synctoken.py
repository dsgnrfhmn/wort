"""Manage the write-only sync tokens of the CLI.  Run on the server.

    python scripts/synctoken.py create USER [LABEL]   prints the token ONCE; put it in a file (mode 600) on the CLI machine
    python scripts/synctoken.py list USER
    python scripts/synctoken.py revoke USER TOKEN_ID

A token can only push the CLI's words/history into USER's list. It cannot read anything or sign in.
"""

from __future__ import annotations

import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from wort import paths  # noqa: E402

from app.db import WebStore  # noqa: E402
from app.sync_app import TOKEN_PREFIX, hash_token  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) < 3 or argv[1] not in {"create", "list", "revoke"}:
        print(__doc__, file=sys.stderr)
        return 2
    store = WebStore(paths.data_dir() / "web.db")
    found = store.user_by_name(argv[2])
    if found is None:
        print(f"No such user: {argv[2]!r}", file=sys.stderr)
        return 1
    user = found[0]
    if argv[1] == "create":
        token = TOKEN_PREFIX + secrets.token_urlsafe(32)
        tid = store.create_sync_token(user.id, hash_token(token), " ".join(argv[3:]))
        print(f"Token {tid} for {user.name}. Shown once, store it now (file mode 600) on the CLI machine:\n{token}")
    elif argv[1] == "list":
        for t in store.sync_tokens(user.id):
            state = f"revoked {t['revoked_at']}" if t["revoked_at"] else f"last used {t['last_used'] or 'never'}"
            print(f"{t['id']}\t{t['label'] or '-'}\tcreated {t['created_at']}\t{state}")
    else:
        if len(argv) != 4 or not argv[3].isdigit():
            print(__doc__, file=sys.stderr)
            return 2
        print("Revoked." if store.revoke_sync_token(user.id, int(argv[3])) else "No such active token.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
