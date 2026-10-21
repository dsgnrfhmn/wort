"""Deterministic provider for tests and local development; makes no network calls."""

from __future__ import annotations

from app.ai.provider import AiError
from app.ai.schemas import (AnswerGrade, Explanation, SentenceCheck, SentenceError, Task, TaskSet, WordResult)


class FakeProvider:
    """A sentence containing 'FEHLER' is wrong ('FEHLER' -> 'richtig'); anything else is right."""

    def __init__(self, fail: bool = False):
        self.calls: list[tuple[str, tuple]] = []
        self.fail = fail

    def _call(self, name: str, *args) -> None:
        self.calls.append((name, args))
        if self.fail:
            raise AiError("fake provider failure")

    def generate_tasks(self, words, n):
        self._call("generate_tasks", words, n)
        return TaskSet(tasks=[Task(prompt=f"Was machst du mit {w}?", word=w, translation_uk="…", translation_en="…")
                              for w in words[:n]] or [Task(prompt="Frage", word="x", translation_uk="", translation_en="")])

    def check_sentence(self, sentence, words, task):
        self._call("check_sentence", sentence, words, task)
        bad = "FEHLER" in sentence
        return SentenceCheck(
            errors=[SentenceError(wrong="FEHLER", right="richtig", kind="Test")] if bad else [],
            word_results=[WordResult(word=w, ok=not bad, note="") for w in words],
            rule="Testregel" if bad else "", natural=sentence.replace("FEHLER", "richtig"),
            corrected=sentence.replace("FEHLER", "richtig"),
        )

    def explain(self, sentence, check):
        self._call("explain", sentence, check)
        return Explanation(rule=check.rule or "Regel", explanation="Erklärung.", merke="Merke dir das.",
                           explanation_uk="Пояснення.")

    def recheck(self, sentence, words, task, objection):
        self._call("recheck", sentence, words, task, objection)
        return self.check_sentence(sentence, words, task)

    def more_for_rule(self, rule, n):
        self._call("more_for_rule", rule, n)
        return TaskSet(tasks=[Task(prompt=f"{rule} {i}", word="x", translation_uk="", translation_en="")
                              for i in range(n)])

    def grade_answer(self, question, answer, expected):
        self._call("grade_answer", question, answer, expected)
        return AnswerGrade(verdict="richtig" if expected.lower() in answer.lower() else "falsch", comment="")
