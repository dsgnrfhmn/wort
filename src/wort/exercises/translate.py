"""Translate EN→DE or DE→EN."""

from __future__ import annotations

import random

from wort.dictionary import grammar as g
from wort.dictionary.importer import gloss_keys
from wort.dictionary.lookup import Entry
from wort.exercises.base import Exercise, ExerciseType, Result, best_match, compare


def _german_display(entry: Entry) -> str:
    if entry.pos == "noun" and entry.gender in g.GENDER_ARTICLE:
        return f"{g.GENDER_ARTICLE[entry.gender]} {entry.lemma}"
    return entry.lemma


def make(entry: Entry, rng: random.Random) -> Exercise:
    if rng.random() < 0.5:
        return _de_to_en(entry)
    return _en_to_de(entry)


def _de_to_en(entry: Entry) -> Exercise:
    accepted = [k for gloss in entry.glosses for k in gloss_keys(gloss)]

    def check(answer: str) -> Result:
        cleaned = answer.lower().strip()
        for prefix in ("to ", "a ", "an ", "the "):
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):]
        verdict, feedback, _ = best_match(cleaned, accepted)
        return Result(verdict, "; ".join(entry.glosses[:3]), feedback)

    return Exercise("translate", entry, f"Translate to English:  {_german_display(entry)}", check)


def _en_to_de(entry: Entry) -> Exercise:
    expected = _german_display(entry)

    def check(answer: str) -> Result:
        words = answer.split()
        article = None
        if entry.pos == "noun" and len(words) > 1 and words[0].lower() in ("der", "die", "das"):
            article, answer = words[0].lower(), " ".join(words[1:])
        verdict, feedback = compare(answer, entry.lemma)
        if verdict != "wrong" and entry.pos == "noun" and entry.gender in g.GENDER_ARTICLE:
            right = g.GENDER_ARTICLE[entry.gender]
            if article is None:
                feedback = (feedback + " " if feedback else "") + f"Don't forget the article: {expected}"
            elif article != right:
                verdict, feedback = "almost", f"The word is right, but the article is {right}."
        return Result(verdict, expected, feedback)

    hint = "noun: include the article" if entry.pos == "noun" else ""
    return Exercise("translate", entry, f"Translate to German:  {'; '.join(entry.glosses[:2])}", check, hint=hint)


TYPE = ExerciseType("translate", "Translation", available=lambda e: bool(e.glosses), make=make, weight=1.5)
