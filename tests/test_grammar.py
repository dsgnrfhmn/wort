import json
import random

import pytest
from fastapi.testclient import TestClient

from app import auth, grammar
from app.db import WebStore
from app.main import create_app
from wort.dictionary.lookup import Dictionary
from wort.exercises.grammar_check import Issue

PASSWORD = "correct horse battery"


def item(topic, kind, n=0):
    i = [k for k, e in enumerate(grammar.TOPICS[topic]["exercises"]) if e["type"] == kind][n]
    return {"kind": "grammar", "topic": topic, "ex": i}


def test_every_topic_has_all_four_exercise_types_and_a_table():
    for key, t in grammar.TOPICS.items():
        assert {e["type"] for e in t["exercises"]} == {"luecke", "mc", "umbau", "eigen"}, key
        assert any(s.get("table") for s in t["sections"]), key


def test_gap_and_choice_are_compared_without_case_umlauts_or_punctuation(dict_path):
    dic = Dictionary(dict_path)
    gap = item("modalverben", "luecke")
    assert grammar.grade(gap, "kann", lambda s: [], dic)[0] == "correct"
    assert grammar.grade(gap, "Kann.", lambda s: [], dic)[0] == "correct"
    assert grammar.grade(gap, "konnte", lambda s: [], dic)[0] == "wrong"
    q = item("praepositionen", "mc")  # auf ___ Tisch → den
    right = grammar.exercise(q)["choices"].index("den") + 1
    assert grammar.grade(q, str(right), lambda s: [], dic)[0] == "correct"
    assert grammar.grade(q, "dem", lambda s: [], dic)[0] == "wrong"
    assert grammar.grade(q, "", lambda s: [], dic)[5] is False  # empty: the task stays open


def test_rewrite_accepts_any_listed_sentence(dict_path):
    dic = Dictionary(dict_path)
    r = item("modalverben", "umbau")
    assert grammar.grade(r, "heute muss ich arbeiten", lambda s: [], dic)[0] == "correct"
    verdict, expected, *_ = grammar.grade(r, "Ich arbeite heute muss.", lambda s: [], dic)
    assert verdict == "wrong" and "Ich muss heute arbeiten." in expected


def test_own_sentence_checks_the_structure_then_languagetool(dict_path):
    dic = Dictionary(dict_path)
    weil = item("nebensaetze", "eigen")
    assert grammar.grade(weil, "Ich lerne Deutsch, weil ich hier gehe.", lambda s: [], dic)[0] == "correct"
    wrong = grammar.grade(weil, "Ich lerne Deutsch, weil ich gehe hier.", lambda s: [], dic)
    assert wrong[0] == "wrong" and "Verb am Ende" in wrong[2]
    missing = grammar.grade(weil, "Ich lerne Deutsch für die Arbeit.", lambda s: [], dic)
    assert missing[0] == "wrong" and "weil" in missing[2]
    issue = Issue("Tippfehler", 0, 3, ["Ich"], "UPPERCASE_SENTENCE_START", "CASING")
    almost = grammar.grade(weil, "ich lerne Deutsch, weil ich hier gehe.", lambda s: [issue], dic)
    assert almost[0] == "almost" and almost[3]
    unchecked = grammar.grade(weil, "Ich lerne Deutsch, weil ich hier gehe.", lambda s: None, dic)
    assert unchecked[0] is None


def test_modal_infinitive_must_close_the_sentence(dict_path):
    dic = Dictionary(dict_path)
    m = item("modalverben", "eigen")
    assert grammar.grade(m, "Ich muss heute nach Hause gehen.", lambda s: [], dic)[0] == "correct"
    assert grammar.grade(m, "Ich muss gehen heute nach Hause.", lambda s: [], dic)[0] == "wrong"


def test_malformed_grammar_file_fails_loud(tmp_path):
    bad = tmp_path / "g.json"
    good = json.loads(grammar.PATH.read_text(encoding="utf-8"))
    topic = next(iter(good.values()))
    for broken in ({}, {"Bad Id": topic},
                   {"x": {**topic, "exercises": [{"type": "mc", "prompt": "?", "why": "", "choices": ["a"], "answers": ["b"]}]}},
                   {"x": {**topic, "exercises": [{"type": "eigen", "prompt": "?", "why": "", "rules": {"nope": 1}}]}}):
        bad.write_text(json.dumps(broken))
        with pytest.raises(ValueError):
            grammar._load(bad)


def test_grammar_tab_topic_page_and_a_session(tmp_path, dict_path):
    app = create_app(db_path=tmp_path / "web.db", dict_path=dict_path, secure_cookies=False, checker=lambda s: [])
    store = WebStore(tmp_path / "web.db")
    uid = store.create_user("anna", auth.hash_password(PASSWORD)).id
    c = TestClient(app, follow_redirects=False, client=("127.0.0.1", 50000))
    c.get("/login")
    c.post("/login", data={"csrf": c.cookies.get("wort_csrf"), "name": "anna", "password": PASSWORD})
    start = c.get("/ueben?modus=grammatik").text
    assert 'href="/ueben?neu=1&amp;modus=grammatik"' in start and 'href="/grammatik/modalverben"' in start
    page = c.get("/grammatik/modalverben").text
    assert ">Modalverben<" in page and ">möchtest<" in page and 'action="/ueben/grammatik/modalverben"' in page
    assert c.get("/grammatik/nope").status_code == 404
    r = c.post("/ueben/grammatik/modalverben", data={"csrf": c.cookies.get("wort_csrf")})
    loc = r.headers["location"]
    sid = int(loc.rsplit("/", 1)[1])
    first = store.practice(uid, sid)["items"][0]
    ex = grammar.exercise(first)
    html = c.get(loc).text
    assert ex["prompt"].replace("«", "&laquo;")[:10] in html or ex["prompt"][:10] in html
    answer = (ex.get("answers") or [ex.get("example")])[0]
    c.post(f"/ueben/s/{sid}/answer", data={"csrf": c.cookies.get("wort_csrf"), "text": answer, "at": 0})
    res = store.practice(uid, sid)["items"][0]["result"]
    assert res["verdict"] in ("correct", "almost") and res["delta"] is None
    assert store.grammar_progress(uid)["modalverben"][1] == 1
    assert "1 / 1" in c.get("/ueben?neu=1&modus=grammatik").text or "0 / 1" in c.get("/ueben?neu=1&modus=grammatik").text


def test_a_verb_the_dictionary_does_not_know_is_not_held_against_the_sentence(dict_path):
    dic = Dictionary(dict_path)  # the fixture has no "arbeiten"
    m = item("modalverben", "eigen")
    assert grammar.grade(m, "Ich muss heute arbeiten.", lambda s: [], dic)[0] == "correct"
    assert grammar.grade(m, "Ich muss heute ein Haus.", lambda s: [], dic)[0] == "wrong"  # a known noun at the end
