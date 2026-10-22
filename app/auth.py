"""Accounts: argon2 password hashes, opaque session tokens (stored hashed), login throttle.

There is no signup; users are created with `scripts/adduser.py`.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from datetime import datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

SESSION_COOKIE = "wort_session"
SESSION_DAYS = 14
MIN_PASSWORD = 12
MAX_FIELD = 200  # caps both name and password before any hashing work

_hasher = PasswordHasher()
# Verified against when the user does not exist, so both cases cost the same.
_DUMMY_HASH = _hasher.hash("wort-dummy-password")


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"password must be at least {MIN_PASSWORD} characters")
    if len(password) > MAX_FIELD:
        raise ValueError(f"password must be at most {MAX_FIELD} characters")
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    if len(password) > MAX_FIELD:
        return False
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def session_expiry(now: datetime) -> datetime:
    return now + timedelta(days=SESSION_DAYS)


class LoginThrottle:
    """At most `limit` failed logins per name within `window` seconds (in memory, per process)."""

    def __init__(self, limit: int = 5, window: float = 300.0, clock=time.monotonic):
        self.limit, self.window, self.clock = limit, window, clock
        self._failures: dict[str, list[float]] = {}

    def _recent(self, key: str) -> list[float]:
        cutoff = self.clock() - self.window
        recent = [t for t in self._failures.get(key, []) if t > cutoff]
        self._failures[key] = recent
        return recent

    def blocked(self, key: str) -> bool:
        return len(self._recent(key)) >= self.limit

    def fail(self, key: str) -> None:
        self._recent(key).append(self.clock())

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)
