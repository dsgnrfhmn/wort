"""Offline translation of short example sentences for the web app: Argos Translate, the same models as the CLI
(wort.sentence). German → English directly; German → Ukrainian through English (Argos has no de→uk model).

Optional: without the 'mt' group or a model, translate() returns "" and the caller shows the word's own
translation instead. Results (and misses) are kept per process; restart after installing a model.
"""

from __future__ import annotations

from functools import lru_cache

from wort import sentence


@lru_cache(maxsize=1024)
def translate(text: str, target: str) -> str:
    """`text` (German) in English ("en") or Ukrainian ("uk"); "" when no model can do it."""
    try:
        english = sentence.translate(text, "de", "en")
        return english if target == "en" else sentence.translate(english, "en", target)
    except (sentence.TranslationUnavailable, ValueError, RuntimeError):
        return ""
