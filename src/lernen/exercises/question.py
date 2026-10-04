"""Multiple-choice questions about a word's grammar."""

from __future__ import annotations

import random
from collections.abc import Callable

from lernen.dictionary import grammar as g
from lernen.dictionary.lookup import Entry
from lernen.exercises.base import Exercise, ExerciseType, choice_checker, shuffled_choices

_UMLAUT = {"a": "ä", "o": "ö", "u": "ü", "au": "äu"}


def umlauted(word: str) -> str:
    """Umlaut the last a/o/u/au of a word: Haus -> Häus, Buch -> Büch."""
    lower = word.lower()
    for i in range(len(word) - 1, -1, -1):
        if lower[i] in "aou":
            if lower[i] == "u" and i > 0 and lower[i - 1] == "a":
                return word[:i - 1] + ("Ä" if word[i - 1].isupper() else "ä") + word[i:]
            repl = _UMLAUT[lower[i]]
            return word[:i] + (repl.upper() if word[i].isupper() else repl) + word[i + 1:]
    return word


def plural_distractors(lemma: str) -> list[str]:
    base = lemma[:-1] if lemma.endswith("e") else lemma
    uml = umlauted(lemma)
    return [lemma + "e", lemma + "en" if not lemma.endswith("e") else lemma + "n", lemma + "er",
            lemma + "s", uml + "e", uml + "er", lemma, base + "en"]


def participle_distractors(entry: Entry) -> list[str]:
    stem = g.stem_of(entry)
    lemma = entry.lemma
    return ["ge" + stem + "t", "ge" + lemma, stem + "t", "ge" + stem + "en", lemma[:-2] + "t" if lemma.endswith("en") else lemma]


def _questions(entry: Entry) -> list[Callable[[random.Random], Exercise]]:
    qs: list[Callable[[random.Random], Exercise]] = []
    hint = entry.glosses[0] if entry.glosses else ""

    def mc(prompt: str, correct: str, choices: list[str]) -> Callable[[random.Random], Exercise]:
        return lambda rng: Exercise("question", entry, prompt, choice_checker(correct), hint=hint, choices=choices)

    def mc_shuffled(prompt: str, correct: str, distractors: list[str]) -> Callable[[random.Random], Exercise]:
        return lambda rng: Exercise(
            "question", entry, prompt, choice_checker(correct), hint=hint,
            choices=shuffled_choices(correct, distractors, rng),
        )

    if entry.pos == "verb":
        if entry.aux in ("haben", "sein"):
            qs.append(mc(f"Which auxiliary verb does «{entry.lemma}» take in the Perfekt?", entry.aux, ["haben", "sein"]))
        qs.append(mc(f"Is «{entry.lemma}» a separable verb?",
                     "trennbar" if entry.separable else "untrennbar", ["trennbar", "untrennbar"]))
        if entry.conj in ("weak", "strong", "irregular"):
            qs.append(mc(f"«{entry.lemma}» is conjugated…",
                         "regelmäßig" if entry.conj == "weak" else "unregelmäßig", ["regelmäßig", "unregelmäßig"]))
        if p2 := g.participle2(entry):
            qs.append(mc_shuffled(f"Partizip II of «{entry.lemma}»?", p2, participle_distractors(entry)))
    elif entry.pos == "noun":
        if pl := g.plural(entry):
            qs.append(mc_shuffled(f"Plural of «{entry.lemma}»?", pl, plural_distractors(entry.lemma)))
    elif entry.pos == "adj":
        if comp := g.comparative(entry):
            qs.append(mc_shuffled(f"Komparativ of «{entry.lemma}»?", comp,
                                  [entry.lemma + "er", umlauted(entry.lemma) + "er", "mehr " + entry.lemma]))
    return qs


def make(entry: Entry, rng: random.Random) -> Exercise:
    return rng.choice(_questions(entry))(rng)


TYPE = ExerciseType("question", "Questions", available=lambda e: bool(_questions(e)), make=make, weight=0.8)
