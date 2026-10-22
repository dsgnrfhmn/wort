from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.db import WebStore
from app.main import create_app

PASSWORD = "correct horse battery"
NOW = datetime(2026, 10, 21, 12, 0)


@pytest.fixture
def env(tmp_path, dict_path):
    db = tmp_path / "web.db"
    app = create_app(db_path=db, dict_path=dict_path, secure_cookies=False)
    store = WebStore(db)
    a = store.create_user("anna", auth.hash_password(PASSWORD)).id
    b = store.create_user("ben", auth.hash_password(PASSWORD)).id
    return app, store, a, b


def client_for(app, name):
    c = TestClient(app, follow_redirects=False)
    c.get("/login")
    r = c.post("/login", data={"csrf": c.cookies.get("wort_csrf"), "name": name, "password": PASSWORD})
    assert r.status_code == 303
    return c


def test_list_shows_article_translation_and_score(env):
    app, store, a, _ = env
    store.add_word(a, "Haus", "noun", now=NOW)
    wid = store.words(a)[0].id
    store.record_attempt(a, wid, "form", "article", "p", "das", "correct", now=NOW)
    html = client_for(app, "anna").get("/").text
    assert "das Haus" in html and f'data-word-id="{wid}"' in html and f'href="/words/{wid}"' in html
    assert "1 Wörter" in html


def test_empty_list_has_explicit_state(env):
    app, *_ = env
    assert "Noch keine Wörter" in client_for(app, "anna").get("/").text


def test_bulk_buttons_disabled_until_selection_and_presets_preselect(env):
    app, store, a, _ = env
    for i, lemma in enumerate(["Haus", "Hund", "Katze"]):
        store.add_word(a, lemma, "noun", now=NOW.replace(hour=i))
    c = client_for(app, "anna")
    plain = c.get("/").text
    assert 'data-status="disabled"' in plain and 'data-selected="true"' not in plain
    preset = c.get("/?preset=latest").text
    assert preset.count('data-selected="true"') == 3


def test_sort_and_limit(env):
    app, store, a, _ = env
    for lemma in ["Katze", "Hund", "Haus"]:
        store.add_word(a, lemma, "noun", now=NOW)
    c = client_for(app, "anna")
    html = c.get("/?sort=word&dir=asc").text
    assert html.index("das Haus") < html.index("der Hund") < html.index("die Katze")
    assert c.get("/?sort=bogus&dir=nope&limit=-5").status_code == 200
    assert c.get("/?limit=999999").status_code == 200


def test_detail_has_declension_and_is_private(env):
    app, store, a, _ = env
    store.add_word(a, "Haus", "noun", now=NOW)
    wid = store.words(a)[0].id
    html = client_for(app, "anna").get(f"/words/{wid}").text
    assert "Deklination" in html and "die Häuser" in html and "Dat." in html
    assert client_for(app, "ben").get(f"/words/{wid}").status_code == 404


def test_own_translation_saved_escaped_and_owner_only(env):
    app, store, a, _ = env
    store.add_word(a, "Haus", "noun", now=NOW)
    wid = store.words(a)[0].id
    c = client_for(app, "anna")
    token = c.cookies.get("wort_csrf")
    r = c.post(f"/words/{wid}/translation", data={"csrf": token, "text": "<b>будинок</b>"})
    assert r.status_code == 303
    page = c.get("/").text
    assert "&lt;b&gt;будинок&lt;/b&gt;" in page and "<b>будинок" not in page
    b = client_for(app, "ben")
    assert b.post(f"/words/{wid}/translation", data={"csrf": b.cookies.get("wort_csrf"), "text": "x"}).status_code == 404
    assert c.post(f"/words/{wid}/translation", data={"csrf": token, "text": "x" * 201}).status_code == 400
    assert c.post(f"/words/{wid}/translation", data={"csrf": "forged", "text": "x"}).status_code == 403


def test_delete_only_own_word(env):
    app, store, a, _ = env
    store.add_word(a, "Haus", "noun", now=NOW)
    wid = store.words(a)[0].id
    b = client_for(app, "ben")
    assert b.post(f"/words/{wid}/delete", data={"csrf": b.cookies.get("wort_csrf")}).status_code == 404
    c = client_for(app, "anna")
    assert c.post(f"/words/{wid}/delete", data={"csrf": c.cookies.get("wort_csrf")}).status_code == 303
    assert store.words(a) == []


