"""Web dashboard backend: import, favorites, sentence check (no HTTP layer)."""

import json
import random
from datetime import datetime

import pytest

from app.checking import apply_corrections, check_sentence, pick_task
from app.db import WebStore
from app.importer import import_export
from app.lexicon import summary
from wort.exercises.grammar_check import Issue
from wort.transfer import FORMAT_VERSION


@pytest.fixture
def web(tmp_path) -> WebStore:
    return WebStore(tmp_path / "web.db")


def export_bytes(queries):
    return json.dumps({
        "format_version": FORMAT_VERSION,
        "exported_at": "2026-10-14T10:00:00",
        "words": [],
        "queries": [{"query": q, "found": f, "queried_at": t} for q, f, t in queries],
    }).encode()


def test_import_is_idempotent(web):
    raw = export_bytes([("Haus", True, "2026-10-01T10:00:00"), ("haus", True, "2026-10-02T10:00:00")])
    assert import_export(web, raw).queries_new == 2
    assert import_export(web, raw).queries_new == 0
    rows = web.history()
    assert len(rows) == 1 and rows[0].count == 2 and rows[0].query == "haus"


@pytest.mark.parametrize("raw", [b"not json", b"[]", json.dumps({"format_version": 99}).encode()])
def test_import_rejects_malformed_and_writes_nothing(web, raw):
    with pytest.raises(ValueError):
        import_export(web, raw)
    assert web.history() == []


def test_favorites_toggle_and_history_flag(web):
    import_export(web, export_bytes([("Haus", True, "2026-10-01T10:00:00")]))
    assert web.toggle_favorite("Haus") is True
    assert web.history()[0].favorite is True
    assert [f.lemma for f in web.favorites()] == ["Haus"]
    assert web.toggle_favorite("Haus") is False
    assert web.favorites() == []


def test_apply_corrections_right_to_left():
    text = "Ich habe ein Hause und ein Auto"
    issues = [Issue("x", 13, 5, ["Haus"]), Issue("y", 0, 3, ["Wir"])]
    assert apply_corrections(text, issues) == "Wir habe ein Haus und ein Auto"


def test_apply_corrections_skips_overlap_and_empty():
    issues = [Issue("a", 0, 5, ["X"]), Issue("b", 2, 2, ["Y"]), Issue("c", 6, 1, [])]
    assert apply_corrections("abcde fgh", issues) == "X fgh"


def test_check_reports_unreachable_languagetool():
    r = check_sentence("Ich habe ein Haus", ["Haus"], checker=lambda s: None)
    assert not r.checked and not r.ok and r.missing == []


def test_check_corrects_and_reports_missing():
    issue = Issue("Falsche Endung", 13, 4, ["Häuser"])
    r = check_sentence("Ich habe ein Haus", ["Häuser"], checker=lambda s: [issue])
    assert r.missing == ["Häuser"]
    assert r.corrected == "Ich habe ein Häuser"
    assert r.remarks[0].message == "Falsche Endung"


def test_check_ok_and_input_limits():
    assert check_sentence("Ich habe ein Haus", ["Haus"], checker=lambda s: []).ok
    assert check_sentence("", [], checker=lambda s: []).error
    assert check_sentence("Haus", [], checker=lambda s: []).error
    assert "too long" in check_sentence("a " * 200, [], checker=lambda s: []).error


def test_task_and_summary_from_dictionary(dictionary):
    entry = dictionary.find_lemma("Haus")
    task, required = pick_task(entry, random.Random(0))
    assert task and required
    assert any("Plural" in line or "article" in line for line in summary(entry))
