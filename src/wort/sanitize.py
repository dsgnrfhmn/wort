"""Sanitizers for text that enters wort from outside (typed queries, dictionary dumps).

Rule: sanitize on the way in, never trust the previous layer. A value that cannot be made safe is
rejected (`Unsafe`), never partially used. The functions are pure and capped.

- `text`  free text: NFC, no control/format/private-use characters (ESC and ANSI sequences, NUL,
          zero-width and bidi controls), whitespace collapsed, length-capped
- `word`  lemma / part of speech / name-like tokens: `text` plus no markup or template characters
"""

from __future__ import annotations

import re
import unicodedata

MAX_DEFAULT = 500


class Unsafe(ValueError):
    """The value cannot be made safe."""


_ANSI = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"            # CSI
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?"  # OSC (title, hyperlinks)
    r"|\x1b[PX^_][^\x1b]*(?:\x1b\\)?"      # DCS / SOS / PM / APC
    r"|\x1b[@-Z\\-_]"                      # two-character escapes
)
_BAD_CATEGORIES = {"Cc", "Cf", "Cs", "Co", "Cn"}  # control, format (zero-width, bidi), surrogate, private, unassigned
_LINE_SEPARATORS = {" ", " ", "\x85"}
_SPACES = re.compile(r"[^\S\n]+")
_TEMPLATE = re.compile(r"\{\{|\{%|\{#|%\}|\}\}|\$\{|<%|%>")
_WORD_FORBIDDEN = re.compile(r"[<>{}\\`|;$]")


def _clean(value: object, multiline: bool) -> str:
    if not isinstance(value, str):
        raise Unsafe("expected a string")
    s = unicodedata.normalize("NFC", value)
    s = _ANSI.sub("", s)
    out = []
    for ch in s:
        if ch in _LINE_SEPARATORS:
            out.append("\n" if multiline else " ")
        elif ch in "\n\r\t":
            out.append("\n" if ch != "\t" and multiline else " ")
        elif unicodedata.category(ch) not in _BAD_CATEGORIES:
            out.append(ch)
    s = "".join(out)
    s = _SPACES.sub(" ", s)
    if multiline:
        s = re.sub(r" ?\n ?", "\n", s)
        s = re.sub(r"\n{3,}", "\n\n", s)
    else:
        s = s.replace("\n", " ")
        s = _SPACES.sub(" ", s)
    return s.strip()


def text(value: object, max_len: int = MAX_DEFAULT, multiline: bool = False) -> str:
    """Make free text safe. Long input is cut at `max_len`; an empty result is allowed (callers decide)."""
    return _clean(value, multiline)[:max_len]


def word(value: object, max_len: int = 100) -> str:
    """A lemma, part of speech or similar token: non-empty, no markup or template characters."""
    cleaned = text(value, max_len)
    if not cleaned:
        raise Unsafe("empty after cleaning")
    if _WORD_FORBIDDEN.search(cleaned) or _TEMPLATE.search(cleaned):
        raise Unsafe("contains markup or template characters")
    return cleaned
