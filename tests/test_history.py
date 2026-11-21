"""The history files: add, read, delete, clear, and moving the old query log out of user.db."""

import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

import pytest

from wort import cli, history, paths
from wort.dataschema import Invalid
from wort.history import HistoryStore
from wort.store import Store

T0 = datetime(2026, 11, 21, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def hs(tmp_path) -> HistoryStore:
    return HistoryStore(tmp_path / "repo")


def test_add_creates_the_directory_and_one_line_per_entry(hs):
    assert not hs.root.exists()
    hs.add("word", "Haus", True, now=T0)
    hs.add("sentence", "Ich gehe nach Hause.", now=T0)
    assert hs.path("word").read_text() == '{"text":"Haus","ts":"2026-11-21T12:00:00Z","found":true}\n'
    assert hs.path("sentence").read_text() == '{"text":"Ich gehe nach Hause.","ts":"2026-11-21T12:00:00Z"}\n'


def test_a_rule_breaking_text_writes_nothing(hs):
    for bad in ("$(id)", "a; b", "<b>", "x" * 61):
        with pytest.raises(Invalid):
            hs.add("word", bad)
    assert not hs.path("word").exists()


def test_unique_folds_case_keeps_the_latest_spelling_and_the_order(hs):
    for n, (text, found) in enumerate([("gehen", True), ("Haus", True), ("haus", False), ("gehen", True)]):
        hs.add("word", text, found, now=T0 + timedelta(seconds=n))
    items = hs.unique("word")
    assert [(i.text, i.found, i.count) for i in items] == [("haus", False, 2), ("gehen", True, 2)]  # oldest first; newest last
    assert items[-1].ts == T0 + timedelta(seconds=3)


def test_unique_since_counts_only_a_sessions_own_tries(hs):
    hs.add("word", "old", True, now=T0)
    hs.add("word", "new", True, now=T0 + timedelta(seconds=5))
    assert [i.text for i in hs.unique("word", since=T0 + timedelta(seconds=1))] == ["new"]
    assert hs.unique("word", since=T0 + timedelta(seconds=9)) == []


def test_replace_changes_every_try_keeps_the_time_and_marks_it_found(hs):
    hs.add("word", "Hasu", False, now=T0)
    hs.add("word", "gehen", True, now=T0 + timedelta(seconds=1))
    hs.add("word", "hasu", False, now=T0 + timedelta(seconds=2))
    assert hs.replace("word", "HASU", "Haus") == 2
    entries = hs.read("word")
    assert [(e.text, e.found, e.ts) for e in entries] == [
        ("Haus", True, T0), ("gehen", True, T0 + timedelta(seconds=1)), ("Haus", True, T0 + timedelta(seconds=2))]
    assert hs.replace("word", "nothing", "Haus") == 0


def test_replace_latest_only_leaves_older_tries_alone(hs):
    hs.add("word", "Haus", True, now=T0)  # an older, real lookup of the same text
    hs.add("word", "Haus", True, now=T0 + timedelta(seconds=5))
    assert hs.replace("word", "Haus", "Hose", latest_only=True) == 1
    assert [e.text for e in hs.read("word")] == ["Haus", "Hose"]


def test_replace_refuses_text_that_breaks_the_rules_and_changes_nothing(hs):
    hs.add("word", "Hasu", False, now=T0)
    before = hs.path("word").read_bytes()
    for bad in ("$(id)", "a; b", "x" * 61):
        with pytest.raises(Invalid):
            hs.replace("word", "Hasu", bad)
    assert hs.path("word").read_bytes() == before


def test_delete_removes_every_try_and_keeps_the_rest(hs):
    for text in ("Haus", "gehen", "haus"):
        hs.add("word", text, True, now=T0)
    assert hs.delete("word", "HAUS") == 2
    assert [e.text for e in hs.read("word")] == ["gehen"]
    assert hs.delete("word", "nothing") == 0


def test_delete_is_atomic_and_leaves_no_temporary_file(hs):
    hs.add("word", "Haus", True, now=T0)
    hs.delete("word", "Haus")
    assert hs.path("word").read_text() == ""
    assert sorted(p.name for p in hs.root.iterdir()) == ["words.jsonl"]


def test_clear_one_kind_or_both(hs):
    hs.add("word", "Haus", True, now=T0)
    hs.add("sentence", "Ich gehe nach Hause.", now=T0)
    assert hs.clear("sentence") == 1 and hs.read("word") and not hs.read("sentence")
    assert hs.clear() == 1 and hs.is_empty()
    assert hs.clear() == 0  # nothing left, nothing to fail on


def test_reading_skips_bad_lines_counts_them_and_the_next_rewrite_drops_them(hs):
    hs.add("word", "Haus", True, now=T0)
    with open(hs.path("word"), "ab") as f:
        f.write(b'{"text":"$(id)","ts":"2026-11-21T12:00:00Z","found":true}\nnot json\n')
    hs.add("word", "gehen", True, now=T0)
    assert [e.text for e in hs.read("word")] == ["Haus", "gehen"] and hs.skipped["word"] == 2
    hs.delete("word", "nothing")  # nothing matched, but a rewrite happens to drop the bad lines
    assert hs.path("word").read_text().count("\n") == 2
    hs.read("word")
    assert hs.skipped["word"] == 0


def test_a_missing_directory_or_file_reads_as_empty(hs):
    assert hs.read("word") == [] and hs.is_empty() and hs.unique("sentence") == []


def test_concurrent_writers_do_not_lose_lines(hs):
    def worker(n):
        for i in range(25):
            hs.add("word", f"w{n}x{i}", True, now=T0)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(hs.read("word")) == 100 and hs.skipped["word"] == 0


# --- the old history in user.db -----------------------------------------------------------------------


def _flat(out: str) -> str:
    """Output with its line breaks undone: the console wraps at 80 columns, and where depends on how long the temporary
    path in the message is (it differs from machine to machine)."""
    return " ".join(out.split())


def _legacy_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE queries (id INTEGER PRIMARY KEY, query TEXT NOT NULL, found INTEGER NOT NULL, ts TEXT NOT NULL)")
    conn.executemany("INSERT INTO queries (query, found, ts) VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()


def test_legacy_count(tmp_path):
    assert history.legacy_count(tmp_path / "missing.db") == 0
    Store(tmp_path / "new.db")  # a fresh user.db has no `queries` table any more
    assert history.legacy_count(tmp_path / "new.db") == 0
    _legacy_db(tmp_path / "old.db", [("Haus", 1, "2026-10-04T10:00:00")])
    assert history.legacy_count(tmp_path / "old.db") == 1


def test_migrate_splits_words_from_sentences_and_skips_what_breaks_the_rules(tmp_path, hs):
    db = tmp_path / "user.db"
    _legacy_db(db, [
        ("Haus", 1, "2026-10-04T10:00:00"),
        ("qwertzuiop", 0, "2026-10-04T10:01:00"),  # not found, one word: still a word
        ("gehen Haus", 1, "2026-10-04T10:02:00"),  # found phrase
        ("Hasu gehen", 0, "2026-10-04T10:03:00"),  # two words, not found: a sentence
        ("Ich gehe nach Hause", 0, "2026-10-04T10:04:00"),  # not found, three words: a sentence
        ("x; rm -rf ~", 0, "2026-10-04T10:05:00"),  # breaks the rules
        ("Haus", 1, "not a date"),
    ])
    assert history.migrate(db, hs) == (3, 2, 2, 0)
    assert [(e.text, e.found) for e in hs.read("word")] == [("Haus", True), ("qwertzuiop", False), ("gehen Haus", True)]
    assert [e.text for e in hs.read("sentence")] == ["Hasu gehen", "Ich gehe nach Hause"]  # not found, two or more words
    assert hs.read("word")[0].ts.tzinfo is timezone.utc
    # the old table is untouched
    assert history.legacy_count(db) == 7


def test_migrate_can_classify_like_the_live_lookup(tmp_path, hs):
    """The old log saved a sentence as found whenever one of its words was found."""
    db = tmp_path / "user.db"
    _legacy_db(db, [
        ("gehen", 1, "2026-10-04T10:00:00"),
        ("Haus gehen Haus", 1, "2026-10-04T10:01:00"),  # found, three words: a sentence by the new rule
        ("sich freuen auf", 1, "2026-10-04T10:02:00"),  # found as a phrase: a word
    ])
    sentence_like = lambda text, found: text == "Haus gehen Haus"
    assert history.migrate(db, hs, sentence_like) == (2, 1, 0, 0)
    assert [e.text for e in hs.read("sentence")] == ["Haus gehen Haus"]


def test_migrate_skips_typed_commands(tmp_path, hs):
    db = tmp_path / "user.db"
    _legacy_db(db, [
        ("uv sync --mt group", 1, "2026-10-04T10:00:00"),
        ("import-uk --file /home/x/.cache/dump.jsonl.gz", 1, "2026-10-04T10:01:00"),
        ("Haus", 1, "2026-10-04T10:02:00"),
    ])
    assert history.migrate(db, hs) == (1, 0, 2, 0)


def test_migrate_puts_old_entries_in_front_of_newer_ones_and_can_be_repeated(tmp_path, hs):
    db = tmp_path / "user.db"
    _legacy_db(db, [("Haus", 1, "2026-10-04T10:00:00"), ("gehen", 1, "2026-10-04T10:01:00"), ("Ich gehe nach Hause", 0, "2026-10-04T10:02:00")])
    now = datetime(2026, 11, 21, 15, 0, 0, tzinfo=timezone.utc)
    hs.add("word", "Vertrag", True, now=now)  # written by the new version before the migration
    hs.add("sentence", "ich habe das erledigt", now=now)
    assert history.migrate(db, hs) == (2, 1, 0, 0)
    assert [e.text for e in hs.read("word")] == ["Haus", "gehen", "Vertrag"]  # time order: the new entry stays last
    assert [e.text for e in hs.read("sentence")] == ["Ich gehe nach Hause", "ich habe das erledigt"]
    assert hs.unique("word")[-1].text == "Vertrag"  # so the newest try is still the newest
    before = hs.path("word").read_bytes(), hs.path("sentence").read_bytes()
    assert history.migrate(db, hs) == (0, 0, 0, 3)  # again: nothing is added twice
    assert (hs.path("word").read_bytes(), hs.path("sentence").read_bytes()) == before


def test_merge_keeps_entries_of_the_same_second_in_file_order(hs):
    t = datetime(2026, 11, 21, 12, 0, 0, tzinfo=timezone.utc)
    hs.add("word", "b", True, now=t)
    from wort.dataschema import make_entry

    assert hs.merge([make_entry("word", "a", True, t), make_entry("word", "b", True, t)]) == 1  # `b` at that time is there
    assert [e.text for e in hs.read("word")] == ["b", "a"]


def test_the_migrate_command_uses_the_dictionary_to_find_sentences(dict_path, capsys):
    import shutil

    shutil.copy(dict_path, paths.dictionary_db())
    _legacy_db(paths.user_db(), [("Haus", 1, "2026-10-04T10:00:00"), ("Haus gehen Haus", 1, "2026-10-04T10:04:00")])
    cli.main(["migrate-history"])
    assert "Migrated 1 words and 1 sentences" in _flat(capsys.readouterr().out)
    assert [e.text for e in HistoryStore(paths.data_repo()).read("sentence")] == ["Haus gehen Haus"]
    cli.main(["migrate-history"])  # safe to repeat
    again = _flat(capsys.readouterr().out)
    assert "Migrated 0 words and 0 sentences" in again and "2 already there" in again


def test_the_migrate_command_without_a_dictionary_goes_by_length(capsys):
    _legacy_db(paths.user_db(), [("Haus", 1, "2026-10-04T10:00:00"), ("Ich gehe nach Hause", 0, "2026-10-04T10:04:00")])
    cli.main(["migrate-history"])
    out = _flat(capsys.readouterr().out)
    assert "The dictionary is not imported" in out and "(2+ words and not found)" in out and "Migrated 1 words and 1 sentences" in out


def test_the_migrate_command_without_old_history(capsys):
    cli.main(["migrate-history"])
    assert "Nothing to migrate" in capsys.readouterr().out


def test_session_hints_at_the_old_history_when_the_files_are_empty(monkeypatch, capsys, dict_path):
    import io
    import shutil
    import sys

    from wort import session

    shutil.copy(dict_path, paths.dictionary_db())
    _legacy_db(paths.user_db(), [("Haus", 1, "2026-10-04T10:00:00")])
    stream = io.StringIO("quit\n")
    stream.isatty = lambda: True
    monkeypatch.setattr(sys, "stdin", stream)
    monkeypatch.setattr(session, "_interactive", lambda: True)
    monkeypatch.setattr(os, "get_terminal_size", lambda *a: os.terminal_size((80, 40)))
    cli.main([])
    assert "wort migrate-history" in capsys.readouterr().out


def test_word_rows_carry_the_color_of_a_noun(dictionary):
    from wort import session
    from wort.search import word_meaning

    assert word_meaning(dictionary, "Haus") == ("house; home", "color(34)")  # das: green
    assert word_meaning(dictionary, "Katze")[1] == "color(160)"  # die: red
    assert word_meaning(dictionary, "gehen")[1] == ""  # a verb has no color in the list
    assert word_meaning(dictionary, "schön")[1] == ""  # nor an adjective: only nouns are colored there
    assert word_meaning(dictionary, "house")[1] == ""  # an English word is not a German noun
    store = HistoryStore(paths.data_repo())
    store.add("word", "Haus", True)
    store.add("word", "qwertz", False)
    rows = {r.query: r for r in session._word_items(store, dictionary)}
    assert rows["Haus"].style == "color(34)" and rows["Haus"].meaning == "house; home"
    assert rows["qwertz"].style == "" and rows["qwertz"].meaning == "nothing found"