def test_import_page_adds_words_for_the_logged_in_user(env):
    import json
    from wort.transfer import FORMAT_VERSION
    app, store, a, b = env
    c = client_for(app, "anna")
    raw = json.dumps({"format_version": FORMAT_VERSION, "exported_at": "2026-10-14T10:00:00",
                      "words": [{"lemma": "Hund", "pos": "noun", "added_at": "2026-10-01T10:00:00"}],
                      "queries": []}).encode()
    r = c.post("/import", data={"csrf": c.cookies.get("wort_csrf")}, files={"file": ("e.json", raw)})
    assert r.status_code == 303 and r.headers["location"] == "/"  # words imported: land on the word list
    assert [w.lemma for w in store.words(a)] == ["Hund"] and store.words(b) == []


def history_env(env, queries=("Haus", "Hund", "Zzzzzz")):
    app, store, a, b = env
    from datetime import timedelta
    store.add_history(a, [(q, q != "Zzzzzz", NOW - timedelta(days=i)) for i, q in enumerate(queries)])
    return app, store, a, b


def test_history_offers_learn_and_it_feeds_the_word_list(env):
    app, store, a, _ = history_env(env)
    c = client_for(app, "anna")
    page = c.get("/history").text
    assert page.count('action="/words/learn"') == 2 and "Lernen" in page  # Haus and Hund (found); not Zzzzzz
    assert "nicht gefunden" in page
    r = c.post("/words/learn", data={"csrf": c.cookies.get("wort_csrf"), "query": "Haus"})
    assert r.status_code == 303 and r.headers["location"] == "/history"
    assert [(w.lemma, w.added_from) for w in store.words(a)] == [("Haus", "lookup")]
    assert "in deinen Wörtern" in c.get("/history").text
    assert "in Wörtern" in c.get("/history").text  # the row now says so instead of offering Lernen
    assert "das Haus" in c.get("/").text  # and it shows up in Wörter, ready for Üben


def test_learning_twice_or_an_unknown_word_changes_nothing_and_says_so(env):
    app, store, a, _ = history_env(env)
    c = client_for(app, "anna")
    tok = lambda: c.cookies.get("wort_csrf")  # noqa: E731
    c.post("/words/learn", data={"csrf": tok(), "query": "Haus"})
    c.post("/words/learn", data={"csrf": tok(), "query": "Haus"})
    assert len(store.words(a)) == 1 and "schon in deinen Wörtern" in c.get("/history").text
    c.post("/words/learn", data={"csrf": tok(), "query": "Zzzzzz"})
    assert len(store.words(a)) == 1 and "nicht im Wörterbuch" in c.get("/history").text
    assert c.post("/words/learn", data={"csrf": "forged", "query": "Haus"}).status_code == 403
    assert c.post("/words/learn", data={"csrf": tok(), "query": "\u200b<b>\x1b"}).status_code == 303
    assert len(store.words(a)) == 1


def test_learn_is_per_user(env):
    app, store, a, b = history_env(env)
    cb = client_for(app, "ben")
    cb.post("/words/learn", data={"csrf": cb.cookies.get("wort_csrf"), "query": "Haus"})
    assert store.words(a) == [] and len(store.words(b)) == 1


def test_import_of_history_only_lands_on_the_history_page_with_a_hint(env):
    import json
    from wort.transfer import FORMAT_VERSION
    app, store, a, _ = env
    c = client_for(app, "anna")
    raw = json.dumps({"format_version": FORMAT_VERSION, "exported_at": "2026-10-14T10:00:00", "words": [],
                      "queries": [{"query": "Haus", "found": True, "queried_at": "2026-10-01T10:00:00"}]}).encode()
    r = c.post("/import", data={"csrf": c.cookies.get("wort_csrf")}, files={"file": ("e.json", raw)})
    assert r.headers["location"] == "/history"
    assert "Lernen" in c.get("/history").text


def test_empty_word_list_points_to_the_history(env):
    app, *_ = env
    page = client_for(app, "anna").get("/").text
    assert "Aus Verlauf hinzufügen" in page and 'href="/history"' in page
