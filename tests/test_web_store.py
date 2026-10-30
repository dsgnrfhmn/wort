import json
import sqlite3
from datetime import datetime, timedelta

import pytest
from wort.transfer import FORMAT_VERSION

from app.db import SCHEMA, SCHEMA_VERSION, WebStore
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
    assert web.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
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


def test_no_write_lock_is_left_open_between_calls(tmp_path):
    """A second connection (the admin script) must be able to write while the app is idle."""
    path = tmp_path / "w.db"
    app_store, admin = WebStore(path), WebStore(path)
    u = app_store.create_user("anna", "h")
    app_store.create_session(u.id, "t", NOW, NOW + timedelta(days=1))
    assert app_store.user_for_session("t", NOW) is not None
    admin.create_user("ben", "h")  # raises "database is locked" if the app left a transaction open
    assert app_store.user_by_name("ben") is not None


def test_revise_attempt_equals_grading_the_new_verdict(web, two):
    a, _ = two
    web.add_word(a, "Haus", "noun", now=NOW)
    wid = web.words(a)[0].id
    web.record_attempt(a, wid, "form", "article", "p", "x", "correct", now=NOW)
    aid, delta = web.record_attempt_full(a, wid, "usage", "sentence", "p", "x", "wrong", now=NOW)
    assert web.revise_attempt(a, aid, "correct", now=NOW) == 0  # mean of form 1 and usage 1 stays 1
    revised = web.word(a, wid)
    ref = WebStore(":memory:")
    uid = ref.create_user("r", "h").id
    ref.add_word(uid, "Haus", "noun", now=NOW)
    rid = ref.words(uid)[0].id
    ref.record_attempt(uid, rid, "form", "article", "p", "x", "correct", now=NOW)
    ref.record_attempt(uid, rid, "usage", "sentence", "p", "x", "correct", now=NOW)
    assert (revised.state, revised.score) == (ref.word(uid, rid).state, ref.word(uid, rid).score)
    assert web.conn.execute("SELECT verdict FROM attempts WHERE id = ?", (aid,)).fetchone()[0] == "correct"


def test_revise_only_the_latest_attempt_and_only_own(web, two):
    a, b = two
    web.add_word(a, "Haus", "noun", now=NOW)
    wid = web.words(a)[0].id
    first, _ = web.record_attempt_full(a, wid, "form", "article", "p", "x", "wrong", now=NOW)
    web.record_attempt_full(a, wid, "form", "article", "p", "x", "wrong", now=NOW)
    assert web.revise_attempt(a, first, "correct") is None  # not the latest any more
    latest = web.conn.execute("SELECT MAX(id) FROM attempts").fetchone()[0]
    assert web.revise_attempt(b, latest, "correct") is None  # not the owner


