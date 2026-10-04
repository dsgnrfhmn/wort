"""Write a sentence using the word in a requested form; checked for the form and (optionally) grammar."""

from __future__ import annotations

import random
import re
from collections.abc import Callable

from lernen.dictionary import grammar as g
from lernen.dictionary.lookup import Entry
from lernen.exercises import grammar_check
from lernen.exercises.base import Exercise, ExerciseType, Result
from lernen.text import normalize

PERSON_LABEL = {"ich": "ich", "du": "du", "er": "er/sie/es", "wir": "wir"}

Checker = Callable[[str], list[grammar_check.Issue] | None]


def targets(entry: Entry) -> list[tuple[str, list[str]]]:
    """(task description, words that must appear in the sentence)."""
    out: list[tuple[str, list[str]]] = []
    if entry.pos == "verb":
        for person in ("ich", "du", "er", "wir"):
            if form := g.present(entry, person):
                out.append((f"Präsens, {PERSON_LABEL[person]}", form.split()))
            if form := g.preterite(entry, person):
                out.append((f"Präteritum, {PERSON_LABEL[person]}", form.split()))
        if p2 := g.participle2(entry):
            for person in ("ich", "er"):
                out.append((f"Perfekt, {PERSON_LABEL[person]}", [g.perfect_aux(entry, person), p2]))
    elif entry.pos == "noun":
        if pl := g.plural(entry):
            out.append(("Plural", [pl]))
        if (dat := g.noun_form(entry, "dative", "plural")) and dat:
            out.append(("Dativ Plural", [dat]))
        if entry.gender in g.ARTICLES and (acc := g.noun_form(entry, "accusative", "singular")):
            out.append(("Akkusativ Singular, with the definite article", [g.ARTICLES[entry.gender]["accusative"], acc]))
    elif entry.pos == "adj":
        if comp := g.comparative(entry):
            out.append(("Komparativ", [comp]))
        if sup := g.superlative(entry):
            out.append(("Superlativ", sup.split()))
    else:
        out.append(("any form", [entry.lemma]))
    return out


def _tokens(sentence: str) -> list[str]:
    return [normalize(t) for t in re.findall(r"[\wäöüÄÖÜß]+", sentence)]


def make(entry: Entry, rng: random.Random, checker: Checker = grammar_check.check) -> Exercise:
    task, required = rng.choice(targets(entry))
    expected = " … ".join(required)

    def check(answer: str) -> Result:
        tokens = _tokens(answer)
        missing = [w for w in required if normalize(w) not in tokens]
        if len(tokens) < 3:
            return Result("wrong", expected, "Write a full sentence (at least 3 words).")
        if missing:
            return Result("wrong", expected, f"Missing the required form: {' '.join(missing)}")
        issues = checker(answer)
        if issues is None:
            return Result("correct", expected, "The form is correct. (Grammar was not checked: LanguageTool is not running.)")
        if issues:
            lines = []
            for issue in issues[:3]:
                fragment = answer[issue.offset: issue.offset + issue.length]
                fix = f" → {', '.join(issue.replacements)}" if issue.replacements else ""
                lines.append(f"«{fragment}»: {issue.message}{fix}")
            return Result("almost", expected, "The form is correct, but there are grammar remarks:\n" + "\n".join(lines))
        return Result("correct", expected, "Form and grammar are correct.")

    gloss = entry.glosses[0] if entry.glosses else ""
    prompt = f"Write a sentence with «{entry.lemma}» in the form: {task}"
    return Exercise("sentence", entry, prompt, check, hint=gloss, slow=True)


TYPE = ExerciseType("sentence", "Sentence", available=lambda e: bool(e.glosses), make=make, weight=0.7)
