import json
import sqlite3
from datetime import datetime, timedelta

import pytest
from wort.transfer import FORMAT_VERSION

from app.db import WebStore
from app.importer import import_export

NOW = datetime(2026, 10, 21, 12, 0)


@pytest.fixture
def web(tmp_path) -> WebStore:
    return WebStore(tmp_path / "web.db")


@pytest.fixture
def two(web):
    return web.create_user("anna", "h1").id, web.create_user("ben", "h2").id


def test_users_are_unique_case_insensitive(web):
    web.create_user("anna", "h")
    with pytest.raises(sqlite3.IntegrityError):
        web.create_user("ANNA", "h")


def test_session_lifecycle(web):
    u = web.create_user("anna", "h")
    web.create_session(u.id, "t1", NOW, NOW + timedelta(days=1))
    assert web.user_for_session("t1", NOW).name == "anna"
    assert web.user_for_session("t1", NOW + timedelta(days=2)) is None  # expired
    web.create_session(u.id, "t2", NOW, NOW + timedelta(days=1))
    web.delete_session("t2")
    assert web.user_for_session("t2", NOW) is None


def test_words_are_isolated_between_users(web, two):
    a, b = two
    web.add_word(a, "Haus", "noun", now=NOW)
    wid = web.words(a)[0].id
    assert web.words(b) == []
    assert web.word(b, wid) is None
    assert web.words_by_ids(b, [wid]) == []
    assert web.record_attempt(b, wid, "form", "article", "p", "x", "correct") is None
    assert web.set_own_translation(b, wid, "x") is False
    assert web.delete_word(b, wid) is False
    assert web.word(a, wid) is not None


def test_same_word_for_two_users_and_duplicates_skipped(web, two):
    a, b = two
    assert web.add_word(a, "Haus", "noun") is True
    assert web.add_word(a, "Haus", "noun") is False
    assert web.add_word(b, "Haus", "noun") is True


def test_attempt_updates_score_streak_due_and_logs(web, two):
    a, _ = two
    web.add_word(a, "Haus", "noun", now=NOW)
    wid = web.words(a)[0].id
    assert web.record_attempt(a, wid, "translation", "flashcard", "Haus?", "house", "correct", now=NOW) == 1
    w = web.word(a, wid)
    assert (w.state.translation, w.state.streak, w.score) == (1, 1, 1)
    assert w.next_due == NOW + timedelta(days=1)
    assert web.record_attempt(a, wid, "translation", "flashcard", "Haus?", "x", "wrong", now=NOW) == -1
    assert web.word(a, wid).next_due == NOW
    n = web.conn.execute("SELECT COUNT(*) FROM attempts WHERE user_id = ?", (a,)).fetchone()[0]
    assert n == 2


def test_history_and_favorites_isolated(web, two):
    a, b = two
    web.add_history(a, [("Haus", True, NOW)])
    web.toggle_favorite(a, "Haus")
    assert web.history(b) == [] and web.favorites(b) == []
    assert web.is_favorite(b, "Haus") is False


def test_import_adds_words_for_the_user_only(web, two):
    a, b = two
    raw = json.dumps({
        "format_version": FORMAT_VERSION, "exported_at": "2026-10-14T10:00:00",
        "words": [{"lemma": "Haus", "pos": "noun", "added_at": "2026-10-01T10:00:00"}],
        "queries": [],
    }).encode()
    r = import_export(web, a, raw)
    assert (r.words_total, r.words_new) == (1, 1)
    assert import_export(web, a, raw).words_new == 0
    assert [w.added_from for w in web.words(a)] == ["cli"] and web.words(b) == []


def test_legacy_v0_db_is_migrated_and_adopted_by_first_user(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE history (id INTEGER PRIMARY KEY, query TEXT NOT NULL, found INTEGER NOT NULL,
            queried_at TEXT NOT NULL, UNIQUE (query, queried_at));
        CREATE TABLE favorites (id INTEGER PRIMARY KEY, lemma TEXT NOT NULL, pos TEXT NOT NULL DEFAULT '',
            added_at TEXT NOT NULL, UNIQUE (lemma, pos));
        INSERT INTO history (query, found, queried_at) VALUES ('Haus', 1, '2026-10-01T10:00:00');
        INSERT INTO favorites (lemma, pos, added_at) VALUES ('Haus', '', '2026-10-01T10:00:00');
    """)
    old.commit(); old.close()
    web = WebStore(path)
    assert web.conn.execute("PRAGMA user_version").fetchone()[0] == 1
    u = web.create_user("anna", "h")
    assert [r.query for r in web.history(u.id)] == ["Haus"]
    assert [f.lemma for f in web.favorites(u.id)] == ["Haus"]
    second = web.create_user("ben", "h")
    assert web.history(second.id) == []


def test_ai_usage_counter_is_per_user_and_day(web, two):
    a, b = two
    assert web.ai_calls_today(a, "2026-10-21") == 0
    assert web.ai_count_call(a, "2026-10-21") == 1
    assert web.ai_count_call(a, "2026-10-21") == 2
    assert web.ai_calls_today(b, "2026-10-21") == 0
    assert web.ai_calls_today(a, "2026-10-22") == 0
