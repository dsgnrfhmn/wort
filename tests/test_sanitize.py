import logging

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


def test_for_model_strips_markup_and_fences():
    assert s.for_model("Ich <b>sehe</b> ```code``` das Haus") == "Ich bsehe/b code das Haus"
    assert "\x1b" not in s.for_model("x\x1b[31m")


@pytest.mark.parametrize("bad", [
    "<script>x</script>", "see <b>this</b>", "http://evil.example", "javascript:alert(1)", "[click](x)", "www.evil.com",
    "{{7*7}}", "{% if %}", "hidden​text", "bidi‮flip", "ctrl\x07char", "x" * 400,
])
def test_model_text_rejects_instead_of_repairing(bad):
    with pytest.raises(s.Unsafe):
        s.model_text(bad, 300)


def test_model_text_accepts_plain_german_and_math_like_text():
    assert s.model_text("Ich stelle einen Antrag. 3 < 5 ist wahr?") == "Ich stelle einen Antrag. 3 < 5 ist wahr?"
    assert s.model_text("Akkusativ: der → den", 100) == "Akkusativ: der → den"
    assert s.model_text("Zeile 1\nZeile 2", 100, multiline=True) == "Zeile 1\nZeile 2"


def test_terminal_strips_escapes_and_never_raises():
    assert s.terminal("ok\x1b[2J\x1b]8;;http://x\x07link") == "oklink"
    assert s.terminal(None) == ""


@pytest.mark.parametrize("raw,must_not", [
    ("key sk-ant-api03-ABCDEFGHIJKLMNOP end", "sk-ant-api03"),
    ("token wsync_abcdefghijkl1234", "wsync_abcdef"),
    ("Authorization: Bearer abc.def.ghi-123456", "abc.def"),
    ("api_key=supersecretvalue", "supersecretvalue"),
    ("password: hunter2hunter2", "hunter2"),
])
def test_redact(raw, must_not):
    assert must_not not in s.redact(raw)


def test_log_records_are_redacted_everywhere(caplog):
    s.install_log_redaction()
    s.install_log_redaction()  # idempotent
    with caplog.at_level(logging.INFO):
        logging.getLogger("x").warning("failed with key %s", "sk-ant-api03-SECRETSECRETSECRET")
    assert "SECRETSECRET" not in caplog.text and "[redacted-key]" in caplog.text


def test_log_redaction_keeps_positional_args_for_the_access_formatter():
    from uvicorn.logging import AccessFormatter
    s.install_log_redaction()
    record = logging.getLogger("uvicorn.access").makeRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:5000", "GET", "/sync?token=wsync_abcdefghijkl", "1.1", 200), None)
    line = AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False).format(record)
    assert line == '127.0.0.1:5000 - "GET /sync?token=[redacted] HTTP/1.1" 200 OK'


@pytest.mark.parametrize("msg,args,secret", [
    ("%s: %s", ("token", "abcdefghijkl"), "abcdefghijkl"),           # each arg clean, the joined line is not
    ("Authorization: %s", ("abcdefghijkl",), "abcdefghijkl"),         # secret split between format and arg
    ("token=%s", ("plainvalue12",), "plainvalue12"),                    # the format string itself matches
    ("key %s", ("sk-ant-api03-SECRETSECRETSECRET",), "SECRETSECRET"),
])
def test_log_redaction_never_leaks_through_args(caplog, msg, args, secret):
    s.install_log_redaction()
    with caplog.at_level(logging.INFO):
        logging.getLogger("x").warning(msg, *args)
    record = caplog.records[-1]
    assert secret not in caplog.text and secret not in record.getMessage()
    assert all(secret not in str(a) for a in (record.args or ()))