def test_v1_database_is_migrated_to_current(tmp_path):
    path = tmp_path / "v1.db"
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE, password_hash TEXT NOT NULL, created_at TEXT NOT NULL);
        INSERT INTO users VALUES (1, 'anna', 'h', '2026-10-01T00:00:00');
        CREATE TABLE history (id INTEGER PRIMARY KEY, user_id INTEGER, query TEXT NOT NULL, found INTEGER NOT NULL, queried_at TEXT NOT NULL, UNIQUE (user_id, query, queried_at));
        CREATE TABLE attempts (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, word_id INTEGER NOT NULL, skill TEXT NOT NULL, kind TEXT NOT NULL, prompt TEXT NOT NULL, answer TEXT NOT NULL, verdict TEXT NOT NULL, delta INTEGER NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE practice_sessions (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('saetze', 'abfrage')), items TEXT NOT NULL, pos INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
        INSERT INTO practice_sessions VALUES (1, 1, 'saetze', '[]', 0, '2026-10-01T00:00:00');
        PRAGMA user_version = 1;
    """)
    con.commit(); con.close()
    web = WebStore(path)
    assert web.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert web.practice(1, 1)["kind"] == "saetze"
    assert web.create_practice(1, "regel", []) > 0  # new kind accepted
    assert {"state_before", "task", "expected", "corrected", "rule"} <= {
        r["name"] for r in web.conn.execute("PRAGMA table_info(attempts)")}


def test_v2_database_gets_the_sync_tokens_table(tmp_path):
    path = tmp_path / "v2.db"
    WebStore(path)  # current schema
    con = sqlite3.connect(path)
    con.executescript("DROP TABLE sync_tokens; PRAGMA user_version = 2;")
    con.commit(); con.close()
    web = WebStore(path)
    u = web.create_user("anna", "h")
    tid = web.create_sync_token(u.id, "hash", "laptop")
    assert web.user_for_sync_token("hash").id == u.id and web.user_for_sync_token("other") is None
    assert web.revoke_sync_token(u.id, tid) and web.user_for_sync_token("hash") is None


def test_sync_tokens_are_scoped_to_their_owner(web, two):
    a, b = two
    tid = web.create_sync_token(a, "h")
    assert web.revoke_sync_token(b, tid) is False  # another user cannot revoke it
    assert web.sync_tokens(b) == [] and web.user_for_sync_token("h").id == a


def test_v4_database_gets_the_attempt_details(tmp_path):
    path = tmp_path / "v4.db"
    WebStore(path)
    con = sqlite3.connect(path)
    con.executescript("""
        ALTER TABLE attempts DROP COLUMN task; ALTER TABLE attempts DROP COLUMN expected;
        ALTER TABLE attempts DROP COLUMN corrected; ALTER TABLE attempts DROP COLUMN rule;
        ALTER TABLE users DROP COLUMN ui_lang;
        INSERT INTO users VALUES (1, 'anna', 'h', '2026-10-01T00:00:00');
        INSERT INTO user_words (id, user_id, lemma, pos, added_at) VALUES (1, 1, 'Haus', 'noun', '2026-10-01T00:00:00');
        INSERT INTO attempts (user_id, word_id, skill, kind, prompt, answer, verdict, delta, created_at)
            VALUES (1, 1, 'form', 'article', 'p', 'der', 'wrong', -1, '2026-10-02T00:00:00');
        PRAGMA user_version = 4;
    """)
    con.commit(); con.close()
    web = WebStore(path)
    assert web.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    old = web.attempts(1, 1)[0]
    assert (old.answer, old.task, old.expected, old.corrected, old.rule) == ("der", "", "", "", "")
    assert web.conn.execute("SELECT ui_lang FROM users WHERE id = 1").fetchone()[0] == "en"  # v5 -> v6
    web.record_attempt_full(1, 1, "form", "sentence", "p", "Ich sehe der Haus.", "wrong",
                            details={"task": "Akkusativ Singular", "expected": "das … Haus",
                                     "corrected": "Ich sehe das Haus.", "rule": "x" * 999})
    new = web.attempts(1, 1)[0]
    assert (new.task, new.expected, new.corrected, len(new.rule)) == ("Akkusativ Singular", "das … Haus",
                                                                      "Ich sehe das Haus.", 300)


def test_v6_database_may_hold_words_from_texts_and_keeps_every_answer(tmp_path):
    """v6 -> v7: user_words.added_from gets 'text'; the table is rebuilt, so the answers must still point at their words."""
    path = tmp_path / "v6.db"
    con = sqlite3.connect(path)
    con.executescript(SCHEMA.replace(", 'practice', 'text')", ", 'practice')") + """
        INSERT INTO users (id, name, password_hash, created_at) VALUES (1, 'anna', 'h', '2026-10-01T00:00:00');
        INSERT INTO user_words (id, user_id, lemma, pos, added_at, own_translation) VALUES (7, 1, 'Haus', 'noun', '2026-10-01T00:00:00', 'house');
        INSERT INTO attempts (user_id, word_id, skill, kind, prompt, answer, verdict, delta, created_at)
            VALUES (1, 7, 'form', 'sentence', 'p', 'a', 'correct', 5, '2026-10-02T00:00:00');
        PRAGMA user_version = 6;
    """)
    assert "'text'" not in con.execute("SELECT sql FROM sqlite_master WHERE name = 'user_words'").fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError):  # the old table really refuses it
        con.execute("INSERT INTO user_words (user_id, lemma, pos, added_from, added_at) VALUES (1, 'x', '', 'text', '2026-10-01T00:00:00')")
    con.commit(); con.close()

    web = WebStore(path)
    assert web.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    word = web.words(1)[0]
    assert (word.id, word.lemma, word.own_translation) == (7, "Haus", "house")
    assert len(web.attempts(1, 7)) == 1  # the answer still belongs to its word (the query joins on word_id)
    assert web.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert web.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert web.add_word(1, "Das ist ein Satz", "phrase", added_from="text") is True
    assert web.add_word(1, "Das ist ein Satz", "phrase", added_from="text") is False  # the same phrase once
    with pytest.raises(sqlite3.IntegrityError):  # the CHECK still guards the other values
        web.conn.execute("INSERT INTO user_words (user_id, lemma, added_from, added_at) VALUES (1, 'y', 'bogus', '2026-10-01T00:00:00')")
    web.conn.rollback()  # the refused INSERT left a transaction open
    WebStore(path)  # opening it again changes nothing
