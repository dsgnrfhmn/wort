"""Exercise model and answer comparison shared by all exercise types."""

from __future__ import annotations

import random
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from lernen.dictionary.lookup import Entry
from lernen.text import levenshtein, normalize

VERDICT_ORDER = {"wrong": 0, "almost": 1, "correct": 2}


@dataclass
class Result:
    verdict: str  # correct | almost | wrong
    expected: str
    feedback: str = ""

    @property
    def ok(self) -> bool:
        return self.verdict == "correct"


@dataclass
class Exercise:
    kind: str
    entry: Entry
    prompt: str
    checker: Callable[[str], Result]
    hint: str = ""
    choices: list[str] | None = None
    slow: bool = False  # checking may hit the network (local LanguageTool)

    def check(self, answer: str) -> Result:
        answer = answer.strip()
        if self.choices and answer.isdigit() and 1 <= int(answer) <= len(self.choices):
            answer = self.choices[int(answer) - 1]
        return self.checker(answer)


@dataclass
class ExerciseType:
    kind: str
    label: str
    available: Callable[[Entry], bool]
    make: Callable[[Entry, random.Random], Exercise]
    weight: float = 1.0
    extra: dict = field(default_factory=dict)


def compare(answer: str, expected: str) -> tuple[str, str]:
    """Compare one answer to one expected string -> (verdict, feedback)."""
    a = unicodedata.normalize("NFC", " ".join(answer.split()))
    e = unicodedata.normalize("NFC", expected)
    if a == e:
        return "correct", ""
    if a.lower() == e.lower():
        if e[:1].isupper() and not a[:1].isupper():
            return "correct", "Nouns are capitalized."
        return "correct", ""
    if normalize(a) == normalize(e):
        return "correct", f"Correct; with umlauts/ß: {e}"
    na, ne = normalize(a), normalize(e)
    if len(ne) >= 4 and levenshtein(na, ne) <= 1:
        return "almost", f"Almost — correct: {e}"
    return "wrong", ""


def best_match(answer: str, expected: Iterable[str]) -> tuple[str, str, str]:
    """Best (verdict, feedback, matched) over several acceptable answers."""
    best = ("wrong", "", "")
    for option in expected:
        verdict, feedback = compare(answer, option)
        if VERDICT_ORDER[verdict] > VERDICT_ORDER[best[0]]:
            best = (verdict, feedback, option)
            if verdict == "correct":
                break
    return best


def strip_pronoun(answer: str) -> str:
    words = answer.split()
    if len(words) > 1 and words[0].lower() in {"ich", "du", "er", "sie", "es", "wir", "ihr"}:
        return " ".join(words[1:])
    return answer


def choice_checker(correct: str) -> Callable[[str], Result]:
    def check(answer: str) -> Result:
        verdict = "correct" if normalize(answer) == normalize(correct) else "wrong"
        return Result(verdict, correct)

    return check


def shuffled_choices(correct: str, distractors: Iterable[str], rng: random.Random, n: int = 4) -> list[str]:
    pool = [d for d in dict.fromkeys(distractors) if d and normalize(d) != normalize(correct)]
    rng.shuffle(pool)
    choices = [correct, *pool[: n - 1]]
    rng.shuffle(choices)
    return choices
