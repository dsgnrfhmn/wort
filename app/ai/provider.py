"""The provider interface the routes depend on. Implementations: fake (tests), anthropic (draft)."""

from __future__ import annotations

from typing import Protocol

from app.ai.schemas import AnswerGrade, Explanation, SentenceCheck, TaskSet


class AiError(RuntimeError):
    """Network failure, timeout, refusal or HTTP error from the provider."""


class Provider(Protocol):
    """Every method receives only the sentence/answer and the words it needs; never full texts or photos."""

    def generate_tasks(self, words: list[str], n: int) -> TaskSet: ...

    def check_sentence(self, sentence: str, words: list[str], task: str) -> SentenceCheck: ...

    def explain(self, sentence: str, check: SentenceCheck) -> Explanation: ...

    def recheck(self, sentence: str, words: list[str], task: str, objection: str) -> SentenceCheck: ...

    def more_for_rule(self, rule: str, n: int) -> TaskSet: ...

    def grade_answer(self, question: str, answer: str, expected: str) -> AnswerGrade: ...
