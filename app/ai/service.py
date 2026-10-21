"""What the routes call: a provider behind the daily cap, with invalid replies turned into errors."""

from __future__ import annotations

import logging
from datetime import datetime

from app.ai.config import AiConfig
from app.ai.limits import DailyLimit, LimitReached
from app.ai.provider import AiError, Provider
from app.ai.schemas import AiInvalid, SentenceCheck
from app.db import WebStore

log = logging.getLogger("wort.ai")


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

    def check_sentence(self, user_id: int, sentence: str, words: list[str], task: str) -> SentenceCheck:
        return self._run(user_id, "check_sentence", lambda p: p.check_sentence(sentence, words, task))

    def explain(self, user_id: int, sentence: str, check: SentenceCheck):
        return self._run(user_id, "explain", lambda p: p.explain(sentence, check))

    def _run(self, user_id: int, name: str, call):
        if not self.available:
            raise AiUnavailable("KI ist ausgeschaltet.")
        try:
            self.limit.take(user_id, datetime.now())
        except LimitReached:
            raise AiUnavailable("Das Tageslimit für KI-Anfragen ist erreicht.") from None
        try:
            result = call(self.provider)
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
