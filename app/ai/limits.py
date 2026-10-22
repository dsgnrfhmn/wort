"""Per-user daily cap on AI calls, enforced on the server before any request is made."""

from __future__ import annotations

from datetime import datetime

from app.db import WebStore


class LimitReached(RuntimeError):
    """The user used up today's AI calls."""


class DailyLimit:
    def __init__(self, store: WebStore, cap: int):
        self.store, self.cap = store, cap

    def remaining(self, user_id: int, now: datetime) -> int:
        return max(0, self.cap - self.store.ai_calls_today(user_id, now.date().isoformat()))

    def take(self, user_id: int, now: datetime) -> None:
        """Count one call; raises LimitReached when the cap is spent (failed calls count too)."""
        if self.remaining(user_id, now) <= 0:
            raise LimitReached()
        self.store.ai_count_call(user_id, now.date().isoformat())
