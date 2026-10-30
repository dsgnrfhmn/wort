"""Sanitizers for every place information enters or leaves wort (CLI and web app).

Rule: sanitize on the way in, validate on the way out, never trust the previous layer. A value that
cannot be made safe is rejected (`Unsafe`), never partially used. The functions are pure and capped.

- `text`        free user text: NFC, no control/format/private-use characters (ESC and ANSI sequences,
                NUL, zero-width and bidi controls), whitespace collapsed, length-capped
- `word`        lemma / part of speech / name-like tokens: `text` plus no markup or template characters
- `for_model`   text that goes into an AI request
- `model_text`  text that comes back from the model: rejected (not repaired) if it carries markup,
                links, template syntax or hidden characters
- `terminal`    anything printed in the CLI that did not come from our own code
- `redact`      key- and token-looking strings, for logs and error messages
"""

from __future__ import annotations

import logging
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
_MARKUP = re.compile(r"<\s*/?\s*[A-Za-z!?]")
_TEMPLATE = re.compile(r"\{\{|\{%|\{#|%\}|\}\}|\$\{|<%|%>")
_LINK = re.compile(r"(?i)(?:\b(?:https?|ftp|file|data|javascript|vbscript):|\bwww\.|\]\()")
_WORD_FORBIDDEN = re.compile(r"[<>{}\\`|;$]")
_SECRETS = [
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"), "[redacted-key]"),
    (re.compile(r"wsync_[A-Za-z0-9_\-]{8,}"), "[redacted-token]"),
    (re.compile(r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?\S+"), r"\1[redacted]"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}"), "Bearer [redacted]"),
    (re.compile(r"(?i)((?:api[_-]?key|token|password|secret)\s*[:=]\s*)\S+"), r"\1[redacted]"),
]


def _clean(value: object, multiline: bool) -> tuple[str, bool]:
    """(cleaned, dropped) where dropped says a character beyond plain whitespace was removed."""
    if not isinstance(value, str):
        raise Unsafe("expected a string")
    s = unicodedata.normalize("NFC", value)
    before = s
    s = _ANSI.sub("", s)
    dropped = s != before
    out = []
    for ch in s:
        if ch in _LINE_SEPARATORS:
            out.append("\n" if multiline else " ")
        elif ch in "\n\r\t":
            out.append("\n" if ch != "\t" and multiline else " ")
        elif unicodedata.category(ch) in _BAD_CATEGORIES:
            dropped = True
        else:
            out.append(ch)
    s = "".join(out)
    s = _SPACES.sub(" ", s)
    if multiline:
        s = re.sub(r" ?\n ?", "\n", s)
        s = re.sub(r"\n{3,}", "\n\n", s)
    else:
        s = s.replace("\n", " ")
        s = _SPACES.sub(" ", s)
    return s.strip(), dropped


def text(value: object, max_len: int = MAX_DEFAULT, multiline: bool = False) -> str:
    """Make free text safe. Long input is cut at `max_len`; an empty result is allowed (callers decide)."""
    cleaned, _ = _clean(value, multiline)
    return cleaned[:max_len]


def word(value: object, max_len: int = 100) -> str:
    """A lemma, part of speech or similar token: non-empty, no markup or template characters."""
    cleaned = text(value, max_len)
    if not cleaned:
        raise Unsafe("empty after cleaning")
    if _WORD_FORBIDDEN.search(cleaned) or _TEMPLATE.search(cleaned):
        raise Unsafe("contains markup or template characters")
    return cleaned


def for_model(value: object, max_len: int = 300, multiline: bool = False) -> str:
    """Text for an AI request: cleaned, and without the characters that look like markup or code fences."""
    cleaned = text(value, max_len, multiline)
    return cleaned.replace("```", "").replace("<", "").replace(">", "")


def model_text(value: object, max_len: int = 300, multiline: bool = False) -> str:
    """Text from the model: only plain text passes. Anything else is rejected, never repaired."""
    cleaned, dropped = _clean(value, multiline)
    if dropped:
        raise Unsafe("hidden or control characters")
    if len(cleaned) > max_len:
        raise Unsafe("too long")
    if _MARKUP.search(cleaned) or _TEMPLATE.search(cleaned) or _LINK.search(cleaned):
        raise Unsafe("markup, template syntax or a link")
    return cleaned


def terminal(value: object, max_len: int = 1000) -> str:
    """Text printed to a terminal that came from outside: no escape sequences, no control characters."""
    try:
        return text(value, max_len, multiline=True)
    except Unsafe:
        return ""


def redact(value: object) -> str:
    """Replace key- and token-looking strings; for logs and error text."""
    s = str(value)
    for pattern, repl in _SECRETS:
        s = pattern.sub(repl, s)
    return s


_installed = False


def _redact_arg(value: object) -> object:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else redact(value)


def _redact_record(record: logging.LogRecord) -> None:
    """Redact a record in place. Tuple args stay a tuple of redacted values, because formatters such as
    uvicorn's access formatter read them by position; if the message they build still looks like it holds
    a secret (one split between the format string and an argument), the record is collapsed to its
    redacted message instead."""
    if isinstance(record.args, tuple) and record.args:
        msg, args = redact(record.msg), tuple(_redact_arg(a) for a in record.args)
        full = msg % args
        if redact(full) == full:
            record.msg, record.args = msg, args
            return
    record.msg, record.args = redact(record.getMessage()), ()


def install_log_redaction() -> None:
    """Redact every log record once, at creation (all loggers, all handlers). Idempotent."""
    global _installed
    if _installed:
        return
    _installed = True
    previous = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        try:
            _redact_record(record)
        except Exception:  # a broken format string must not break logging
            record.msg, record.args = redact(record.msg), ()
        return record

    logging.setLogRecordFactory(factory)
