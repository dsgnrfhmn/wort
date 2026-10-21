"""Word score and scheduling for the web practice (pure functions, no I/O).

Every word has up to three skill sub-scores on a 0-10 scale:

    translation  de<->en meaning (flashcards, "Was bedeutet ...?")
    form         article, plural, case and verb forms
    usage        the word used in a written sentence

A verdict moves the matching skill by DELTA[verdict]: correct +1, almost 0,
wrong -1, clamped to 0-10. A skill that was never answered stays None. The word
score shown in the UI is the rounded mean of the answered skills (None while
there are none). `next_due` doubles with every consecutive correct answer
(1, 2, 4, ... days, capped at MAX_INTERVAL_DAYS) and falls back to today after a
wrong one.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

SKILLS = ("translation", "form", "usage")
DELTA = {"correct": 1, "almost": 0, "wrong": -1}
MAX_SCORE = 10
MAX_INTERVAL_DAYS = 32


@dataclass(frozen=True)
class WordState:
    translation: int | None = None
    form: int | None = None
    usage: int | None = None
    streak: int = 0  # consecutive correct answers


def word_score(state: WordState) -> int | None:
    values = [v for v in (state.translation, state.form, state.usage) if v is not None]
    if not values:
        return None
    return round(sum(values) / len(values))


def apply_verdict(state: WordState, skill: str, verdict: str) -> WordState:
    """Return the new state after one graded answer."""
    if skill not in SKILLS:
        raise ValueError(f"unknown skill: {skill!r}")
    if verdict not in DELTA:
        raise ValueError(f"unknown verdict: {verdict!r}")
    current = getattr(state, skill)
    base = 0 if current is None else current
    new = min(MAX_SCORE, max(0, base + DELTA[verdict]))
    if verdict == "correct":
        streak = state.streak + 1
    elif verdict == "wrong":
        streak = 0
    else:
        streak = state.streak
    return replace(state, **{skill: new}, streak=streak)


def score_delta(before: WordState, after: WordState) -> int:
    """Change of the displayed word score; a word without a score counts as 0."""
    return (word_score(after) or 0) - (word_score(before) or 0)


def next_due(state: WordState, verdict: str, now: datetime) -> datetime:
    """When the word should come up again."""
    if verdict == "wrong" or state.streak == 0:
        return now
    days = min(2 ** (state.streak - 1), MAX_INTERVAL_DAYS)
    return now + timedelta(days=days)


def level(score: int | None) -> str:
    """Bucket for the score chip: new / weak (0-3) / medium (4-6) / strong (7-10)."""
    if score is None:
        return "new"
    if score <= 3:
        return "weak"
    if score <= 6:
        return "medium"
    return "strong"
