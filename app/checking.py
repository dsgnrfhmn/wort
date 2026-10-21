"""Sentence check: required-form test + LanguageTool corrections.

Uses the existing loopback-only client; if LanguageTool is unreachable the result
says so explicitly (never a fake "no errors").
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field

from wort import sanitize
from wort.dictionary.lookup import Entry
from wort.exercises import grammar_check
from wort.exercises.grammar_check import Issue
from wort.exercises.sentence import _tokens, targets
from wort.text import normalize

MAX_SENTENCE = 300

Checker = Callable[[str], list[Issue] | None]


@dataclass
class Remark:
    fragment: str
    message: str
    replacements: list[str]


@dataclass
class CheckResult:
    sentence: str
    corrected: str
    remarks: list[Remark] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    checked: bool = True  # False -> LanguageTool was not reachable
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and self.checked and not self.missing and not self.remarks


def pick_task(entry: Entry, rng: random.Random) -> tuple[str, list[str]]:
    return rng.choice(targets(entry))


def apply_corrections(text: str, issues: list[Issue]) -> str:
    """Apply the first replacement of each non-overlapping issue, right to left."""
    chosen: list[Issue] = []
    end = -1
    for issue in sorted(issues, key=lambda i: i.offset):
        if issue.replacements and issue.offset >= end:
            chosen.append(issue)
            end = issue.offset + issue.length
    for issue in reversed(chosen):
        text = text[: issue.offset] + issue.replacements[0] + text[issue.offset + issue.length:]
    return text


def check_sentence(sentence: str, required: list[str], checker: Checker = grammar_check.check) -> CheckResult:
    sentence = sanitize.text(sentence, 2000)
    if not sentence:
        return CheckResult(sentence, "", error="Write a sentence first.")
    if len(sentence) > MAX_SENTENCE:
        return CheckResult(sentence, "", error=f"Sentence is too long (max {MAX_SENTENCE} characters).")
    tokens = _tokens(sentence)
    if len(tokens) < 3:
        return CheckResult(sentence, "", error="Write a full sentence (at least 3 words).")
    missing = [w for w in required if normalize(w) not in tokens]
    issues = checker(sentence)
    if issues is None:
        return CheckResult(sentence, sentence, missing=missing, checked=False)
    remarks = [
        Remark(sanitize.text(sentence[i.offset: i.offset + i.length], 100), sanitize.text(i.message, 300),
               [r for r in (sanitize.text(x, 100) for x in i.replacements[:5]) if r])
        for i in issues
    ]
    return CheckResult(sentence, apply_corrections(sentence, issues), remarks, missing)
