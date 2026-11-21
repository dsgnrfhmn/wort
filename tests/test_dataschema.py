"""The rules for what may be stored in the history files (words.jsonl, sentences.jsonl)."""

import json
from datetime import datetime, timezone

import pytest

from wort import dataschema as d

NOW = datetime(2026, 11, 21, 15, 5, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("kind,text", [
    ("word", "Haus"), ("word", "sich freuen"), ("word", "E-Mail"), ("word", "Größe"), ("word", "Übung"),
    ("sentence", "Haus- und Gartentür"), ("sentence", "Heute sind es -5 Grad."), ("word", "z. B."), ("word", "die Häuser (Pl.)"), ("word", "будинок"), ("word", "l’homme"), ("word", "12 Uhr"),
    ("sentence", "Ich gehe nach Hause."), ("sentence", "„Wo ist das Haus?“, fragte sie."),
    ("sentence", "Er sagte: Komm um 12:30 Uhr!"), ("sentence", "Das Wetter … nun ja."),
    ("sentence", "Дякую, добре — а ти?"), ("sentence", "(Das ist ein Test.)"),
])
def test_words_and_sentences_are_accepted(kind, text):
    assert d.text_problem(text, kind) is None
    assert d.make_entry(kind, text, True, NOW).text == text


# Everything below must be refused: commands, markup, templates, paths, links, control and invisible characters.
@pytest.mark.parametrize("text", [
    "$(rm -rf ~)", "`id`", "a; b", "a | b", "a && b", "ls > /tmp/x", "rm -rf /", "cat /etc/passwd", "~/.ssh/id_rsa",
    "<script>alert(1)</script>", "<b>x</b>", "{{7*7}}", "{% import os %}", "${HOME}", "%s %n", "a\\b",
    "[click](http://x)", "http://evil.example", "https://evil.example/x", "javascript:alert(1)", "data:text/html,x",
    "www.evil.com", "file:passwd", "a@b.c", "x=1", "+cmd", "=SUM(A1)", "@SUM(1)", "-rf", "--help", "#!/bin/sh", "uv sync --mt group", "ls -la", "Haus --version",
    "line\nbreak", "tab\tbed", "carriage\rreturn", "nul\x00byte", "bell\x07", "esc\x1b[31mred", "\x1b]0;title\x07x",
    "zero\u200bwidth", "bidi\u202eevil", "\ufeffbom", "soft\u00adhyphen", "no\u00a0break", "line\u2028sep", "private\ue000use",
    "emoji 😀", "arrow → here", "€ 5", "50%", "a*b", "a_b", "a/b", "a^b", "a~b", "a'b\"c;d",
    " leading", "trailing ", "double  space", "", " ", "…", ".dot", "(", "'", "ignore\x00",
])
def test_everything_else_is_refused(text):
    assert d.text_problem(text, "sentence") is not None and d.text_problem(text, "word") is not None


def test_length_limits():
    assert d.text_problem("a" * 60, "word") is None and d.text_problem("a" * 61, "word")
    assert d.text_problem("a" * 500, "sentence") is None and d.text_problem("a" * 501, "sentence")


def test_text_must_already_be_nfc():
    assert d.text_problem("\u00dc", "word") is None  # precomposed
    assert d.text_problem("U\u0308", "word") == "text is not NFC-normalized"  # U + combining diaeresis


def test_non_strings_are_refused():
    for bad in (None, 5, b"x", ["a"], {"a": 1}):
        assert d.text_problem(bad, "word")


def test_line_round_trip():
    word = d.make_entry("word", "Haus", True, NOW)
    assert d.dump_line(word) == '{"text":"Haus","ts":"2026-11-21T15:05:00Z","found":true}'
    assert d.parse_line(d.dump_line(word), "word") == word
    sentence = d.make_entry("sentence", "Ich gehe.", False, NOW)  # `found` means nothing for a sentence
    assert d.dump_line(sentence) == '{"text":"Ich gehe.","ts":"2026-11-21T15:05:00Z"}'
    assert d.parse_line(d.dump_line(sentence), "sentence").found is True


@pytest.mark.parametrize("line", [
    "",
    "not json",
    "[]", "null", '"Haus"', "5",
    '{"text":"Haus","ts":"2026-11-21T15:05:00Z"}',  # `found` missing
    '{"text":"Haus","ts":"2026-11-21T15:05:00Z","found":true,"x":1}',  # extra key
    '{"text":"Haus","ts":"2026-11-21T15:05:00Z","found":"yes"}',  # wrong type
    '{"text":"Haus","ts":"2026-11-21T15:05:00Z","found":1}',
    '{"text":5,"ts":"2026-11-21T15:05:00Z","found":true}',
    '{"text":"Haus","ts":"2026-11-21","found":true}',
    '{"text":"Haus","ts":"2026-11-21T15:05:00+00:00","found":true}',
    '{"text":"Haus","ts":"2026-13-45T25:61:00Z","found":true}',
    '{"text":"Haus","ts":null,"found":true}',
    '{"text":"Haus","text":"Katze","ts":"2026-11-21T15:05:00Z","found":true}',  # duplicate key
    '{"text":"$(id)","ts":"2026-11-21T15:05:00Z","found":true}',
    '{"text":"Haus","ts":"2026-11-21T15:05:00Z","found":NaN}',
    '{"text":"Ha\\u0000us","ts":"2026-11-21T15:05:00Z","found":true}',  # an escaped NUL
    '{"text":"Haus","ts":"2026-11-21T15:05:00Z","found":true}\r',
    '{"text":"Haus","ts":"2026-11-21T15:05:00Z","found":true}\t',
    '{"text":"' + "a" * 5000 + '","ts":"2026-11-21T15:05:00Z","found":true}',
])
def test_bad_lines_are_refused(line):
    with pytest.raises(d.Invalid):
        d.parse_line(line, "word")


def test_a_sentence_line_may_not_carry_found():
    with pytest.raises(d.Invalid):
        d.parse_line('{"text":"Ich gehe.","ts":"2026-11-21T15:05:00Z","found":true}', "sentence")


def _file(*entries):
    return ("".join(d.dump_line(e) + "\n" for e in entries)).encode()


def test_a_file_is_all_or_nothing_and_names_the_bad_line():
    good = d.make_entry("word", "Haus", True, NOW)
    assert d.check_bytes(_file(good, good), "word") == [good, good]
    assert d.check_bytes(b"", "word") == []
    bad = _file(good) + b'{"text":"$(id)","ts":"2026-11-21T15:05:00Z","found":true}\n'
    with pytest.raises(d.Invalid, match="line 2: character not allowed"):
        d.check_bytes(bad, "word")


@pytest.mark.parametrize("data,why", [
    (b'{"text":"Haus","ts":"2026-11-21T15:05:00Z","found":true}', "no newline"),  # no final newline
    (b"\xff\xfe\n", "UTF-8"),
    (b"\xef\xbb\xbf" + b'{"text":"Haus","ts":"2026-11-21T15:05:00Z","found":true}\n', "line 1"),  # a BOM
    (b"\n", "line 1"),  # an empty line
])
def test_file_level_problems(data, why):
    with pytest.raises(d.Invalid, match=why):
        d.check_bytes(data, "word")


def test_file_size_and_line_count_are_capped(monkeypatch):
    monkeypatch.setattr(d, "MAX_FILE_BYTES", 10)
    with pytest.raises(d.Invalid, match="too large"):
        d.check_bytes(b"x" * 11, "word")
    monkeypatch.setattr(d, "MAX_FILE_BYTES", 10_000)
    monkeypatch.setitem(d.MAX_LINES, "word", 1)
    with pytest.raises(d.Invalid, match="more than 1 lines"):
        d.check_bytes(_file(*[d.make_entry("word", "a", True, NOW)] * 2), "word")


def test_make_entry_refuses_rule_breaking_text_and_unknown_kinds():
    with pytest.raises(d.Invalid):
        d.make_entry("word", "$(id)")
    with pytest.raises(d.Invalid):
        d.make_entry("command", "Haus")


def test_make_entry_uses_utc_whole_seconds():
    local = datetime(2026, 11, 21, 16, 5, 0, 999, tzinfo=timezone.utc).astimezone()
    entry = d.make_entry("word", "Haus", True, local)
    assert entry.ts == datetime(2026, 11, 21, 16, 5, 0, tzinfo=timezone.utc) and entry.ts.microsecond == 0


# --- a whole checkout of the data repository ------------------------------------------------------------


def _repo(tmp_path, **files):
    for name, content in files.items():
        path = tmp_path / name.replace("__", "/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode())
    return tmp_path


def test_check_tree_accepts_the_expected_layout(tmp_path):
    good = d.make_entry("word", "Haus", True, NOW)
    root = _repo(tmp_path, **{"words.jsonl": _file(good), "sentences.jsonl": b"", "README.md": "# data\n", "validate.py": "x = 1\n",
                               ".gitattributes": "*.jsonl merge=union\n", ".github__workflows__validate.yml": "name: v\n"})
    (root / ".git").mkdir()
    (root / ".git" / "anything").write_text("ignored")
    assert d.check_tree(root) == {"words.jsonl": 1, "sentences.jsonl": 0}


@pytest.mark.parametrize("name", ["evil.sh", "run.py", "notes.txt", "data/words.jsonl", ".github/workflows/other.yml", "words.jsonl.bak", ".env"])
def test_check_tree_refuses_any_other_file(tmp_path, name):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")
    with pytest.raises(d.Invalid, match="not an allowed file"):
        d.check_tree(tmp_path)


def test_check_tree_refuses_symlinks(tmp_path):
    target = tmp_path / "outside.txt"
    target.write_text("secret")
    (tmp_path / "words.jsonl").symlink_to(target)
    with pytest.raises(d.Invalid, match="regular file"):
        d.check_tree(tmp_path)


def test_check_tree_names_the_file_with_a_bad_line(tmp_path):
    root = _repo(tmp_path, **{"sentences.jsonl": '{"text":"$(id)","ts":"2026-11-21T15:05:00Z"}\n'})
    with pytest.raises(d.Invalid, match=r"sentences.jsonl: line 1"):
        d.check_tree(root)


def test_main_reports_ok_and_failure(tmp_path, capsys):
    root = _repo(tmp_path, **{"words.jsonl": _file(d.make_entry("word", "Haus", True, NOW))})
    assert d.main([str(root)]) == 0 and "OK: 1 in words.jsonl" in capsys.readouterr().out
    (root / "evil.sh").write_text("x")
    assert d.main([str(root)]) == 1 and "evil.sh: not an allowed file" in capsys.readouterr().err


def test_the_validator_uses_only_the_standard_library():
    """It is copied alone into the data repository as validate.py: it may not import wort or anything else."""
    import ast
    import sys

    tree = ast.parse(open(d.__file__, encoding="utf-8").read())
    modules = {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    modules |= {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert modules <= set(sys.stdlib_module_names) | {"__future__"}, modules


def test_json_in_the_file_is_what_json_loads_says():
    line = d.dump_line(d.make_entry("word", "Größe", True, NOW))
    assert json.loads(line) == {"text": "Größe", "ts": "2026-11-21T15:05:00Z", "found": True}
    assert "Größe" in line  # written as UTF-8, not as \u escapes
