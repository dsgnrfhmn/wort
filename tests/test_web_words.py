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
    assert r.status_code == 303 and r.headers["location"].startswith("/history")
    assert [w.lemma for w in store.words(a)] == ["Hund"] and store.words(b) == []
