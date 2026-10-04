"""Type a specific form: plural, genitive, conjugation, Partizip II, comparison."""

from __future__ import annotations

import random

from lernen.dictionary import grammar as g
from lernen.dictionary.lookup import Entry
from lernen.exercises.base import Exercise, ExerciseType, Result, best_match, strip_pronoun

PERSON_LABEL = {"ich": "ich", "du": "du", "er": "er/sie/es", "wir": "wir", "ihr": "ihr", "sie": "sie/Sie"}


def candidates(entry: Entry) -> list[tuple[str, str, list[str]]]:
    """(prompt, display answer, accepted answers)."""
    out: list[tuple[str, str, list[str]]] = []
    if entry.pos == "noun":
        art = g.GENDER_ARTICLE.get(entry.gender or "", "")
        if (pl := g.plural(entry)) and pl != "-":
            out.append((f"Plural:  {art} {entry.lemma} → die ___", pl, [pl]))
        if entry.gender in ("m", "n") and (gen := g.noun_form(entry, "genitive", "singular")):
            out.append((f"Genitiv:  {art} {entry.lemma} → des ___", gen, [gen]))
        if (dat := g.noun_form(entry, "dative", "plural")) and dat != g.plural(entry):
            out.append((f"Dativ Plural:  {entry.lemma} → mit den ___", dat, [dat]))
    elif entry.pos == "verb":
        for person in ("du", "er"):
            if form := g.present(entry, person):
                out.append((f"Präsens, {PERSON_LABEL[person]}:  {entry.lemma} → {person} ___", form, [form]))
        for person in ("ich", "wir"):
            if form := g.preterite(entry, person):
                out.append((f"Präteritum, {PERSON_LABEL[person]}:  {entry.lemma} → {person} ___", form, [form]))
        if p2 := g.participle2(entry):
            aux = g.perfect_aux(entry, "er")
            out.append((f"Perfekt:  {entry.lemma} → er ___ ___", f"{aux} {p2}", [f"{aux} {p2}"]))
    elif entry.pos == "adj":
        if comp := g.comparative(entry):
            out.append((f"Komparativ:  {entry.lemma} → ___", comp, [comp]))
        if sup := g.superlative(entry):
            bare = sup.removeprefix("am ")
            out.append((f"Superlativ:  {entry.lemma} → am ___", sup, [bare, sup]))
    return out


def make(entry: Entry, rng: random.Random) -> Exercise:
    prompt, shown, accepted = rng.choice(candidates(entry))

    def check(answer: str) -> Result:
        verdict, feedback, _ = best_match(strip_pronoun(answer), accepted)
        return Result(verdict, shown, feedback)

    return Exercise("forms", entry, prompt, check, hint=entry.glosses[0] if entry.glosses else "")


TYPE = ExerciseType("forms", "Forms", available=lambda e: bool(candidates(e)), make=make, weight=1.2)
