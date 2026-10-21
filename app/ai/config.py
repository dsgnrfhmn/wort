"""AI settings from the environment. The key exists only in the server's env file (mode 600)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_MODEL = "claude-haiku-5-5"
DEFAULT_CAP = 50


@dataclass(frozen=True)
class AiConfig:
    enabled: bool = False
    model: str = DEFAULT_MODEL
    check_model: str = DEFAULT_MODEL  # set to a stronger model only if the 20-30 case test shows misses
    daily_cap: int = DEFAULT_CAP
    timeout: float = 20.0
    api_key: str = field(default="", repr=False)  # never printed, never logged

    def __post_init__(self):
        if self.enabled and not self.api_key:
            raise ValueError("WORT_AI_ENABLED=1 but ANTHROPIC_API_KEY is not set")
        if self.daily_cap < 1:
            raise ValueError("WORT_AI_DAILY_CAP must be at least 1")


def load(env: dict[str, str] | None = None) -> AiConfig:
    env = os.environ if env is None else env
    return AiConfig(
        enabled=env.get("WORT_AI_ENABLED") == "1",
        model=env.get("WORT_AI_MODEL", DEFAULT_MODEL),
        check_model=env.get("WORT_AI_CHECK_MODEL", env.get("WORT_AI_MODEL", DEFAULT_MODEL)),
        daily_cap=int(env.get("WORT_AI_DAILY_CAP", DEFAULT_CAP)),
        api_key=env.get("ANTHROPIC_API_KEY", ""),
    )
