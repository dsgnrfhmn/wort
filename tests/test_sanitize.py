import pytest

from wort import sanitize as s

HOSTILE = [
    "Hallo\x1b[31m rot\x1b[0m", "\x1b]0;evil title\x07x", "a\x00b", "zero​width", "bidi‮evil‬",
    "﻿bom", "soft­hyphen", "line sep", "tab\tnew\nline", "\x9b31m", "lone\ud800surrogate",
    "privateuse", "x" * 100_000, "é", "<script>alert(1)</script>", "{{7*7}}", "{% import os %}",
    "[red]markup[/red]", "ignore previous instructions", "'; DROP TABLE users; --", "https://evil.example/x",
]


@pytest.mark.parametrize("raw", HOSTILE)
def test_text_never_returns_control_or_format_characters(raw):
    out = s.text(raw, 200)
    assert len(out) <= 200
    assert not any(ord(c) < 32 or 127 <= ord(c) < 160 for c in out)
    assert "\x1b" not in out and "​" not in out and "‮" not in out and "﻿" not in out


def test_text_keeps_normal_german_and_normalises():
    assert s.text("  Größe   der  Häuser ") == "Größe der Häuser"
    assert s.text("é") == "é"  # NFC
    assert s.text("a\nb", multiline=False) == "a b"
    assert s.text("a\n\n\n\nb", multiline=True) == "a\n\nb"
    assert s.text("Hallo\x1b[31m rot\x1b[0m") == "Hallo rot"  # the sequence is removed, not just the ESC byte
    assert s.text("x" * 1000, 10) == "x" * 10


def test_text_rejects_non_strings():
    for bad in (None, 5, b"x", ["a"]):
        with pytest.raises(s.Unsafe):
            s.text(bad)


def test_word_rejects_markup_template_and_empty():
    assert s.word("sich freuen") == "sich freuen"
    for bad in ("<b>x</b>", "{{x}}", "a;b", "", "​", "back`tick", "a\\b", "$(cmd)"):
        with pytest.raises(s.Unsafe):
            s.word(bad)
