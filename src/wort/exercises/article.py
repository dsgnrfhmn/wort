"""der / die / das."""

from __future__ import annotations

import random

from wort.dictionary import grammar as g
from wort.dictionary.lookup import Entry
from wort.exercises.base import Exercise, ExerciseType, choice_checker


def make(entry: Entry, rng: random.Random) -> Exercise:
    right = g.GENDER_ARTICLE[entry.gender]
    hint = entry.glosses[0] if entry.glosses else ""
    return Exercise(
        "article", entry, f"Article:  ___ {entry.lemma}", choice_checker(right), hint=hint, choices=["der", "die", "das"]
    )


TYPE = ExerciseType(
    "article", "Article", available=lambda e: e.pos == "noun" and e.gender in g.GENDER_ARTICLE, make=make, weight=1.0
)
