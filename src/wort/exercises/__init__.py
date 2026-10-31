"""Exercise registry and session building."""

from __future__ import annotations

import random

from wort.dictionary.lookup import Dictionary, Entry
from wort.exercises import article, forms, question, sentence, translate
from wort.exercises.base import Exercise, ExerciseType, Result
from wort.store import Store, Word

TYPES: dict[str, ExerciseType] = {t.kind: t for t in (translate.TYPE, article.TYPE, forms.TYPE, question.TYPE, sentence.TYPE)}
LABELS = {kind: t.label for kind, t in TYPES.items()}

__all__ = ["Exercise", "Result", "TYPES", "LABELS", "pick_exercise", "build_session"]


def pick_exercise(entry: Entry, accuracy: dict[str, float], rng: random.Random, kinds: set[str] | None = None) -> Exercise:
    """Choose an exercise type for the word, favouring types it is weak at or has not seen."""
    options = [t for t in TYPES.values() if (kinds is None or t.kind in kinds) and t.available(entry)]
    if not options:
        options = [TYPES["translate"]]
    weights = [t.weight * (1.0 + 2.0 * (1.0 - accuracy.get(t.kind, 0.0))) for t in options]
    chosen = rng.choices(options, weights=weights)[0]
    return chosen.make(entry, rng)


def build_session(
    store: Store,
    dictionary: Dictionary,
    limit: int = 10,
    rng: random.Random | None = None,
    kinds: set[str] | None = None,
    word_ids: set[int] | None = None,
) -> list[tuple[Word, Exercise]]:
    rng = rng or random.Random()
    words = store.session_words(limit=10_000)
    if word_ids is not None:
        words = [w for w in words if w.id in word_ids]
    session = []
    for word in words:
        entry = dictionary.find_lemma(word.lemma, word.pos)
        if entry is None:
            continue
        if kinds == {"sentence"} and not sentence.TYPE.available(entry):
            continue
        session.append((word, pick_exercise(entry, store.stats(word).by_exercise, rng, kinds)))
        if len(session) >= limit:
            break
    return session
