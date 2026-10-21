import random
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app import auth, practice
from app.db import WebStore
from app.main import create_app
from wort.dictionary.lookup import Dictionary
from wort.exercises.grammar_check import Issue

PASSWORD = "correct horse battery"


@pytest.fixture
def env(tmp_path, dict_path):
    db = tmp_path / "web.db"
    app = create_app(db_path=db, dict_path=dict_path, secure_cookies=False, checker=lambda s: [])
    store = WebStore(db)
    a = store.create_user("anna", auth.hash_password(PASSWORD)).id
    b = store.create_user("ben", auth.hash_password(PASSWORD)).id
    for lemma, pos in [("Haus", "noun"), ("gehen", "verb")]:
        store.add_word(a, lemma, pos)
    return app, store, a, b


def login(app, name):
    c = TestClient(app, follow_redirects=False)
    c.get("/login")
    c.post("/login", data={"csrf": c.cookies.get("wort_csrf"), "name": name, "password": PASSWORD})
    return c


def start(c, store, uid, kind, ids=None):
    ids = ids or [w.id for w in store.words(uid)]
    r = c.post(f"/ueben/{kind}", data={"csrf": c.cookies.get("wort_csrf"), "ids": ids})
    assert r.status_code == 303, r.text
    return r.headers["location"]


def test_build_items_round_robin_and_abfrage(dict_path):
    dic = Dictionary(dict_path)
    store_words = [(type("W", (), {"id": i})(), dic.find_lemma(l)) for i, l in [(1, "Haus"), (2, "gehen")]]
    items = practice.build_items("saetze", store_words, random.Random(1))
    assert len(items) == 5 and {i["word_id"] for i in items} == {1, 2} and all(i["kind"] == "sentence" for i in items)
    ab = practice.build_items("abfrage", store_words, random.Random(1))
    assert len(ab) == 2 and all("seed" in i for i in ab)


def test_grade_sentence_cases():
    ok = practice.grade_sentence("Ich sehe die Häuser dort", ["Häuser"], lambda s: [])
    assert ok.verdict == "correct"
    missing = practice.grade_sentence("Ich sehe das Haus dort", ["Häuser"], lambda s: [])
    assert missing.verdict == "wrong" and missing.missing == ["Häuser"]
    unchecked = practice.grade_sentence("Ich sehe die Häuser dort", ["Häuser"], lambda s: None)
    assert unchecked.verdict is None and unchecked.final is True and unchecked.checked is False
    short = practice.grade_sentence("Häuser", ["Häuser"], lambda s: [])
    assert short.verdict is None and short.final is False
    remark = practice.grade_sentence("Ich sehe die Häuser dort", ["Häuser"],
                                     lambda s: [Issue("Stil", 4, 4, ["sah"])])
    assert remark.verdict == "almost"


def test_full_abfrage_session_updates_scores(env, dict_path):
    app, store, a, _ = env
    c = login(app, "anna")
    loc = start(c, store, a, "abfrage")
    sid = int(loc.rsplit("/", 1)[1])
    page = c.get(loc).text
    assert "Aufgabe 1 / 2" in page
    for _ in range(2):
        sess = store.practice(a, sid)
        item = sess["items"][sess["pos"]]
        word = store.word(a, item["word_id"])
        dic = Dictionary(dict_path)
        entry = dic.find_lemma(word.lemma, word.pos or None)
        _, _, _, ex, _ = practice.rebuild(item, entry)
        right = ex.check("zzz").expected.split(";")[0].strip()
        c.post(f"/ueben/s/{sid}/answer", data={"csrf": c.cookies.get("wort_csrf"), "text": right})
        c.post(f"/ueben/s/{sid}/next", data={"csrf": c.cookies.get("wort_csrf")})
    done = c.get(loc).text
    assert "Ergebnis" in done
    n = store.conn.execute("SELECT COUNT(*) FROM attempts WHERE user_id = ?", (a,)).fetchone()[0]
    assert n == 2


def test_sentence_session_with_unreachable_grammar_check_gives_no_score(tmp_path, dict_path):
    db = tmp_path / "w.db"
    app = create_app(db_path=db, dict_path=dict_path, secure_cookies=False, checker=lambda s: None)
    store = WebStore(db)
    a = store.create_user("anna", auth.hash_password(PASSWORD)).id
    store.add_word(a, "Haus", "noun")
    c = login(app, "anna")
    loc = start(c, store, a, "saetze")
    sid = int(loc.rsplit("/", 1)[1])
    item = store.practice(a, sid)["items"][0]
    entry = Dictionary(dict_path).find_lemma("Haus", "noun")
    required = practice.rebuild(item, entry)[4]
    c.post(f"/ueben/s/{sid}/answer", data={"csrf": c.cookies.get("wort_csrf"), "text": "Ich sehe " + " ".join(required) + " dort"})
    page = c.get(loc).text
    assert "nicht geprüft" in page and store.words(a)[0].score is None


def test_other_users_cannot_open_or_answer_a_session_or_use_foreign_word_ids(env):
    app, store, a, b = env
    ca = login(app, "anna")
    loc = start(ca, store, a, "abfrage")
    sid = int(loc.rsplit("/", 1)[1])
    cb = login(app, "ben")
    assert cb.get(loc).status_code == 404
    assert cb.post(f"/ueben/s/{sid}/answer", data={"csrf": cb.cookies.get("wort_csrf"), "text": "x"}).status_code == 404
    r = cb.post("/ueben/abfrage", data={"csrf": cb.cookies.get("wort_csrf"), "ids": [w.id for w in store.words(a)]})
    assert r.status_code == 303 and r.headers["location"] == "/"  # nothing usable, no session
    assert "keine" in cb.get("/").text  # the one-time message comes from a server-set cookie, not the URL


def test_csrf_and_input_limits(env):
    app, store, a, _ = env
    c = login(app, "anna")
    assert c.post("/ueben/saetze", data={"csrf": "forged", "ids": [1]}).status_code == 403
    assert c.post("/ueben/saetze", data={"csrf": c.cookies.get("wort_csrf")}).status_code == 400
    assert c.post("/ueben/bogus", data={"csrf": c.cookies.get("wort_csrf"), "ids": [1]}).status_code == 404
    loc = start(c, store, a, "saetze")
    sid = int(loc.rsplit("/", 1)[1])
    r = c.post(f"/ueben/s/{sid}/answer", data={"csrf": c.cookies.get("wort_csrf"), "text": "x" * 5000})
    assert r.status_code == 303  # capped, not an error
    assert len(store.conn.execute("SELECT answer FROM attempts").fetchall()) <= 1
