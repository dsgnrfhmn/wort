"""What the routes call: a provider behind the daily cap, with invalid replies turned into errors."""

from __future__ import annotations

import logging
from datetime import datetime

from app.ai.config import AiConfig
from app.ai.limits import DailyLimit, LimitReached
from app.ai.provider import AiError, Provider
from wort import sanitize

from app.ai.schemas import AiInvalid, SentenceCheck
from app.db import WebStore

log = logging.getLogger("wort.ai")


_MULTILINE = {"explanation", "explanation_uk"}


def clean_reply(obj):
    """Every string of a validated reply must be plain text; markup, links or hidden characters reject it."""
    def walk(value, key=""):
        if isinstance(value, str):
            return sanitize.model_text(value, 1200, multiline=key in _MULTILINE)
        if isinstance(value, list):
            return [walk(v, key) for v in value]
        if isinstance(value, dict):
            return {k: walk(v, k) for k, v in value.items()}
        return value
    try:
        return type(obj).model_validate(walk(obj.model_dump()))
    except (sanitize.Unsafe, ValueError):
        raise AiInvalid("unsafe reply") from None


class AiUnavailable(RuntimeError):
    """Not usable now; `.reason` is a user-facing message. Callers change no score."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class AiService:
    def __init__(self, config: AiConfig, store: WebStore, provider: Provider | None):
        self.config = config
        self.provider = provider
        self.limit = DailyLimit(store, config.daily_cap)

    @property
    def available(self) -> bool:
        return self.config.enabled and self.provider is not None

    def remaining(self, user_id: int) -> int:
        return self.limit.remaining(user_id, datetime.now()) if self.available else 0

    def uses(self, feature: str) -> bool:
        """True when AI is on and this call site is allowed (WORT_AI_FEATURES)."""
        return self.available and feature in self.config.features

    def check_sentence(self, user_id: int, sentence: str, words: list[str], task: str) -> SentenceCheck:
        return self._run(user_id, "check", lambda p: p.check_sentence(sentence, words, task))

    def explain(self, user_id: int, sentence: str, check: SentenceCheck):
        return self._run(user_id, "explain", lambda p: p.explain(sentence, check))

    def generate_tasks(self, user_id: int, words: list[str], n: int):
        return self._run(user_id, "tasks", lambda p: p.generate_tasks(words, n))

    def recheck(self, user_id: int, sentence: str, words: list[str], task: str, objection: str):
        return self._run(user_id, "recheck", lambda p: p.recheck(sentence, words, task, objection))

    def more_for_rule(self, user_id: int, rule: str, n: int):
        return self._run(user_id, "rule", lambda p: p.more_for_rule(rule, n))

    def grade_answer(self, user_id: int, question: str, answer: str, expected: str):
        return self._run(user_id, "answer", lambda p: p.grade_answer(question, answer, expected))

    def _run(self, user_id: int, feature: str, call):
        name = feature
        if not self.uses(feature):
            raise AiUnavailable("KI ist ausgeschaltet.")
        try:
            self.limit.take(user_id, datetime.now())
        except LimitReached:
            raise AiUnavailable("Das Tageslimit für KI-Anfragen ist erreicht.") from None
        try:
            result = clean_reply(call(self.provider))
        except AiInvalid:
            log.warning("ai %s: invalid reply", name)  # counts only; never log user text or replies
            raise AiUnavailable("Die KI-Antwort war ungültig. Es wurde nichts bewertet.") from None
        except AiError as e:
            log.warning("ai %s: %s", name, e)
            raise AiUnavailable("Die KI ist gerade nicht erreichbar. Es wurde nichts bewertet.") from None
        return result


def build(config: AiConfig, store: WebStore, provider: Provider | None = None) -> AiService:
    """Create the service. The Anthropic provider is imported only here, only when enabled."""
    if config.enabled and provider is None:
        from app.ai.anthropic_provider import AnthropicProvider  # noqa: PLC0415

        provider = AnthropicProvider(config)
    return AiService(config, store, provider)
