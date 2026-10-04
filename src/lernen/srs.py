"""SM-2 spaced repetition and a per-word mastery score."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

QUALITY = {"correct": 5, "almost": 3, "wrong": 1}
RESULT_SCORE = {"correct": 1.0, "almost": 0.5, "wrong": 0.0}


@dataclass
class SrsState:
    ease: float = 2.5
    interval: float = 0.0  # days
    reps: int = 0
    due: datetime | None = None


def review(state: SrsState, verdict: str, now: datetime) -> SrsState:
    q = QUALITY[verdict]
    ease = max(1.3, state.ease + 0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    if q < 3:
        reps, interval = 0, 0.0  # see it again this session/day
    else:
        reps = state.reps + 1
        if reps == 1:
            interval = 1.0
        elif reps == 2:
            interval = 3.0
        else:
            interval = round(state.interval * ease, 1)
        if q == 3:
            interval = max(1.0, interval * 0.6)
    return SrsState(ease=ease, interval=interval, reps=reps, due=now + timedelta(days=interval))


def mastery(verdicts_newest_first: list[str], interval: float) -> int:
    """0–100: recency-weighted accuracy of the last 10 answers, scaled by how well it is spaced."""
    recent = verdicts_newest_first[:10]
    if not recent:
        return 0
    weights = [0.85**i for i in range(len(recent))]
    accuracy = sum(w * RESULT_SCORE[v] for w, v in zip(weights, recent)) / sum(weights)
    spacing = 0.7 + 0.3 * min(interval / 21.0, 1.0)
    return round(100 * accuracy * spacing)
