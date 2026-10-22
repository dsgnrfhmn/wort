"""Live check of the six AI blocks, run by the maintainer ON THE SERVER with the real key.

    WORT_AI_ENABLED=1 ANTHROPIC_API_KEY=... PYTHONPATH=.:src python scripts/ai_smoke.py

Sends one fixed, non-private example per block (no learner data), checks the reply against the schemas
and the sanitizer, and prints latency and token counts. Exits non-zero if any block fails. It makes six
real API calls (a few cents at most). It is the only thing in this repository that talks to the API for real.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from app.ai import config as ai_config  # noqa: E402
from app.ai import schemas, service  # noqa: E402
from app.ai.anthropic_provider import AnthropicProvider  # noqa: E402

SENTENCE = "Ich stelle ein Antrag beim Jobcenter."


def main() -> int:
    try:
        config = ai_config.load()
    except ValueError as e:
        print(f"config: {e}")
        return 2
    if not config.enabled:
        print("Set WORT_AI_ENABLED=1 and ANTHROPIC_API_KEY.")
        return 2
    provider = AnthropicProvider(config)
    check: schemas.SentenceCheck | None = None
    failures = 0

    def run(name, call):
        nonlocal failures
        start = time.monotonic()
        try:
            result = service.clean_reply(call())  # the same sanitizing the app applies
            status = "PASS"
        except Exception as e:  # report, do not stop: every block gets its line
            result, status, failures = None, f"FAIL ({type(e).__name__}: {e})", failures + 1
        print(f"{name:16} {status:10} {time.monotonic() - start:5.1f}s  tokens in/out {provider.last_usage}")
        return result

    check = run("check", lambda: provider.check_sentence(SENTENCE, ["Antrag"], "Schreibe einen Satz mit «Antrag»."))
    run("recheck", lambda: provider.recheck(SENTENCE, ["Antrag"], "Schreibe einen Satz mit «Antrag».", "Ich glaube, er ist richtig."))
    run("explain", lambda: provider.explain(SENTENCE, check or schemas.SentenceCheck(
        errors=[], word_results=[], rule="Akkusativ", natural="", corrected=SENTENCE)))
    run("tasks", lambda: provider.generate_tasks(["Wohnung", "Antrag"], 3))
    run("rule", lambda: provider.more_for_rule("Artikel im Akkusativ", 3))
    run("answer", lambda: provider.grade_answer("Was bedeutet «Wohnung»?", "apartment", "apartment; flat"))
    print("ALL PASS" if not failures else f"{failures} block(s) FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
