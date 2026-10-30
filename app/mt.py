"""Offline translation of short example sentences and, paragraph by paragraph, of a recognised text (the Texte check step) for the
web app: Argos Translate, the same models as the CLI (wort.sentence). German → English directly; German → Ukrainian through English (Argos has no de→uk model).

Optional: without the 'mt' group or a model, translate() returns "" and the caller shows the word's own
translation instead. Results (and misses) are kept per process; restart after installing a model.
"""

from __future__ import annotations

import re
import threading
from functools import lru_cache

from wort import sentence

CHUNK = 450  # characters: below the translator's cap (wort.sentence.MAX_CHARS, 500) for a sentence that has to be cut
WAIT = 30  # seconds a paragraph waits for another user's translation before it is told to try again
# Endings that are not the end of a sentence: "bis zum 15. November" (a number) and the usual abbreviations.
ABBREVIATIONS = {"z.", "b.", "d.", "h.", "u.", "a.", "o.", "ä.", "v.", "bzw.", "ca.", "ggf.", "usw.", "etc.", "evtl.", "inkl.",
                 "nr.", "str.", "tel.", "dr.", "hr.", "fr.", "prof.", "abs.", "vgl.", "sog.", "zzgl.", "max.", "min.", "mio.",
                 "mrd.", "ev.", "geb.", "co.", "ggü."}
_BREAK = re.compile(r"(?<=[.!?…])\s+(?=[A-ZÄÖÜ\"„»(§\d])")
_one_at_a_time = threading.Lock()


class Busy(RuntimeError):
    """Another translation is running and did not finish within WAIT seconds."""


@lru_cache(maxsize=1024)
def translate(text: str, target: str) -> str:
    """`text` (German) in English ("en") or Ukrainian ("uk"); "" when no model can do it."""
    try:
        english = sentence.translate(text, "de", "en")
        return english if target == "en" else sentence.translate(english, "en", target)
    except (sentence.TranslationUnavailable, ValueError, RuntimeError):
        return ""


def sentences(text: str) -> list[str]:
    """A paragraph cut into sentences at ". " "! " "? " before a capital letter, a quote or a number, except after a
    number ("15. November") or an abbreviation ("z. B. Mieter"); a sentence over CHUNK characters is cut at commas, then
    at spaces, so every piece can be translated. Whitespace is made single spaces."""
    text = " ".join(text.split())
    out, start = [], 0
    for m in _BREAK.finditer(text):
        last = text[start:m.start()].split(" ")[-1]
        if last[:-1].isdigit() or last.lower() in ABBREVIATIONS:
            continue
        out.append(text[start:m.start()])
        start = m.end()
    if text[start:]:
        out.append(text[start:])
    return [piece for sentence_ in out for piece in _cut(sentence_)]


def _cut(sentence_: str) -> list[str]:
    if len(sentence_) <= CHUNK:
        return [sentence_]
    pieces, current = [], ""
    for part in re.split(r"(?<=,)\s+", sentence_):
        for word in ([part] if len(part) <= CHUNK else part.split(" ")):
            if current and len(current) + 1 + len(word) > CHUNK:
                pieces.append(current)
                current = word
            else:
                current = f"{current} {word}".strip() if current else word
    return pieces + [current] if current else pieces


def paragraph(text: str, target: str) -> str:
    """A paragraph in English ("en") or Ukrainian ("uk"), sentence by sentence; "" if any sentence cannot be translated
    (a made-up or half translation is worse than none). One translation runs at a time (shared host); Busy when another
    user's takes longer than WAIT seconds."""
    if not _one_at_a_time.acquire(timeout=WAIT):
        raise Busy()
    try:
        done = [translate(piece, target) for piece in sentences(text)]
    finally:
        _one_at_a_time.release()
    return " ".join(done) if done and all(done) else ""
